from __future__ import annotations

import hashlib
from threading import RLock

from opspilot.workflow.failures import WorkflowError
from opspilot.workflow.models import (
    DryRunResult,
    RemediationAction,
    RemediationOutcome,
    remediation_plan_digest,
)


class SyntheticRemediationExecutor:
    """A bounded demonstration adapter with no external or production side effects."""

    def __init__(self) -> None:
        self._outcomes: dict[str, tuple[str, RemediationOutcome]] = {}
        self._lock = RLock()
        self.execution_count = 0

    def dry_run(self, action: RemediationAction) -> DryRunResult:
        if action.environment != "synthetic":
            raise WorkflowError("remediation_scope_violation")
        return DryRunResult(
            action_type=action.action_type,
            predicted_effect=(
                f"Would request a rolling restart of {action.deployment} "
                f"for service {action.service} in synthetic."
            ),
            preconditions=[
                "The approved plan digest must still match.",
                "The human approval must be unexpired.",
                "The idempotency key must not belong to another plan.",
            ],
        )

    def execute(
        self,
        action: RemediationAction,
        *,
        idempotency_key: str,
    ) -> RemediationOutcome:
        if action.environment != "synthetic":
            raise WorkflowError("remediation_scope_violation")
        action_digest = remediation_plan_digest("run_" + "0" * 32, action)
        with self._lock:
            existing = self._outcomes.get(idempotency_key)
            if existing is not None:
                if existing[0] != action_digest:
                    raise WorkflowError("idempotency_key_conflict")
                return existing[1]
            reference = hashlib.sha256(
                f"{idempotency_key}:{action_digest}".encode()
            ).hexdigest()[:20]
            outcome = RemediationOutcome(
                provider_reference=f"synthetic-restart-{reference}",
                summary=(
                    f"Recorded one simulated rolling restart for {action.deployment}; "
                    "no external system was changed."
                ),
                simulated=True,
            )
            self._outcomes[idempotency_key] = (action_digest, outcome)
            self.execution_count += 1
            return outcome
