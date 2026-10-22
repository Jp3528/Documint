"""Explicit real adapter. No implicit fallback, automatic retries, pricing guesses or logs."""

import json
from collections.abc import Sequence
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from .contracts import EmbeddingBatch, ModelInfo, ProviderError, Usage
from .validation import validate_batch


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_opener = build_opener(_NoRedirect())


class _Vector(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    index: int = Field(ge=0)
    embedding: list[float]


class _Usage(BaseModel):
    model_config = ConfigDict(strict=True)
    prompt_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class _Response(BaseModel):
    model_config = ConfigDict(strict=True)
    model: str
    data: list[_Vector]
    usage: _Usage


class OpenAIEmbeddingProvider:
    def __init__(
        self, api_key: SecretStr | None, model: str, revision: str, dimensions: int
    ) -> None:
        if api_key is None or not api_key.get_secret_value().strip():
            raise ProviderError("EMBEDDING_KEY_MISSING")
        self._key = api_key
        self._model = ModelInfo(model, revision, "REAL", dimensions)

    @property
    def model(self) -> ModelInfo:
        return self._model

    def _request(self, payload: dict[str, object]) -> object:
        request = Request(
            "https://api.openai.com/v1/embeddings",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + self._key.get_secret_value(),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with _opener.open(request, timeout=30) as response:
                content = response.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                raise ProviderError("EMBEDDING_RESPONSE_LIMIT")
            return json.loads(content)
        except (URLError, OSError, ValueError) as exc:
            raise ProviderError("EMBEDDING_REQUEST_FAILED") from exc

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        # UTF-8 byte counts conservatively bound tokens, without a model-specific tokenizer.
        if (
            not texts
            or len(texts) > 32
            or any(not text.strip() or len(text.encode("utf-8")) > 8192 for text in texts)
        ):
            raise ProviderError("EMBEDDING_INPUT_LIMIT")
        try:
            response = _Response.model_validate(
                self._request(
                    {
                        "model": self.model.name,
                        "input": list(texts),
                        "dimensions": self.model.dimensions,
                        "encoding_format": "float",
                    }
                )
            )
        except ValidationError as exc:
            raise ProviderError("EMBEDDING_RESPONSE_INVALID") from exc
        if response.model != self.model.name:
            raise ProviderError("EMBEDDING_MODEL_MISMATCH")
        if sorted(item.index for item in response.data) != list(range(len(texts))):
            raise ProviderError("EMBEDDING_COUNT_MISMATCH")
        result = EmbeddingBatch(
            tuple(tuple(item.embedding) for item in sorted(response.data, key=lambda x: x.index)),
            self.model,
            Usage(input_tokens=response.usage.prompt_tokens),
        )
        validate_batch(result, self.model, len(texts))
        return result
