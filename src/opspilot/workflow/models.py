from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from opspilot.investigation.models import (
    EvidenceItem,
    IncidentRequest,
    InvestigationResult,
    ToolTrace,
    UsageSummary,
)

RunStatus = Literal["completed", "failed"]
ProposalStatus = Literal[
    "awaiting_approval",
    "approved",
    "rejected",
    "executing",
    "completed",
    "failed",
]
ExecutionStatus = Literal["executing", "completed", "failed"]
ActorType = Literal["human", "service", "system"]
Decision = Literal["approve", "reject"]


class WorkflowModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Actor(WorkflowModel):
    actor_type: ActorType
    actor_id: str = Field(pattern=r"^[a-zA-Z0-9_.:@/-]{3,160}$")
    display_name: str = Field(min_length=1, max_length=160)


class InvestigationFailureSnapshot(WorkflowModel):
    code: str = Field(min_length=3, max_length=128)
    category: str = Field(min_length=3, max_length=64)
    retryable: bool
    message: str = Field(min_length=1, max_length=500)
    trace: list[ToolTrace]
    evidence: list[EvidenceItem]
    usage: UsageSummary


class InvestigationRun(WorkflowModel):
    run_id: str = Field(pattern=r"^run_[a-f0-9]{32}$")
    tenant_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{2,63}$")
    request: IncidentRequest
    status: RunStatus
    result: InvestigationResult | None
    failure: InvestigationFailureSnapshot | None
    created_by: Actor
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_outcome(self) -> InvestigationRun:
        if self.status == "completed" and (self.result is None or self.failure is not None):
            raise ValueError("completed runs require a result and no failure")
        if self.status == "failed" and (self.failure is None or self.result is not None):
            raise ValueError("failed runs require a failure and no result")
        return self


class RemediationAction(WorkflowModel):
    action_type: Literal["restart_deployment"] = "restart_deployment"
    service: str = Field(min_length=1, max_length=128)
    environment: str = Field(min_length=1, max_length=64)
    deployment: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,127}$")
    reason: str = Field(min_length=10, max_length=1_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("remediation evidence IDs must be unique")
        return values


class DryRunResult(WorkflowModel):
    action_type: Literal["restart_deployment"]
    side_effects_performed: Literal[False] = False
    predicted_effect: str = Field(min_length=1, max_length=500)
    preconditions: list[str] = Field(min_length=1, max_length=20)
    risk: Literal["medium"] = "medium"


class ApprovalDecision(WorkflowModel):
    decision: Decision
    decided_by: Actor
    reason: str = Field(min_length=3, max_length=1_000)
    expected_plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decided_at: datetime
    expires_at: datetime | None

    @model_validator(mode="after")
    def validate_expiry(self) -> ApprovalDecision:
        if self.decided_by.actor_type != "human":
            raise ValueError("approval decisions require a human actor")
        if self.decision == "approve" and self.expires_at is None:
            raise ValueError("approved decisions require an expiry")
        if self.decision == "reject" and self.expires_at is not None:
            raise ValueError("rejected decisions cannot have an expiry")
        if self.expires_at is not None and self.expires_at <= self.decided_at:
            raise ValueError("approval expiry must be after the decision time")
        return self


class RemediationProposal(WorkflowModel):
    proposal_id: str = Field(pattern=r"^prop_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^run_[a-f0-9]{32}$")
    plan_version: Literal[1] = 1
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: RemediationAction
    dry_run: DryRunResult
    status: ProposalStatus
    created_by: Actor
    approval: ApprovalDecision | None
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class RemediationOutcome(WorkflowModel):
    provider_reference: str = Field(min_length=3, max_length=200)
    summary: str = Field(min_length=3, max_length=500)
    simulated: bool


class RemediationExecution(WorkflowModel):
    execution_id: str = Field(pattern=r"^exec_[a-f0-9]{32}$")
    proposal_id: str = Field(pattern=r"^prop_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^run_[a-f0-9]{32}$")
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{8,128}$")
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    requested_by: Actor
    lease_owner: str = Field(pattern=r"^[a-zA-Z0-9_.:@-]{1,128}$", exclude=True)
    lease_expires_at: datetime
    fencing_token: int = Field(ge=1)
    attempt_count: int = Field(ge=1)
    status: ExecutionStatus
    outcome: RemediationOutcome | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None

    @model_validator(mode="after")
    def validate_outcome(self) -> RemediationExecution:
        if self.lease_expires_at.tzinfo is None:
            raise ValueError("execution lease expiry must include a timezone")
        if self.status == "executing" and (
            self.outcome is not None or self.error_code is not None or self.completed_at is not None
        ):
            raise ValueError("executing records cannot contain a terminal outcome")
        if self.status == "completed" and (
            self.outcome is None or self.error_code is not None or self.completed_at is None
        ):
            raise ValueError("completed records require an outcome")
        if self.status == "failed" and (
            self.outcome is not None or self.error_code is None or self.completed_at is None
        ):
            raise ValueError("failed records require an error code")
        return self


class AuditEvent(WorkflowModel):
    event_id: str = Field(pattern=r"^audit_[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^run_[a-f0-9]{32}$")
    sequence_no: int = Field(ge=1)
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    actor: Actor
    payload: dict[str, object]
    previous_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    occurred_at: datetime


def remediation_plan_digest(run_id: str, action: RemediationAction) -> str:
    payload = {
        "plan_version": 1,
        "run_id": run_id,
        "action": action.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def audit_event_digest(
    *,
    run_id: str,
    sequence_no: int,
    event_type: str,
    actor: Actor,
    payload: dict[str, object],
    previous_hash: str | None,
    occurred_at: datetime,
) -> str:
    canonical = json.dumps(
        {
            "run_id": run_id,
            "sequence_no": sequence_no,
            "event_type": event_type,
            "actor": actor.model_dump(mode="json"),
            "payload": payload,
            "previous_hash": previous_hash,
            "occurred_at": occurred_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_audit_events(events: list[AuditEvent]) -> bool:
    if not events:
        return False
    expected_run_id = events[0].run_id
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, 1):
        if (
            event.run_id != expected_run_id
            or event.sequence_no != expected_sequence
            or event.previous_hash != previous_hash
        ):
            return False
        expected_hash = audit_event_digest(
            run_id=event.run_id,
            sequence_no=event.sequence_no,
            event_type=event.event_type,
            actor=event.actor,
            payload=event.payload,
            previous_hash=event.previous_hash,
            occurred_at=event.occurred_at,
        )
        if event.event_hash != expected_hash:
            return False
        previous_hash = event.event_hash
    return True
