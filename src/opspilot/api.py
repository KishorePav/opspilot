from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from opspilot.config import Settings
from opspilot.domain.models import Document
from opspilot.retrieval.embedding import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from opspilot.retrieval.service import HybridRetriever


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict)


class EvidenceResponse(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    source: str
    content: str
    score: float
    lexical_rank: int | None
    vector_rank: int | None


class RetrievalResponse(BaseModel):
    query: str
    evidence: list[EvidenceResponse]


def _load_documents(corpus_dir: Path) -> list[Document]:
    documents = []
    for path in sorted(corpus_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        title = content.splitlines()[0].lstrip("# ").strip() or path.stem
        documents.append(
            Document(
                document_id=path.stem,
                title=title,
                content=content,
                source=str(path),
                metadata={"environment": "synthetic"},
            )
        )
    return documents


@lru_cache(maxsize=1)
def get_retriever() -> HybridRetriever:
    settings = Settings.from_environment()
    embedder: EmbeddingProvider
    if settings.embedding_provider == "openai":
        embedder = OpenAIEmbeddingProvider(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
    elif settings.embedding_provider == "hash":
        embedder = HashEmbeddingProvider()
    else:
        raise RuntimeError(f"unsupported embedding provider: {settings.embedding_provider}")

    retriever = HybridRetriever(embedder)
    documents = _load_documents(settings.corpus_dir)
    if not documents:
        raise RuntimeError(f"no Markdown documents found in {settings.corpus_dir}")
    retriever.index_documents(documents)
    return retriever


def create_app() -> FastAPI:
    app = FastAPI(title="OpsPilot Retrieval API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/retrieve", response_model=RetrievalResponse)
    def retrieve(request: RetrievalRequest) -> RetrievalResponse:
        try:
            hits = get_retriever().search(
                request.query,
                top_k=request.top_k,
                filters=request.filters,
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        evidence = [
            EvidenceResponse(
                chunk_id=hit.chunk.chunk_id,
                document_id=hit.chunk.document_id,
                title=hit.chunk.title,
                source=hit.chunk.source,
                content=hit.chunk.content,
                score=hit.score,
                lexical_rank=hit.lexical_rank,
                vector_rank=hit.vector_rank,
            )
            for hit in hits
        ]
        return RetrievalResponse(query=request.query, evidence=evidence)

    return app
