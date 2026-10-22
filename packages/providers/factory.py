from packages.config import Settings

from .contracts import EmbeddingProvider, ProviderError
from .fake import FakeEmbeddingProvider
from .openai_embeddings import OpenAIEmbeddingProvider


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
