"""Scripted synthetic demo, not a generative model or a semantic quality evaluator."""

from pathlib import Path

from evals.schema import GoldenDataset

from .contracts import Claim, LLMRequest, LLMResult, ModelInfo
from .fake import FAKE_USAGE, INSUFFICIENT_EVIDENCE


class DemoLLMProvider:
    def __init__(self) -> None:
        path = Path(__file__).resolve().parents[2] / "evals/golden.json"
        self.dataset = GoldenDataset.model_validate_json(path.read_text("utf-8"))

    @property
    def model(self) -> ModelInfo:
        return ModelInfo("fake-corpus-scripted", "golden-" + self.dataset.version, "FAKE")

    def generate(self, request: LLMRequest) -> LLMResult:
        fallback = LLMResult(INSUFFICIENT_EVIDENCE, (), self.model, FAKE_USAGE)
        case = next(
            (
                case
                for case in self.dataset.cases
                if case.category == "answerable" and case.question == request.question
            ),
            None,
        )
        if case is None:
            return fallback
        claims: list[Claim] = []
        for reference in case.evidence:
            found = next(
                (
                    (source, line.strip())
                    for source in request.evidence
                    for line in source.text.splitlines()
                    if reference.quote in line
                ),
                None,
            )
            if found is None:
                return fallback
            source, text = found
            claim = Claim(text, (source.source_id,))
            if claim not in claims:
                claims.append(claim)
        return LLMResult(
            " ".join(claim.text for claim in claims), tuple(claims), self.model, FAKE_USAGE
        )
