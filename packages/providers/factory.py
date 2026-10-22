from packages.config import Settings

from .contracts import EmbeddingProvider, LLMProvider, ProviderError
from .demo_llm import DemoLLMProvider
from .fake import FakeEmbeddingProvider
from .openai_embeddings import OpenAIEmbeddingProvider
from .openai_llm import OpenAILLMProvider


def make_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "fake":
        if settings.environment == "production":
            raise ProviderError("EMBEDDING_FAKE_FORBIDDEN")
        return FakeEmbeddingProvider()
    return OpenAIEmbeddingProvider(
        settings.openai_api_key,
        settings.embedding_model,
        settings.embedding_revision,
        settings.embedding_dimensions,
    )


def make_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        if settings.environment == "production":
            raise ProviderError("LLM_FAKE_FORBIDDEN")
        return DemoLLMProvider()
    return OpenAILLMProvider(
        settings.openai_api_key,
        settings.llm_model,
        settings.llm_revision,
        settings.context_token_budget,
        settings.llm_max_output_tokens,
    )
