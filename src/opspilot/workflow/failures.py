from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowFailureDefinition:
    status_code: int
    public_message: str


WORKFLOW_FAILURES: dict[str, WorkflowFailureDefinition] = {
    "approval_expired": WorkflowFailureDefinition(409, "The approval has expired."),
    "approval_actor_required": WorkflowFailureDefinition(
        422, "Approval must be supplied by a human actor."
    ),
    "approval_required": WorkflowFailureDefinition(409, "Human approval is required."),
    "audit_integrity_failed": WorkflowFailureDefinition(
        503, "The workflow audit chain could not be verified."
    ),
    "execution_adapter_failed": WorkflowFailureDefinition(
        503, "The remediation executor failed safely."
    ),
    "execution_in_progress": WorkflowFailureDefinition(
        409, "The remediation execution is already in progress."
    ),
    "execution_lease_lost": WorkflowFailureDefinition(
        409, "The remediation execution lease is no longer owned by this worker."
    ),
    "idempotency_key_conflict": WorkflowFailureDefinition(
        409, "A different idempotency key already owns this remediation."
    ),
    "invalid_remediation_evidence": WorkflowFailureDefinition(
        422, "The remediation must cite evidence collected by this investigation."
    ),
    "plan_digest_mismatch": WorkflowFailureDefinition(
        409, "The remediation plan no longer matches the reviewed plan."
    ),
    "proposal_already_decided": WorkflowFailureDefinition(
        409, "The remediation proposal already has a decision."
    ),
    "proposal_not_found": WorkflowFailureDefinition(404, "The remediation proposal was not found."),
    "remediation_scope_violation": WorkflowFailureDefinition(
        422, "The remediation expanded beyond the diagnosed incident scope."
    ),
    "run_not_diagnosed": WorkflowFailureDefinition(
        409, "Only a completed, diagnosed investigation can propose remediation."
    ),
    "run_not_found": WorkflowFailureDefinition(404, "The investigation run was not found."),
    "self_approval_forbidden": WorkflowFailureDefinition(
        409, "The proposal author cannot approve the same remediation."
    ),
    "workflow_unavailable": WorkflowFailureDefinition(
        503, "The durable workflow store is unavailable."
    ),
}


class WorkflowError(RuntimeError):
    def __init__(self, code: str) -> None:
        try:
            definition = WORKFLOW_FAILURES[code]
        except KeyError as exc:
            raise ValueError(f"unregistered workflow failure code: {code}") from exc
        super().__init__(code)
        self.code = code
        self.status_code = definition.status_code
        self.public_message = definition.public_message

    def public_detail(self) -> dict[str, object]:
        return {"code": self.code, "message": self.public_message}
