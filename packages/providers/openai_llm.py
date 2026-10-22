"""Stateless Responses API adapter. Schema validity does not establish factual support."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from packages.rag.prompts import ANSWER_SCHEMA, token_upper_bound, user_content

from .contracts import Claim, LLMRequest, LLMResult, ModelInfo, ProviderError, Usage
from .openai_http import post_json


class _Content(BaseModel):
    model_config = ConfigDict(strict=True)
    type: str
    text: str | None = None


class _Item(BaseModel):
    model_config = ConfigDict(strict=True)
    type: str
    role: str | None = None
    status: str | None = None
    content: list[_Content] = Field(default_factory=list)


class _Usage(BaseModel):
    model_config = ConfigDict(strict=True)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class _Response(BaseModel):
    model_config = ConfigDict(strict=True)
    status: str
    model: str
    output: list[_Item]
    usage: _Usage


class _Claim(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] = Field(min_length=1, max_length=8)


class _Answer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    text: str = Field(max_length=12000)
    claims: list[_Claim] = Field(max_length=20)


class OpenAILLMProvider:
    def __init__(
        self,
        key: SecretStr | None,
        model: str,
        revision: str,
        input_budget: int = 6000,
        output_tokens: int = 1024,
    ) -> None:
        if key is None or not key.get_secret_value().strip():
            raise ProviderError("LLM_KEY_MISSING")
        if not model.strip():
            raise ProviderError("LLM_MODEL_MISSING")
        self._key, self._model = key, ModelInfo(model, revision, "REAL")
        self.input_budget, self.output_tokens = input_budget, output_tokens

    @property
    def model(self) -> ModelInfo:
        return self._model

    def _request(self, payload: dict[str, object]) -> object:
        return post_json(self._key, "responses", payload)

    def generate(self, request: LLMRequest) -> LLMResult:
        if token_upper_bound(request) > self.input_budget:
            raise ProviderError("LLM_INPUT_LIMIT")
        try:
            response = _Response.model_validate(
                self._request(
                    {
                        "model": self.model.name,
                        "store": False,
                        "max_output_tokens": self.output_tokens,
                        "input": [
                            {"role": "system", "content": request.system_prompt},
                            {"role": "user", "content": user_content(request)},
                        ],
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": "documint_answer",
                                "strict": True,
                                "schema": ANSWER_SCHEMA,
                            }
                        },
                    }
                )
            )
            if response.model != self.model.name:
                raise ProviderError("LLM_MODEL_MISMATCH")
            if response.status != "completed":
                raise ProviderError("LLM_INCOMPLETE")
            texts = []
            for item in response.output:
                if item.type == "reasoning":
                    continue
                if item.type != "message" or item.role != "assistant" or item.status != "completed":
                    raise ProviderError("LLM_UNEXPECTED_OUTPUT")
                for content in item.content:
                    if content.type == "refusal":
                        raise ProviderError("LLM_REFUSED")
                    if content.type != "output_text" or content.text is None:
                        raise ProviderError("LLM_UNEXPECTED_OUTPUT")
                    texts.append(content.text)
            if len(texts) != 1:
                raise ProviderError("LLM_RESPONSE_INVALID")
            answer = _Answer.model_validate_json(texts[0])
        except ValidationError as exc:
            raise ProviderError("LLM_RESPONSE_INVALID") from exc
        return LLMResult(
            answer.text,
            tuple(Claim(c.text, tuple(c.source_ids)) for c in answer.claims),
            self.model,
            Usage(
                input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens
            ),
        )
