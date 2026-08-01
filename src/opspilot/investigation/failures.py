from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from opspilot.investigation.models import EvidenceItem, ToolTrace, UsageSummary

FailureCategory = Literal[
    "budget",
    "contract",
    "data_integrity",
    "dependency",
    "provider",
    "safety_policy",
]


@dataclass(frozen=True, slots=True)
class FailureDefinition:
    category: FailureCategory
    retryable: bool
    public_message: str


FAILURE_TAXONOMY: dict[str, FailureDefinition] = {
    "diagnosis_has_no_citations": FailureDefinition(
        "safety_policy", False, "The diagnosis did not cite collected evidence."
    ),
    "duplicate_tool_call": FailureDefinition(
        "safety_policy", False, "The investigation repeated an identical tool call."
    ),
    "evidence_budget_exhausted": FailureDefinition(
        "budget", False, "The investigation exceeded its evidence budget."
    ),
    "evidence_id_collision": FailureDefinition(
        "data_integrity", False, "Conflicting evidence identifiers were returned."
    ),
    "investigation_round_budget_exhausted": FailureDefinition(
        "budget", False, "The investigation exceeded its round budget."
    ),
    "model_gateway_failed": FailureDefinition(
        "provider", True, "The model provider could not complete the investigation."
    ),
    "non_json_tool_arguments": FailureDefinition(
        "contract", False, "The model returned invalid tool arguments."
    ),
    "pricing_policy_mismatch": FailureDefinition(
        "contract", False, "Usage could not be matched to the configured price policy."
    ),
    "report_contains_unknown_citation": FailureDefinition(
        "safety_policy", False, "The report cited evidence that was not collected."
    ),
    "report_incident_mismatch": FailureDefinition(
        "contract", False, "The report did not match the requested incident."
    ),
    "report_service_scope_violation": FailureDefinition(
        "safety_policy", False, "The report expanded beyond the incident service scope."
    ),
    "tool_call_budget_exhausted": FailureDefinition(
        "budget", False, "The investigation exceeded its tool-call budget."
    ),
    "token_budget_exhausted": FailureDefinition(
        "budget", False, "The investigation exceeded its model-token budget."
    ),
    "unknown_tool": FailureDefinition(
        "safety_policy", False, "The model requested an unregistered tool."
    ),
    "scope_violation": FailureDefinition(
        "safety_policy", False, "A tool request exceeded the incident scope."
    ),
    "invalid_arguments": FailureDefinition(
        "contract", False, "A tool request contained invalid arguments."
    ),
    "retrieval_unavailable": FailureDefinition(
        "dependency", True, "A required evidence source was unavailable."
    ),
}


def failure_definition(code: str) -> FailureDefinition:
    try:
        return FAILURE_TAXONOMY[code]
    except KeyError as exc:
        raise ValueError(f"unregistered investigation failure code: {code}") from exc


class InvestigationFailedError(RuntimeError):
    """A typed fail-closed result with optional partial evaluation context."""

    def __init__(self, code: str) -> None:
        definition = failure_definition(code)
        super().__init__(code)
        self.code = code
        self.category = definition.category
        self.retryable = definition.retryable
        self.public_message = definition.public_message
        self.trace: tuple[ToolTrace, ...] = ()
        self.evidence: tuple[EvidenceItem, ...] = ()
        self.usage: UsageSummary | None = None

    def attach_context(
        self,
        *,
        trace: list[ToolTrace],
        evidence: list[EvidenceItem],
        usage: UsageSummary,
    ) -> None:
        self.trace = tuple(trace)
        self.evidence = tuple(evidence)
        self.usage = usage

    def public_detail(self) -> dict[str, object]:
        return {
            "code": self.code,
            "category": self.category,
            "retryable": self.retryable,
            "message": self.public_message,
        }
