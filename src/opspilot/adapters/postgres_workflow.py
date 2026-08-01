from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from psycopg import Connection
from psycopg import Error as PsycopgError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from pydantic import BaseModel

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
    remediation_plan_digest,
    verify_audit_events,
)


def _json(model: BaseModel) -> str:
    return model.model_dump_json()


class PostgresWorkflowStore:
    """Atomic PostgreSQL state transitions for approval-gated remediation."""

    def __init__(
        self,
        database_url: str,
        *,
        pool_min_size: int = 1,
        pool_max_size: int = 8,
    ) -> None:
        self._pool = cast(
            ConnectionPool[Connection[dict[str, Any]]],
            ConnectionPool(
                conninfo=database_url,
                min_size=pool_min_size,
                max_size=pool_max_size,
                kwargs={"row_factory": dict_row},
                open=False,
            ),
        )
        try:
            self._pool.open(wait=True)
        except (PsycopgError, PoolTimeout) as exc:
            raise WorkflowError("workflow_unavailable") from exc

    @contextmanager
    def _connection(self) -> Iterator[Connection[dict[str, Any]]]:
        try:
            with self._pool.connection() as connection:
                yield connection
        except WorkflowError:
            raise
        except (PsycopgError, PoolTimeout) as exc:
            raise WorkflowError("workflow_unavailable") from exc

    def close(self) -> None:
        self._pool.close()

    def create_run(self, run: InvestigationRun) -> InvestigationRun:
        with self._connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO investigation_runs (
                    run_id, tenant_id, incident_id, status, request, result, failure,
                    created_by, created_at, updated_at, version
                ) VALUES (
                    %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s, %s, %s
                )
                """,
                (
                    run.run_id,
                    run.tenant_id,
                    run.request.incident_id,
                    run.status,
                    _json(run.request),
                    _json(run.result) if run.result is not None else None,
                    _json(run.failure) if run.failure is not None else None,
                    _json(run.created_by),
                    run.created_at,
                    run.updated_at,
                    run.version,
                ),
            )
            self._append_event(
                connection,
                run.run_id,
                "investigation.created",
                run.created_by,
                {"incident_id": run.request.incident_id, "status": run.status},
                run.created_at,
            )
        return run

    def get_run(self, run_id: str) -> InvestigationRun:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM investigation_runs WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        if row is None:
            raise WorkflowError("run_not_found")
        return self._run_from_row(row)

    def create_proposal(self, proposal: RemediationProposal) -> RemediationProposal:
        with self._connection() as connection, connection.transaction():
            if self._lock_run(connection, proposal.run_id) is None:
                raise WorkflowError("run_not_found")
            connection.execute(
                """
                INSERT INTO remediation_proposals (
                    proposal_id, run_id, plan_version, plan_digest, action, dry_run,
                    status, created_by, approval, created_at, updated_at, version
                ) VALUES (
                    %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                    %s, %s::jsonb, NULL, %s, %s, %s
                )
                """,
                (
                    proposal.proposal_id,
                    proposal.run_id,
                    proposal.plan_version,
                    proposal.plan_digest,
                    _json(proposal.action),
                    _json(proposal.dry_run),
                    proposal.status,
                    _json(proposal.created_by),
                    proposal.created_at,
                    proposal.updated_at,
                    proposal.version,
                ),
            )
            self._append_event(
                connection,
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
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM remediation_proposals WHERE proposal_id = %s",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise WorkflowError("proposal_not_found")
        return self._proposal_from_row(row)

    def decide_proposal(
        self,
        proposal_id: str,
        decision: ApprovalDecision,
        *,
        now: datetime,
    ) -> RemediationProposal:
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                "SELECT * FROM remediation_proposals WHERE proposal_id = %s FOR UPDATE",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise WorkflowError("proposal_not_found")
            proposal = self._proposal_from_row(row)
            self._lock_run(connection, proposal.run_id)
            if proposal.status != "awaiting_approval" or proposal.approval is not None:
                raise WorkflowError("proposal_already_decided")
            if (
                decision.expected_plan_digest != proposal.plan_digest
                or remediation_plan_digest(proposal.run_id, proposal.action) != proposal.plan_digest
            ):
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
            connection.execute(
                """
                UPDATE remediation_proposals
                SET status = %s, approval = %s::jsonb, updated_at = %s, version = %s
                WHERE proposal_id = %s
                """,
                (status, _json(decision), now, updated.version, proposal_id),
            )
            event_type = (
                "remediation.approved" if decision.decision == "approve" else "remediation.rejected"
            )
            self._append_event(
                connection,
                proposal.run_id,
                event_type,
                decision.decided_by,
                {
                    "proposal_id": proposal.proposal_id,
                    "plan_digest": proposal.plan_digest,
                    "reason": decision.reason,
                    "expires_at": (
                        decision.expires_at.isoformat() if decision.expires_at is not None else None
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
        lease_owner: str,
        lease_expires_at: datetime,
        now: datetime,
    ) -> ExecutionClaim:
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                "SELECT * FROM remediation_proposals WHERE proposal_id = %s FOR UPDATE",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise WorkflowError("proposal_not_found")
            proposal = self._proposal_from_row(row)
            self._lock_run(connection, proposal.run_id)
            existing_row = connection.execute(
                "SELECT * FROM remediation_executions WHERE proposal_id = %s FOR UPDATE",
                (proposal_id,),
            ).fetchone()
            if existing_row is not None:
                existing = self._execution_from_row(existing_row)
                if existing.idempotency_key != idempotency_key:
                    raise WorkflowError("idempotency_key_conflict")
                if existing.status != "executing" or existing.lease_expires_at > now:
                    return ExecutionClaim(existing, claimed=False)
                recovered = existing.model_copy(
                    update={
                        "requested_by": requested_by,
                        "lease_owner": lease_owner,
                        "lease_expires_at": lease_expires_at,
                        "fencing_token": existing.fencing_token + 1,
                        "attempt_count": existing.attempt_count + 1,
                    }
                )
                connection.execute(
                    """
                    UPDATE remediation_executions
                    SET requested_by = %s::jsonb, lease_owner = %s,
                        lease_expires_at = %s, fencing_token = %s, attempt_count = %s
                    WHERE execution_id = %s
                    """,
                    (
                        _json(requested_by),
                        lease_owner,
                        lease_expires_at,
                        recovered.fencing_token,
                        recovered.attempt_count,
                        recovered.execution_id,
                    ),
                )
                self._append_event(
                    connection,
                    existing.run_id,
                    "remediation.execution_recovered",
                    requested_by,
                    {
                        "proposal_id": existing.proposal_id,
                        "execution_id": existing.execution_id,
                        "attempt_count": recovered.attempt_count,
                        "fencing_token": recovered.fencing_token,
                    },
                    now,
                )
                return ExecutionClaim(recovered, claimed=True, recovered=True)
            conflicting = connection.execute(
                "SELECT execution_id FROM remediation_executions WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
            if conflicting is not None:
                raise WorkflowError("idempotency_key_conflict")

            approval = proposal.approval
            if proposal.status != "approved" or approval is None:
                raise WorkflowError("approval_required")
            if (
                approval.expected_plan_digest != proposal.plan_digest
                or remediation_plan_digest(proposal.run_id, proposal.action) != proposal.plan_digest
            ):
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
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                fencing_token=1,
                attempt_count=1,
                status="executing",
                outcome=None,
                error_code=None,
                created_at=now,
                completed_at=None,
            )
            connection.execute(
                """
                INSERT INTO remediation_executions (
                    execution_id, proposal_id, run_id, idempotency_key, plan_digest,
                    requested_by, lease_owner, lease_expires_at, fencing_token, attempt_count,
                    status, outcome, error_code, created_at, completed_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s,
                    'executing', NULL, NULL, %s, NULL
                )
                """,
                (
                    execution.execution_id,
                    execution.proposal_id,
                    execution.run_id,
                    execution.idempotency_key,
                    execution.plan_digest,
                    _json(execution.requested_by),
                    execution.lease_owner,
                    execution.lease_expires_at,
                    execution.fencing_token,
                    execution.attempt_count,
                    execution.created_at,
                ),
            )
            connection.execute(
                """
                UPDATE remediation_proposals
                SET status = 'executing', updated_at = %s, version = version + 1
                WHERE proposal_id = %s
                """,
                (now, proposal_id),
            )
            self._append_event(
                connection,
                proposal.run_id,
                "remediation.execution_claimed",
                requested_by,
                {
                    "proposal_id": proposal.proposal_id,
                    "execution_id": execution.execution_id,
                    "idempotency_key": idempotency_key,
                    "plan_digest": proposal.plan_digest,
                    "attempt_count": execution.attempt_count,
                    "fencing_token": execution.fencing_token,
                },
                now,
            )
        return ExecutionClaim(execution, claimed=True)

    def complete_execution(
        self,
        execution_id: str,
        outcome: RemediationOutcome,
        *,
        lease_owner: str,
        fencing_token: int,
        now: datetime,
    ) -> RemediationExecution:
        with self._connection() as connection, connection.transaction():
            execution = self._locked_execution(connection, execution_id)
            self._lock_run(connection, execution.run_id)
            if execution.status == "completed":
                return execution
            if execution.status != "executing":
                raise WorkflowError("execution_adapter_failed")
            self._require_lease(execution, lease_owner, fencing_token, now)
            completed = execution.model_copy(
                update={"status": "completed", "outcome": outcome, "completed_at": now}
            )
            connection.execute(
                """
                UPDATE remediation_executions
                SET status = 'completed', outcome = %s::jsonb, completed_at = %s
                WHERE execution_id = %s
                """,
                (_json(outcome), now, execution_id),
            )
            connection.execute(
                """
                UPDATE remediation_proposals
                SET status = 'completed', updated_at = %s, version = version + 1
                WHERE proposal_id = %s
                """,
                (now, execution.proposal_id),
            )
            self._append_event(
                connection,
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
        lease_owner: str,
        fencing_token: int,
        now: datetime,
    ) -> RemediationExecution:
        with self._connection() as connection, connection.transaction():
            execution = self._locked_execution(connection, execution_id)
            self._lock_run(connection, execution.run_id)
            if execution.status != "executing":
                return execution
            self._require_lease(execution, lease_owner, fencing_token, now)
            failed = execution.model_copy(
                update={"status": "failed", "error_code": error_code, "completed_at": now}
            )
            connection.execute(
                """
                UPDATE remediation_executions
                SET status = 'failed', error_code = %s, completed_at = %s
                WHERE execution_id = %s
                """,
                (error_code, now, execution_id),
            )
            connection.execute(
                """
                UPDATE remediation_proposals
                SET status = 'failed', updated_at = %s, version = version + 1
                WHERE proposal_id = %s
                """,
                (now, execution.proposal_id),
            )
            self._append_event(
                connection,
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

    def renew_execution_lease(
        self,
        execution_id: str,
        *,
        lease_owner: str,
        fencing_token: int,
        lease_expires_at: datetime,
        now: datetime,
    ) -> RemediationExecution:
        if lease_expires_at <= now:
            raise ValueError("renewed lease expiry must be in the future")
        with self._connection() as connection, connection.transaction():
            execution = self._locked_execution(connection, execution_id)
            self._require_lease(execution, lease_owner, fencing_token, now)
            connection.execute(
                """
                UPDATE remediation_executions
                SET lease_expires_at = %s
                WHERE execution_id = %s
                """,
                (lease_expires_at, execution_id),
            )
        return execution.model_copy(update={"lease_expires_at": lease_expires_at})

    def list_audit_events(self, run_id: str) -> list[AuditEvent]:
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT run_id FROM investigation_runs WHERE run_id = %s", (run_id,)
                ).fetchone()
                is None
            ):
                raise WorkflowError("run_not_found")
            rows = connection.execute(
                """
                SELECT * FROM workflow_audit_events
                WHERE run_id = %s ORDER BY sequence_no
                """,
                (run_id,),
            ).fetchall()
        return [self._audit_from_row(row) for row in rows]

    def verify_audit_chain(self, run_id: str) -> bool:
        return verify_audit_events(self.list_audit_events(run_id))

    def is_ready(self) -> bool:
        with self._connection() as connection:
            row = connection.execute("SELECT 1 AS ready").fetchone()
        return row is not None and row["ready"] == 1

    @staticmethod
    def _require_lease(
        execution: RemediationExecution,
        lease_owner: str,
        fencing_token: int,
        now: datetime,
    ) -> None:
        if (
            execution.status != "executing"
            or execution.lease_owner != lease_owner
            or execution.fencing_token != fencing_token
            or execution.lease_expires_at <= now
        ):
            raise WorkflowError("execution_lease_lost")

    @staticmethod
    def _lock_run(connection: Connection[dict[str, Any]], run_id: str) -> Mapping[str, Any] | None:
        return connection.execute(
            "SELECT run_id FROM investigation_runs WHERE run_id = %s FOR UPDATE",
            (run_id,),
        ).fetchone()

    def _locked_execution(
        self,
        connection: Connection[dict[str, Any]],
        execution_id: str,
    ) -> RemediationExecution:
        row = connection.execute(
            "SELECT * FROM remediation_executions WHERE execution_id = %s FOR UPDATE",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise WorkflowError("execution_adapter_failed")
        return self._execution_from_row(row)

    def _append_event(
        self,
        connection: Connection[dict[str, Any]],
        run_id: str,
        event_type: str,
        actor: Actor,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> None:
        rows = connection.execute(
            """
            SELECT * FROM workflow_audit_events
            WHERE run_id = %s ORDER BY sequence_no
            """,
            (run_id,),
        ).fetchall()
        existing_events = [self._audit_from_row(row) for row in rows]
        if existing_events and not verify_audit_events(existing_events):
            raise WorkflowError("audit_integrity_failed")
        sequence_no = len(existing_events) + 1
        previous_hash = existing_events[-1].event_hash if existing_events else None
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
        connection.execute(
            """
            INSERT INTO workflow_audit_events (
                event_id, run_id, sequence_no, event_type, actor, payload,
                previous_hash, event_hash, occurred_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
            """,
            (
                event.event_id,
                event.run_id,
                event.sequence_no,
                event.event_type,
                _json(event.actor),
                json.dumps(event.payload, sort_keys=True),
                event.previous_hash,
                event.event_hash,
                event.occurred_at,
            ),
        )

    @staticmethod
    def _run_from_row(row: Mapping[str, Any]) -> InvestigationRun:
        payload = dict(row)
        payload.pop("incident_id", None)
        return InvestigationRun.model_validate(payload)

    @staticmethod
    def _proposal_from_row(row: Mapping[str, Any]) -> RemediationProposal:
        return RemediationProposal.model_validate(dict(row))

    @staticmethod
    def _execution_from_row(row: Mapping[str, Any]) -> RemediationExecution:
        return RemediationExecution.model_validate(dict(row))

    @staticmethod
    def _audit_from_row(row: Mapping[str, Any]) -> AuditEvent:
        return AuditEvent(
            event_id=str(row["event_id"]),
            run_id=str(row["run_id"]),
            sequence_no=int(row["sequence_no"]),
            event_type=str(row["event_type"]),
            actor=row["actor"],
            payload=row["payload"],
            previous_hash=(str(row["previous_hash"]) if row["previous_hash"] else None),
            event_hash=str(row["event_hash"]),
            occurred_at=row["occurred_at"],
        )
