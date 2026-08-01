from __future__ import annotations

from datetime import datetime
from threading import RLock
from uuid import uuid4

from opspilot.workflow.base import ExecutionClaim
from opspilot.workflow.failures import WorkflowError
from opspilot.workflow.models import (
    Actor,
    ApprovalDecision,
    AuditEvent,
    InvestigationRun,
    RemediationExecution,
    RemediationOutcome,
    RemediationProposal,
    audit_event_digest,
    verify_audit_events,
)


class InMemoryWorkflowStore:
    """Deterministic workflow adapter for unit tests; it is not durable storage."""

    def __init__(self) -> None:
        self._runs: dict[str, InvestigationRun] = {}
        self._proposals: dict[str, RemediationProposal] = {}
        self._executions: dict[str, RemediationExecution] = {}
        self._execution_by_proposal: dict[str, str] = {}
        self._events: dict[str, list[AuditEvent]] = {}
        self._lock = RLock()

    def create_run(self, run: InvestigationRun) -> InvestigationRun:
        with self._lock:
            if run.run_id in self._runs:
                raise ValueError(f"duplicate run ID: {run.run_id}")
            self._runs[run.run_id] = run
            self._append_event(
                run.run_id,
                "investigation.created",
                run.created_by,
                {"incident_id": run.request.incident_id, "status": run.status},
                run.created_at,
            )
            return run

    def get_run(self, run_id: str) -> InvestigationRun:
        with self._lock:
            try:
                return self._runs[run_id]
            except KeyError as exc:
                raise WorkflowError("run_not_found") from exc

    def create_proposal(self, proposal: RemediationProposal) -> RemediationProposal:
        with self._lock:
            self.get_run(proposal.run_id)
            if proposal.proposal_id in self._proposals:
                raise ValueError(f"duplicate proposal ID: {proposal.proposal_id}")
            self._proposals[proposal.proposal_id] = proposal
            self._append_event(
                proposal.run_id,
                "remediation.proposed",
                proposal.created_by,
                {
                    "proposal_id": proposal.proposal_id,
                    "plan_digest": proposal.plan_digest,
                    "action_type": proposal.action.action_type,
                    "side_effects_performed": proposal.dry_run.side_effects_performed,
                },
                proposal.created_at,
            )
            return proposal

    def get_proposal(self, proposal_id: str) -> RemediationProposal:
        with self._lock:
            try:
                return self._proposals[proposal_id]
            except KeyError as exc:
                raise WorkflowError("proposal_not_found") from exc

    def decide_proposal(
        self,
        proposal_id: str,
        decision: ApprovalDecision,
        *,
        now: datetime,
    ) -> RemediationProposal:
        with self._lock:
            proposal = self.get_proposal(proposal_id)
            if proposal.status != "awaiting_approval" or proposal.approval is not None:
                raise WorkflowError("proposal_already_decided")
            if decision.expected_plan_digest != proposal.plan_digest:
                raise WorkflowError("plan_digest_mismatch")
            if decision.decided_by.actor_id == proposal.created_by.actor_id:
                raise WorkflowError("self_approval_forbidden")

            status = "approved" if decision.decision == "approve" else "rejected"
            updated = proposal.model_copy(
                update={
                    "status": status,
                    "approval": decision,
                    "updated_at": now,
                    "version": proposal.version + 1,
                }
            )
            self._proposals[proposal_id] = updated
            event_type = (
                "remediation.approved"
                if decision.decision == "approve"
                else "remediation.rejected"
            )
            self._append_event(
                proposal.run_id,
                event_type,
                decision.decided_by,
                {
                    "proposal_id": proposal.proposal_id,
                    "plan_digest": proposal.plan_digest,
                    "reason": decision.reason,
                    "expires_at": (
                        decision.expires_at.isoformat()
                        if decision.expires_at is not None
                        else None
                    ),
                },
                now,
            )
            return updated

    def claim_execution(
        self,
        proposal_id: str,
        *,
        idempotency_key: str,
        requested_by: Actor,
        now: datetime,
    ) -> ExecutionClaim:
        with self._lock:
            proposal = self.get_proposal(proposal_id)
            existing_id = self._execution_by_proposal.get(proposal_id)
            if existing_id is not None:
                existing = self._executions[existing_id]
                if existing.idempotency_key != idempotency_key:
                    raise WorkflowError("idempotency_key_conflict")
                return ExecutionClaim(existing, claimed=False)

            approval = proposal.approval
            if proposal.status != "approved" or approval is None:
                raise WorkflowError("approval_required")
            if approval.expected_plan_digest != proposal.plan_digest:
                raise WorkflowError("plan_digest_mismatch")
            if approval.expires_at is None or approval.expires_at <= now:
                raise WorkflowError("approval_expired")

            execution = RemediationExecution(
                execution_id=f"exec_{uuid4().hex}",
                proposal_id=proposal.proposal_id,
                run_id=proposal.run_id,
                idempotency_key=idempotency_key,
                plan_digest=proposal.plan_digest,
                requested_by=requested_by,
                status="executing",
                outcome=None,
                error_code=None,
                created_at=now,
                completed_at=None,
            )
            self._executions[execution.execution_id] = execution
            self._execution_by_proposal[proposal_id] = execution.execution_id
            self._proposals[proposal_id] = proposal.model_copy(
                update={
                    "status": "executing",
                    "updated_at": now,
                    "version": proposal.version + 1,
                }
            )
            self._append_event(
                proposal.run_id,
                "remediation.execution_claimed",
                requested_by,
                {
                    "proposal_id": proposal.proposal_id,
                    "execution_id": execution.execution_id,
                    "idempotency_key": idempotency_key,
                    "plan_digest": proposal.plan_digest,
                },
                now,
            )
            return ExecutionClaim(execution, claimed=True)

    def complete_execution(
        self,
        execution_id: str,
        outcome: RemediationOutcome,
        *,
        now: datetime,
    ) -> RemediationExecution:
        with self._lock:
            execution = self._executions[execution_id]
            if execution.status == "completed":
                return execution
            if execution.status != "executing":
                raise WorkflowError("execution_adapter_failed")
            completed = execution.model_copy(
                update={"status": "completed", "outcome": outcome, "completed_at": now}
            )
            self._executions[execution_id] = completed
            proposal = self.get_proposal(execution.proposal_id)
            self._proposals[proposal.proposal_id] = proposal.model_copy(
                update={
                    "status": "completed",
                    "updated_at": now,
                    "version": proposal.version + 1,
                }
            )
            self._append_event(
                execution.run_id,
                "remediation.executed",
                execution.requested_by,
                {
                    "proposal_id": execution.proposal_id,
                    "execution_id": execution.execution_id,
                    "provider_reference": outcome.provider_reference,
                    "simulated": outcome.simulated,
                },
                now,
            )
            return completed

    def fail_execution(
        self,
        execution_id: str,
        error_code: str,
        *,
        now: datetime,
    ) -> RemediationExecution:
        with self._lock:
            execution = self._executions[execution_id]
            if execution.status != "executing":
                return execution
            failed = execution.model_copy(
                update={"status": "failed", "error_code": error_code, "completed_at": now}
            )
            self._executions[execution_id] = failed
            proposal = self.get_proposal(execution.proposal_id)
            self._proposals[proposal.proposal_id] = proposal.model_copy(
                update={
                    "status": "failed",
                    "updated_at": now,
                    "version": proposal.version + 1,
                }
            )
            self._append_event(
                execution.run_id,
                "remediation.execution_failed",
                execution.requested_by,
                {
                    "proposal_id": execution.proposal_id,
                    "execution_id": execution.execution_id,
                    "error_code": error_code,
                },
                now,
            )
            return failed

    def list_audit_events(self, run_id: str) -> list[AuditEvent]:
        with self._lock:
            self.get_run(run_id)
            return list(self._events.get(run_id, []))

    def verify_audit_chain(self, run_id: str) -> bool:
        return verify_audit_events(self.list_audit_events(run_id))

    def close(self) -> None:
        return None

    def _append_event(
        self,
        run_id: str,
        event_type: str,
        actor: Actor,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> None:
        events = self._events.setdefault(run_id, [])
        if events and not verify_audit_events(events):
            raise WorkflowError("audit_integrity_failed")
        previous_hash = events[-1].event_hash if events else None
        sequence_no = len(events) + 1
        event = AuditEvent(
            event_id=f"audit_{uuid4().hex}",
            run_id=run_id,
            sequence_no=sequence_no,
            event_type=event_type,
            actor=actor,
            payload=payload,
            previous_hash=previous_hash,
            event_hash=audit_event_digest(
                run_id=run_id,
                sequence_no=sequence_no,
                event_type=event_type,
                actor=actor,
                payload=payload,
                previous_hash=previous_hash,
                occurred_at=occurred_at,
            ),
            occurred_at=occurred_at,
        )
        events.append(event)
