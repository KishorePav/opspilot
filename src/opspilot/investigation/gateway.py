from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from opspilot.investigation.models import (
    EvidenceItem,
    IncidentRequest,
    ModelTurn,
    ToolTrace,
)
from opspilot.tools.base import ToolSpec

_SAFE_PROVIDER_VALUE = re.compile(r"^[a-zA-Z0-9_.:/-]{1,160}$")


@dataclass(frozen=True, slots=True)
class ProviderDiagnostic:
    """Sanitized provider metadata suitable for an evaluation artifact."""

    provider: str
    error_type: str
    error_code: str | None = None
    http_status: int | None = None
    request_id: str | None = None


def _safe_provider_value(value: object) -> str | None:
    if not isinstance(value, str) or not _SAFE_PROVIDER_VALUE.fullmatch(value):
        return None
    return value


def provider_diagnostic(provider: str, exc: Exception) -> ProviderDiagnostic:
    """Extract bounded metadata without retaining provider exception messages."""

    status_candidate = getattr(exc, "status_code", None)
    code_candidate = getattr(exc, "code", None)
    if not isinstance(status_candidate, int) and isinstance(code_candidate, int):
        status_candidate = code_candidate
    http_status = (
        status_candidate
        if isinstance(status_candidate, int) and 100 <= status_candidate <= 599
        else None
    )

    error_code = _safe_provider_value(code_candidate)
    if error_code is None:
        error_code = _safe_provider_value(getattr(exc, "status", None))

    request_id = _safe_provider_value(getattr(exc, "request_id", None))
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if request_id is None and isinstance(headers, Mapping):
        for header in ("x-request-id", "x-goog-request-id"):
            request_id = _safe_provider_value(headers.get(header))
            if request_id is not None:
                break

    return ProviderDiagnostic(
        provider=provider,
        error_type=type(exc).__name__[:160],
        error_code=error_code,
        http_status=http_status,
        request_id=request_id,
    )


class ModelGatewayError(RuntimeError):
    """Raised when the model cannot produce a valid investigation turn."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic: ProviderDiagnostic | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


class InvestigationModelGateway(Protocol):
    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn: ...
