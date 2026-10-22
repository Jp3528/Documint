import hashlib
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.config import Settings
from packages.identity.policies import Actor
from packages.providers.contracts import (
    Claim,
    EmbeddingProvider,
    LLMProvider,
    ModelInfo,
    ProviderError,
    Usage,
)
from packages.providers.fake import INSUFFICIENT_EVIDENCE
from packages.retrieval.citations import Citation, CitationService
from packages.retrieval.contracts import RetrievalResult, SearchRequest
from packages.retrieval.service import RetrievalService

from .context import ContextBuilder, ContextConfig
from .models import GenerationRun, GenerationSource
from .prompts import PROMPT_VERSION


class AnswerView(BaseModel):
    id: UUID
    text: str
    abstained: bool
    claims: tuple[Claim, ...]
    citations: tuple[Citation, ...]
    model: ModelInfo
    embedding_mode: Literal["FAKE", "REAL"] | None
    retrieval_method: str
    retrieval_usage: Usage
    llm_usage: Usage
    prompt_version: str
    context_token_upper_bound: int
    citation_integrity: Literal["PASS", "FAIL", "NOT_APPLICABLE"]
    support_status: str = "NOT_EVALUATED"


@dataclass(frozen=True)
class AnswerOutcome:
    view: AnswerView
    used_source_ids: tuple[UUID, ...]


class AnswerService:
    def __init__(
        self,
        db: Session,
        actor: Actor,
        settings: Settings,
        embedding: EmbeddingProvider,
        llm: LLMProvider,
    ) -> None:
        self.db, self.actor, self.settings = db, actor, settings
        self.embedding, self.llm = embedding, llm

    def answer(self, request: SearchRequest) -> AnswerOutcome:
        retrieval = RetrievalService(self.db, self.actor)
        result: RetrievalResult = (
            retrieval.lexical(request)
            if request.method == "lexical"
            else retrieval.vector(request, self.embedding)
            if request.method == "vector"
            else retrieval.hybrid(request, self.embedding)
        )
        config = ContextConfig(
            token_budget=self.settings.context_token_budget,
            max_chunks=self.settings.context_max_chunks,
            max_per_document=self.settings.context_max_per_document,
            neighbor_radius=self.settings.context_neighbor_radius,
        )
        context = ContextBuilder(self.db, retrieval.actor, config).build(
            request.query, result.candidates
        )
        base = AnswerView(
            id=uuid4(),
            text=INSUFFICIENT_EVIDENCE,
            abstained=True,
            claims=(),
            citations=(),
            model=self.llm.model,
            embedding_mode=result.embedding_mode,
            retrieval_method=result.method,
            retrieval_usage=result.usage,
            llm_usage=Usage(observed_cost_usd=Decimal(0)),
            prompt_version=PROMPT_VERSION,
            context_token_upper_bound=context.token_upper_bound,
            citation_integrity="NOT_APPLICABLE",
        )

        def finish(error_code: str | None = None) -> AnswerOutcome:
            data = base.model_dump(mode="json")
            run = GenerationRun(
                id=base.id,
                actor_id=self.actor.id,
                question_sha256=hashlib.sha256(request.query.encode()).hexdigest(),
                status="FAILED" if error_code else "ABSTAINED" if base.abstained else "ANSWERED",
                model_info=asdict(base.model),
                prompt_version=base.prompt_version,
                context_token_upper_bound=base.context_token_upper_bound,
                error_code=error_code,
                retrieval_config={
                    "method": result.method,
                    "strategy_version": result.strategy_version,
                    "fusion": result.configuration,
                    "embedding_model": asdict(self.embedding.model)
                    if result.embedding_mode
                    else None,
                },
                usage={"retrieval": data["retrieval_usage"], "llm": data["llm_usage"]},
            )
            self.db.add(run)
            self.db.flush()
            cited = {citation.chunk_id for citation in base.citations}
            self.db.add_all(
                GenerationSource(run_id=run.id, chunk_id=key, cited=key in cited)
                for key in context.source_ids
            )
            self.db.commit()
            return AnswerOutcome(base, context.source_ids)

        if not context.source_ids:
            return finish()
        self.db.commit()  # Release database locks before the external model call.
        try:
            response = self.llm.generate(context.request)
            if response.model != self.llm.model:
                raise ProviderError("LLM_MODEL_MISMATCH")
        except ProviderError as exc:
            self.db.rollback()
            base.llm_usage = Usage()  # A lost/failed response has unknown billed usage.
            finish(exc.code)
            raise
        base.llm_usage = response.usage
        if not response.claims:
            return finish()
        if (
            len(response.claims) > 20
            or response.text != " ".join(c.text for c in response.claims)
            or any(
                not c.text.strip() or len(c.text) > 2000 or not c.source_ids
                for c in response.claims
            )
        ):
            base.citation_integrity = "FAIL"
            return finish()
        try:
            ids = tuple(
                dict.fromkeys(UUID(key) for claim in response.claims for key in claim.source_ids)
            )
        except (ValueError, TypeError, AttributeError):
            base.citation_integrity = "FAIL"
            return finish()
        citations = CitationService(self.db, retrieval.actor)
        available = citations.sources(context.source_ids, active_only=True)
        if set(available) != set(context.source_ids) or not set(ids) <= set(context.source_ids):
            base.citation_integrity = "FAIL"
            return finish()
        base.text, base.abstained, base.claims = response.text, False, response.claims
        base.citation_integrity = "PASS"
        base.citations = tuple(Citation.model_validate(available[key].model_dump()) for key in ids)
        return finish()
