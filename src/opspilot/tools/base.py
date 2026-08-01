from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from opspilot.investigation.models import EvidenceItem


class ToolExecutionError(RuntimeError):
    """A sanitized, expected failure at the tool boundary."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, object]


class ReadOnlyTool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    def execute(self, arguments: Mapping[str, object]) -> list[EvidenceItem]: ...
