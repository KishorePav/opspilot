from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from opspilot.workflow.models import (
    Actor,
    ApprovalDecision,
    AuditEvent,
    DryRunResult,
    InvestigationRun,
    RemediationAction,
    RemediationExecution,
    RemediationOutcome,
    RemediationProposal,
)


@dataclass(frozen=True, slots=True)
class ExecutionClaim:
    execution: RemediationExecution
    claimed: bool


class WorkflowStore(Protocol):
    def create_run(self, run: InvestigationRun) -> InvestigationRun: ...

    def get_run(self, run_id: str) -> InvestigationRun: ...

    def create_proposal(self, proposal: RemediationProposal) -> RemediationProposal: ...

    def get_proposal(self, proposal_id: str) -> RemediationProposal: ...

    def decide_proposal(
        self,
        proposal_id: str,
        decision: ApprovalDecision,
        *,
        now: datetime,
    ) -> RemediationProposal: ...

    def claim_execution(
        self,
        proposal_id: str,
        *,
        idempotency_key: str,
        requested_by: Actor,
        now: datetime,
    ) -> ExecutionClaim: ...

    def complete_execution(
        self,
        execution_id: str,
        outcome: RemediationOutcome,
        *,
        now: datetime,
    ) -> RemediationExecution: ...

    def fail_execution(
        self,
        execution_id: str,
        error_code: str,
        *,
        now: datetime,
    ) -> RemediationExecution: ...

    def list_audit_events(self, run_id: str) -> list[AuditEvent]: ...

    def verify_audit_chain(self, run_id: str) -> bool: ...

    def close(self) -> None: ...


class RemediationExecutor(Protocol):
    def dry_run(self, action: RemediationAction) -> DryRunResult: ...

    def execute(
        self,
        action: RemediationAction,
        *,
        idempotency_key: str,
    ) -> RemediationOutcome: ...


class AuditReadableStore(Protocol):
    def list_audit_events(self, run_id: str) -> Sequence[AuditEvent]: ...
