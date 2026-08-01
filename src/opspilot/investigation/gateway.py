from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from opspilot.investigation.models import (
    EvidenceItem,
    IncidentRequest,
    ModelTurn,
    ToolTrace,
)
from opspilot.tools.base import ToolSpec


class ModelGatewayError(RuntimeError):
    """Raised when the model cannot produce a valid investigation turn."""


class InvestigationModelGateway(Protocol):
    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn: ...
