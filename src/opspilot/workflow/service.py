from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from opspilot.investigation.failures import InvestigationFailedError
from opspilot.investigation.models import IncidentRequest
from opspilot.investigation.orchestrator import IncidentInvestigator
from opspilot.observability import NoopObservability, Observability
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
        execution_lease_ttl: timedelta = timedelta(seconds=30),
        worker_id: str = "opspilot-worker",
        observability: Observability | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if approval_ttl <= timedelta(0) or approval_ttl > timedelta(hours=1):
            raise ValueError("approval TTL must be between 1 second and 1 hour")
        if execution_lease_ttl < timedelta(seconds=5) or execution_lease_ttl > timedelta(minutes=5):
            raise ValueError("execution lease TTL must be between 5 seconds and 5 minutes")
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker ID must contain 1 to 128 characters")
        self._investigator = investigator
        self._store = store
        self._executor = executor
        self._approval_ttl = approval_ttl
        self._execution_lease_ttl = execution_lease_ttl
        self._worker_id = worker_id
        self._observability = observability or NoopObservability()
        self._clock = clock

    def close(self) -> None:
        self._store.close()

    def create_investigation(
        self,
        request: IncidentRequest,
        *,
        created_by: Actor,
        tenant_id: str,
    ) -> InvestigationRun:
        with self._observability.operation("workflow.create_investigation"):
            now = self._clock()
            run_id = f"run_{uuid4().hex}"
            try:
                result = self._investigator.investigate(request)
                self._observability.record_model_usage(
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                )
                run = InvestigationRun(
                    run_id=run_id,
                    tenant_id=tenant_id,
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
                self._observability.record_model_usage(
                    input_tokens=exc.usage.input_tokens,
                    output_tokens=exc.usage.output_tokens,
                )
                run = InvestigationRun(
                    run_id=run_id,
                    tenant_id=tenant_id,
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

    def get_investigation(self, run_id: str, *, tenant_id: str) -> InvestigationRun:
        with self._observability.operation("workflow.get_investigation"):
            run = self._store.get_run(run_id)
            self._require_run_tenant(run, tenant_id)
            return run

    def create_proposal(
        self,
        run_id: str,
        action: RemediationAction,
        *,
        created_by: Actor,
        tenant_id: str,
    ) -> RemediationProposal:
        with self._observability.operation("workflow.create_proposal"):
            run = self._store.get_run(run_id)
            self._require_run_tenant(run, tenant_id)
            return self._create_proposal(run, action, created_by=created_by)

    def _create_proposal(
        self,
        run: InvestigationRun,
        action: RemediationAction,
        *,
        created_by: Actor,
    ) -> RemediationProposal:
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
            run_id=run.run_id,
            plan_digest=remediation_plan_digest(run.run_id, action),
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

    def get_proposal(self, proposal_id: str, *, tenant_id: str) -> RemediationProposal:
        with self._observability.operation("workflow.get_proposal"):
            proposal = self._store.get_proposal(proposal_id)
            self._require_proposal_tenant(proposal, tenant_id)
            return proposal

    def decide_proposal(
        self,
        proposal_id: str,
        *,
        decision: Literal["approve", "reject"],
        expected_plan_digest: str,
        decided_by: Actor,
        reason: str,
        tenant_id: str,
    ) -> RemediationProposal:
        with self._observability.operation("workflow.decide_proposal"):
            proposal = self._store.get_proposal(proposal_id)
            self._require_proposal_tenant(proposal, tenant_id)
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
        tenant_id: str,
    ) -> RemediationExecution:
        with self._observability.operation("workflow.execute_proposal"):
            proposal = self._store.get_proposal(proposal_id)
            self._require_proposal_tenant(proposal, tenant_id)
            if not self._store.verify_audit_chain(proposal.run_id):
                raise WorkflowError("audit_integrity_failed")
            now = self._clock()
            claim = self._store.claim_execution(
                proposal_id,
                idempotency_key=idempotency_key,
                requested_by=requested_by,
                lease_owner=self._worker_id,
                lease_expires_at=now + self._execution_lease_ttl,
                now=now,
            )
            if not claim.claimed:
                if claim.execution.status == "executing":
                    raise WorkflowError("execution_in_progress")
                return claim.execution
            if claim.recovered:
                self._observability.record_lease_recovery()

            try:
                outcome = self._executor.execute(
                    proposal.action,
                    idempotency_key=idempotency_key,
                )
            except Exception as exc:
                self._store.fail_execution(
                    claim.execution.execution_id,
                    "execution_adapter_failed",
                    lease_owner=self._worker_id,
                    fencing_token=claim.execution.fencing_token,
                    now=self._clock(),
                )
                raise WorkflowError("execution_adapter_failed") from exc
            return self._store.complete_execution(
                claim.execution.execution_id,
                outcome,
                lease_owner=self._worker_id,
                fencing_token=claim.execution.fencing_token,
                now=self._clock(),
            )

    def audit_events(self, run_id: str, *, tenant_id: str) -> list[AuditEvent]:
        with self._observability.operation("workflow.audit_events"):
            run = self._store.get_run(run_id)
            self._require_run_tenant(run, tenant_id)
            events = self._store.list_audit_events(run_id)
            if not self._store.verify_audit_chain(run_id):
                raise WorkflowError("audit_integrity_failed")
            return events

    def is_ready(self) -> bool:
        return self._store.is_ready()

    @staticmethod
    def _require_run_tenant(run: InvestigationRun, tenant_id: str) -> None:
        if run.tenant_id != tenant_id:
            raise WorkflowError("run_not_found")

    def _require_proposal_tenant(
        self,
        proposal: RemediationProposal,
        tenant_id: str,
    ) -> None:
        run = self._store.get_run(proposal.run_id)
        if run.tenant_id != tenant_id:
            raise WorkflowError("proposal_not_found")
