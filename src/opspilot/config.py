from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


def _optional_decimal(name: str) -> Decimal | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    return Decimal(raw)


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
    investigation_provider: str
    investigation_model: str
    operational_fixture_path: Path
    investigation_max_rounds: int
    investigation_max_tool_calls: int
    investigation_max_evidence_items: int
    approval_ttl_seconds: int
    pricing_version: str | None
    input_usd_per_million: Decimal | None
    cached_input_usd_per_million: Decimal | None
    output_usd_per_million: Decimal | None

    def __post_init__(self) -> None:
        if self.retrieval_backend not in {"memory", "postgres"}:
            raise ValueError("retrieval backend must be 'memory' or 'postgres'")
        if self.embedding_dimensions < 32:
            raise ValueError("embedding dimensions must be at least 32")
        if self.database_pool_min_size < 1:
            raise ValueError("database pool minimum size must be positive")
        if self.database_pool_max_size < self.database_pool_min_size:
            raise ValueError("database pool maximum must be at least its minimum")
        if self.investigation_provider not in {"disabled", "openai"}:
            raise ValueError("investigation provider must be 'disabled' or 'openai'")
        if not self.investigation_model.strip():
            raise ValueError("investigation model must not be empty")
        if min(
            self.investigation_max_rounds,
            self.investigation_max_tool_calls,
            self.investigation_max_evidence_items,
        ) < 1:
            raise ValueError("investigation budgets must be positive")
        if self.approval_ttl_seconds < 1 or self.approval_ttl_seconds > 3_600:
            raise ValueError("approval TTL must be between 1 and 3600 seconds")
        pricing_values = (
            self.input_usd_per_million,
            self.cached_input_usd_per_million,
            self.output_usd_per_million,
        )
        configured_rates = sum(value is not None for value in pricing_values)
        if configured_rates not in {0, len(pricing_values)}:
            raise ValueError("all model pricing rates must be configured together")
        if configured_rates and not self.pricing_version:
            raise ValueError("configured model pricing requires a pricing version")
        if any(value is not None and value < 0 for value in pricing_values):
            raise ValueError("model pricing rates cannot be negative")

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
            investigation_provider=os.getenv(
                "OPSPILOT_INVESTIGATION_PROVIDER", "disabled"
            ),
            investigation_model=os.getenv("OPSPILOT_INVESTIGATION_MODEL", "gpt-5.6"),
            operational_fixture_path=Path(
                os.getenv(
                    "OPSPILOT_OPERATIONAL_FIXTURE",
                    "fixtures/operations/dataflow-permission-denied.json",
                )
            ),
            investigation_max_rounds=int(
                os.getenv("OPSPILOT_INVESTIGATION_MAX_ROUNDS", "8")
            ),
            investigation_max_tool_calls=int(
                os.getenv("OPSPILOT_INVESTIGATION_MAX_TOOL_CALLS", "12")
            ),
            investigation_max_evidence_items=int(
                os.getenv("OPSPILOT_INVESTIGATION_MAX_EVIDENCE_ITEMS", "40")
            ),
            approval_ttl_seconds=int(os.getenv("OPSPILOT_APPROVAL_TTL_SECONDS", "900")),
            pricing_version=os.getenv("OPSPILOT_PRICING_VERSION") or None,
            input_usd_per_million=_optional_decimal(
                "OPSPILOT_INPUT_USD_PER_MILLION"
            ),
            cached_input_usd_per_million=_optional_decimal(
                "OPSPILOT_CACHED_INPUT_USD_PER_MILLION"
            ),
            output_usd_per_million=_optional_decimal(
                "OPSPILOT_OUTPUT_USD_PER_MILLION"
            ),
        )
