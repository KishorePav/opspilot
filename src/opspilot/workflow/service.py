from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from opspilot.investigation.failures import InvestigationFailedError
from opspilot.investigation.models import IncidentRequest
from opspilot.investigation.orchestrator import IncidentInvestigator
from opspilot.workflow.base import RemediationExecutor, WorkflowStore
from opspilot.workflow.failures import WorkflowError
from opspilot.workflow.models import (
    Actor,
    ApprovalDecision,
    AuditEvent,
    InvestigationFailureSnapshot,
    InvestigationRun,
    RemediationAction,
    RemediationExecution,
    RemediationProposal,
    remediation_plan_digest,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class RemediationWorkflowService:
    def __init__(
        self,
        investigator: IncidentInvestigator,
        store: WorkflowStore,
        executor: RemediationExecutor,
        *,
        approval_ttl: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if approval_ttl <= timedelta(0) or approval_ttl > timedelta(hours=1):
            raise ValueError("approval TTL must be between 1 second and 1 hour")
        self._investigator = investigator
        self._store = store
        self._executor = executor
        self._approval_ttl = approval_ttl
        self._clock = clock

    def close(self) -> None:
        self._store.close()

    def create_investigation(
        self,
        request: IncidentRequest,
        *,
        created_by: Actor,
    ) -> InvestigationRun:
        now = self._clock()
        run_id = f"run_{uuid4().hex}"
        try:
            result = self._investigator.investigate(request)
            run = InvestigationRun(
                run_id=run_id,
                request=request,
                status="completed",
                result=result,
                failure=None,
                created_by=created_by,
                created_at=now,
                updated_at=now,
                version=1,
            )
        except InvestigationFailedError as exc:
            assert exc.usage is not None
            run = InvestigationRun(
                run_id=run_id,
                request=request,
                status="failed",
                result=None,
                failure=InvestigationFailureSnapshot(
                    code=exc.code,
                    category=exc.category,
                    retryable=exc.retryable,
                    message=exc.public_message,
                    trace=list(exc.trace),
                    evidence=list(exc.evidence),
                    usage=exc.usage,
                ),
                created_by=created_by,
                created_at=now,
                updated_at=now,
                version=1,
            )
        return self._store.create_run(run)

    def get_investigation(self, run_id: str) -> InvestigationRun:
        return self._store.get_run(run_id)

    def create_proposal(
        self,
        run_id: str,
        action: RemediationAction,
        *,
        created_by: Actor,
    ) -> RemediationProposal:
        run = self._store.get_run(run_id)
        if (
            run.status != "completed"
            or run.result is None
            or run.result.report.status != "diagnosed"
        ):
            raise WorkflowError("run_not_diagnosed")
        if (
            action.environment != run.request.environment
            or action.service not in run.request.services
        ):
            raise WorkflowError("remediation_scope_violation")
        evidence_ids = {item.evidence_id for item in run.result.evidence}
        if not set(action.evidence_ids) <= evidence_ids:
            raise WorkflowError("invalid_remediation_evidence")

        now = self._clock()
        proposal = RemediationProposal(
            proposal_id=f"prop_{uuid4().hex}",
            run_id=run_id,
            plan_digest=remediation_plan_digest(run_id, action),
            action=action,
            dry_run=self._executor.dry_run(action),
            status="awaiting_approval",
            created_by=created_by,
            approval=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        return self._store.create_proposal(proposal)

    def get_proposal(self, proposal_id: str) -> RemediationProposal:
        return self._store.get_proposal(proposal_id)

    def decide_proposal(
        self,
        proposal_id: str,
        *,
        decision: Literal["approve", "reject"],
        expected_plan_digest: str,
        decided_by: Actor,
        reason: str,
    ) -> RemediationProposal:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if decided_by.actor_type != "human":
            raise WorkflowError("approval_actor_required")
        now = self._clock()
        approval = ApprovalDecision(
            decision=decision,
            decided_by=decided_by,
            reason=reason,
            expected_plan_digest=expected_plan_digest,
            decided_at=now,
            expires_at=now + self._approval_ttl if decision == "approve" else None,
        )
        return self._store.decide_proposal(proposal_id, approval, now=now)

    def execute_proposal(
        self,
        proposal_id: str,
        *,
        idempotency_key: str,
        requested_by: Actor,
    ) -> RemediationExecution:
        proposal = self._store.get_proposal(proposal_id)
        if not self._store.verify_audit_chain(proposal.run_id):
            raise WorkflowError("audit_integrity_failed")
        now = self._clock()
        claim = self._store.claim_execution(
            proposal_id,
            idempotency_key=idempotency_key,
            requested_by=requested_by,
            now=now,
        )
        if not claim.claimed:
            if claim.execution.status == "executing":
                raise WorkflowError("execution_in_progress")
            return claim.execution

        try:
            outcome = self._executor.execute(
                proposal.action,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            self._store.fail_execution(
                claim.execution.execution_id,
                "execution_adapter_failed",
                now=self._clock(),
            )
            raise WorkflowError("execution_adapter_failed") from exc
        return self._store.complete_execution(
            claim.execution.execution_id,
            outcome,
            now=self._clock(),
        )

    def audit_events(self, run_id: str) -> list[AuditEvent]:
        events = self._store.list_audit_events(run_id)
        if not self._store.verify_audit_chain(run_id):
            raise WorkflowError("audit_integrity_failed")
        return events
