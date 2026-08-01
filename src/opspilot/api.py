from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from opspilot.bootstrap import build_retriever
from opspilot.config import Settings
from opspilot.retrieval.base import (
    ClosableRetriever,
    EvidenceRetriever,
    RetrievalUnavailableError,
)

_FILTER_KEY = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict)

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, filters: dict[str, str]) -> dict[str, str]:
        if len(filters) > 10:
            raise ValueError("no more than 10 metadata filters are allowed")
        for key, value in filters.items():
            if not _FILTER_KEY.fullmatch(key):
                raise ValueError(f"invalid metadata filter key: {key!r}")
            if not value or len(value) > 128:
                raise ValueError("metadata filter values must contain 1 to 128 characters")
        return filters


class EvidenceResponse(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    source: str
    content: str
    metadata: dict[str, str]
    score: float
    lexical_rank: int | None
    vector_rank: int | None


class RetrievalResponse(BaseModel):
    query: str
    evidence: list[EvidenceResponse]


@lru_cache(maxsize=1)
def get_retriever() -> EvidenceRetriever:
    return build_retriever(Settings.from_environment())


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    if get_retriever.cache_info().currsize:
        retriever = get_retriever()
        if isinstance(retriever, ClosableRetriever):
            retriever.close()
        get_retriever.cache_clear()


def create_app() -> FastAPI:
    app = FastAPI(title="OpsPilot Retrieval API", version="0.2.0", lifespan=_lifespan)

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
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (RetrievalUnavailableError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        evidence = [
            EvidenceResponse(
                chunk_id=hit.chunk.chunk_id,
                document_id=hit.chunk.document_id,
                title=hit.chunk.title,
                source=hit.chunk.source,
                content=hit.chunk.content,
                metadata=dict(hit.chunk.metadata),
                score=hit.score,
                lexical_rank=hit.lexical_rank,
                vector_rank=hit.vector_rank,
            )
            for hit in hits
        ]
        return RetrievalResponse(query=request.query, evidence=evidence)

    return app
