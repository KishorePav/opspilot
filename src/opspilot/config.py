from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    retrieval_backend: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    corpus_dir: Path
    database_url: str
    database_pool_min_size: int
    database_pool_max_size: int

    def __post_init__(self) -> None:
        if self.retrieval_backend not in {"memory", "postgres"}:
            raise ValueError("retrieval backend must be 'memory' or 'postgres'")
        if self.embedding_dimensions < 32:
            raise ValueError("embedding dimensions must be at least 32")
        if self.database_pool_min_size < 1:
            raise ValueError("database pool minimum size must be positive")
        if self.database_pool_max_size < self.database_pool_min_size:
            raise ValueError("database pool maximum must be at least its minimum")

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            environment=os.getenv("OPSPILOT_ENVIRONMENT", "local"),
            retrieval_backend=os.getenv("OPSPILOT_RETRIEVAL_BACKEND", "memory"),
            embedding_provider=os.getenv("OPSPILOT_EMBEDDING_PROVIDER", "hash"),
            embedding_model=os.getenv(
                "OPSPILOT_EMBEDDING_MODEL", "text-embedding-3-small"
            ),
            embedding_dimensions=int(os.getenv("OPSPILOT_EMBEDDING_DIMENSIONS", "1536")),
            corpus_dir=Path(os.getenv("OPSPILOT_CORPUS_DIR", "fixtures/runbooks")),
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql://opspilot:opspilot@localhost:5432/opspilot",
            ),
            database_pool_min_size=int(os.getenv("OPSPILOT_DATABASE_POOL_MIN_SIZE", "1")),
            database_pool_max_size=int(os.getenv("OPSPILOT_DATABASE_POOL_MAX_SIZE", "8")),
        )
