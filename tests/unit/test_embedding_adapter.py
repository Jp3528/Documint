import json
from dataclasses import replace
from decimal import Decimal
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest
from pydantic import SecretStr

from packages.config import Settings
from packages.providers.contracts import EmbeddingBatch, ModelInfo, ProviderError, Usage
from packages.providers.factory import make_embedding_provider
from packages.providers.openai_embeddings import OpenAIEmbeddingProvider
from packages.providers.validation import validate_batch


def adapter() -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(
        SecretStr("synthetic-test-key"), "text-embedding-3-small", "test", 2
    )


def payload() -> dict[str, object]:
    return {
        "model": "text-embedding-3-small",
        "data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}],
        "usage": {"prompt_tokens": 7, "total_tokens": 7},
    }


def test_real_adapter_wire_contract_order_usage_and_no_invented_cost() -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload()).encode()
    with patch(
        "packages.providers.openai_embeddings._opener.open", return_value=response
    ) as request:
        result = adapter().embed(["first", "second"])
    sent = request.call_args.args[0]
    assert sent.full_url == "https://api.openai.com/v1/embeddings"
    assert json.loads(sent.data) == {
        "input": ["first", "second"],
        "model": "text-embedding-3-small",
        "dimensions": 2,
        "encoding_format": "float",
    }
    assert request.call_args.kwargs["timeout"] == 30
    assert result.vectors == ((1.0, 0.0), (0.0, 1.0))
    assert result.model.mode == "REAL" and result.usage.input_tokens == 7
    assert result.usage.observed_cost_usd is None  # HTTP stub, no real API evaluation.


@pytest.mark.parametrize(
    "body,code",
    [
        ({"model": "other"}, "EMBEDDING_MODEL_MISMATCH"),
        ({"data": [{"index": 0, "embedding": [1.0, 0.0]}] * 2}, "EMBEDDING_COUNT_MISMATCH"),
        ({"data": [{"index": 0, "embedding": [1.0]}]}, "EMBEDDING_COUNT_MISMATCH"),
        (
            {"data": [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": [1.0]}]},
            "EMBEDDING_DIMENSION_MISMATCH",
        ),
        ({"usage": {"prompt_tokens": -1, "total_tokens": 7}}, "EMBEDDING_RESPONSE_INVALID"),
        ({"data": [{"index": 0, "embedding": [float("nan"), 1.0]}]}, "EMBEDDING_RESPONSE_INVALID"),
    ],
)
def test_real_adapter_rejects_invalid_responses(body: dict[str, object], code: str) -> None:
    with (
        patch.object(OpenAIEmbeddingProvider, "_request", return_value=payload() | body),
        pytest.raises(ProviderError, match=code),
    ):
        adapter().embed(["first", "second"])


@pytest.mark.parametrize("texts", [[], [""], [" "], ["x"] * 33, ["文" * 3000]])
def test_input_limits_precede_external_requests(texts: list[str]) -> None:
    with patch.object(OpenAIEmbeddingProvider, "_request") as request:
        with pytest.raises(ProviderError, match="EMBEDDING_INPUT_LIMIT"):
            adapter().embed(texts)
        request.assert_not_called()


def test_request_errors_are_sanitized_and_not_retried() -> None:
    with patch(
        "packages.providers.openai_embeddings._opener.open", side_effect=URLError("private")
    ) as req:
        with pytest.raises(ProviderError, match=r"^EMBEDDING_REQUEST_FAILED$"):
            adapter().embed(["test"])
        assert req.call_count == 1


def test_provider_selection_never_silently_falls_back_to_fake() -> None:
    with pytest.raises(ProviderError, match="EMBEDDING_KEY_MISSING"):
        make_embedding_provider(Settings(embedding_provider="openai", openai_api_key=None))
    with pytest.raises(ProviderError, match="EMBEDDING_FAKE_FORBIDDEN"):
        make_embedding_provider(Settings(environment="production", embedding_provider="fake"))
    assert make_embedding_provider(Settings(embedding_provider="fake")).model.mode == "FAKE"


@pytest.mark.parametrize("vector", [(0.0, 0.0), (float("inf"), 1.0), (1e40, 1.0), (1e-45, 0.0)])
def test_vectors_must_be_usable_float32_values(vector: tuple[float, ...]) -> None:
    model = ModelInfo("test", "1", "FAKE", 2)
    with pytest.raises(ProviderError, match="EMBEDDING_INVALID_VECTOR"):
        validate_batch(EmbeddingBatch((vector,), model, Usage()), model, 1)
    with pytest.raises(ProviderError, match="EMBEDDING_MODEL_MISMATCH"):
        validate_batch(
            EmbeddingBatch(((1.0, 0.0),), replace(model, revision="2"), Usage()), model, 1
        )
    with pytest.raises(ProviderError, match="EMBEDDING_INVALID_USAGE"):
        validate_batch(
            EmbeddingBatch(((1.0, 0.0),), model, Usage(observed_cost_usd=Decimal("-1"))), model, 1
        )
