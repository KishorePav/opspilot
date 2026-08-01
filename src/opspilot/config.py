from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    corpus_dir: Path

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            environment=os.getenv("OPSPILOT_ENVIRONMENT", "local"),
            embedding_provider=os.getenv("OPSPILOT_EMBEDDING_PROVIDER", "hash"),
            embedding_model=os.getenv(
                "OPSPILOT_EMBEDDING_MODEL", "text-embedding-3-small"
            ),
            embedding_dimensions=int(os.getenv("OPSPILOT_EMBEDDING_DIMENSIONS", "1536")),
            corpus_dir=Path(os.getenv("OPSPILOT_CORPUS_DIR", "fixtures/runbooks")),
        )
