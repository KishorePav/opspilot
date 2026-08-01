from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from opspilot.domain.models import SearchHit


class RetrievalUnavailableError(RuntimeError):
    """Raised when the configured retrieval infrastructure cannot serve requests."""


class EvidenceRetriever(Protocol):
    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: Mapping[str, str] | None = None,
    ) -> list[SearchHit]: ...


@runtime_checkable
class ClosableRetriever(Protocol):
    def close(self) -> None: ...
