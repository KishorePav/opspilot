from __future__ import annotations

from opspilot.adapters.postgres import PostgresHybridRetriever
from opspilot.config import Settings
from opspilot.corpus import load_markdown_documents
from opspilot.retrieval.base import EvidenceRetriever
from opspilot.retrieval.embedding import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from opspilot.retrieval.service import HybridRetriever


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
    if settings.embedding_provider == "hash":
        return HashEmbeddingProvider(dimensions=settings.embedding_dimensions)
    raise RuntimeError(f"unsupported embedding provider: {settings.embedding_provider}")


def build_retriever(settings: Settings) -> EvidenceRetriever:
    embedder = build_embedding_provider(settings)
    if settings.retrieval_backend == "postgres":
        return PostgresHybridRetriever(
            settings.database_url,
            embedder,
            pool_min_size=settings.database_pool_min_size,
            pool_max_size=settings.database_pool_max_size,
        )

    retriever = HybridRetriever(embedder)
    documents = load_markdown_documents(settings.corpus_dir)
    if not documents:
        raise RuntimeError(f"no Markdown documents found in {settings.corpus_dir}")
    retriever.index_documents(documents)
    return retriever
