import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from packages.config import Settings
from packages.providers.contracts import Evidence, LLMRequest, ProviderError
from packages.providers.factory import make_llm_provider
from packages.providers.openai_llm import OpenAILLMProvider
from packages.rag.prompts import SYSTEM_PROMPT


def provider() -> OpenAILLMProvider:
    return OpenAILLMProvider(SecretStr("synthetic-test-key"), "configured-model", "test")


def payload() -> dict[str, object]:
    return {
        "status": "completed",
        "model": "configured-model",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "text": "Evidence sentence.",
                                "claims": [
                                    {"text": "Evidence sentence.", "source_ids": ["source-1"]}
                                ],
                            }
                        ),
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 40, "output_tokens": 12, "total_tokens": 52},
    }


def test_real_llm_wire_contract_is_stateless_structured_and_records_observed_tokens() -> None:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload()).encode()
    request = LLMRequest(SYSTEM_PROMPT, "Question", (Evidence("source-1", "Evidence sentence."),))
    with patch("packages.providers.openai_http._opener.open", return_value=response) as network:
        result = provider().generate(request)
    sent = network.call_args.args[0]
    body = json.loads(sent.data)
    assert sent.full_url == "https://api.openai.com/v1/responses"
    assert body["store"] is False and body["max_output_tokens"] == 1024
    assert body["text"]["format"]["strict"] is True
    assert body["input"][0]["role"] == "system" and body["input"][1]["role"] == "user"
    assert "tools" not in body and "previous_response_id" not in body
    assert network.call_args.kwargs["timeout"] == 45 and network.call_count == 1
    assert result.model.mode == "REAL" and result.usage.input_tokens == 40
    assert result.usage.output_tokens == 12 and result.usage.observed_cost_usd is None
    assert result.claims[0].source_ids == ("source-1",)  # Proposals, not validated citations.


@pytest.mark.parametrize(
    "change,code",
    [
        ({"model": "other-model"}, "LLM_MODEL_MISMATCH"),
        ({"status": "incomplete"}, "LLM_INCOMPLETE"),
        ({"output": [{"type": "function_call"}]}, "LLM_UNEXPECTED_OUTPUT"),
        ({"output": []}, "LLM_RESPONSE_INVALID"),
        (
            {"usage": {"input_tokens": -1, "output_tokens": 0, "total_tokens": 0}},
            "LLM_RESPONSE_INVALID",
        ),
        (
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal"}],
                    }
                ]
            },
            "LLM_REFUSED",
        ),
        (
            {
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "not-json"}],
                    }
                ]
            },
            "LLM_RESPONSE_INVALID",
        ),
    ],
)
def test_real_llm_rejects_unusable_output_without_fallback(
    change: dict[str, object], code: str
) -> None:
    with (
        patch.object(OpenAILLMProvider, "_request", return_value=payload() | change),
        pytest.raises(ProviderError, match=code),
    ):
        provider().generate(LLMRequest(SYSTEM_PROMPT, "Question"))


def test_llm_selection_and_input_limits_are_explicit() -> None:
    with pytest.raises(ProviderError, match="LLM_KEY_MISSING"):
        make_llm_provider(Settings(llm_provider="openai", openai_api_key=None))
    with pytest.raises(ProviderError, match="LLM_MODEL_MISSING"):
        make_llm_provider(
            Settings(llm_provider="openai", openai_api_key=SecretStr("test"), llm_model="")
        )
    with pytest.raises(ProviderError, match="LLM_FAKE_FORBIDDEN"):
        make_llm_provider(Settings(environment="production", llm_provider="fake"))
    with patch.object(OpenAILLMProvider, "_request") as network:
        with pytest.raises(ProviderError, match="LLM_INPUT_LIMIT"):
            provider().generate(LLMRequest(SYSTEM_PROMPT, "文" * 3000))
        network.assert_not_called()
