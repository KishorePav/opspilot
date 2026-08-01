from __future__ import annotations

import os
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import psycopg

from opspilot.adapters.postgres_workflow import PostgresWorkflowStore
from opspilot.adapters.synthetic_remediation import SyntheticRemediationExecutor
from opspilot.investigation.models import (
    CitedClaim,
    DiagnosisReport,
    EvidenceItem,
    IncidentRequest,
    ModelTurn,
    RankedHypothesis,
    ToolCall,
    ToolTrace,
)
from opspilot.investigation.orchestrator import IncidentInvestigator
from opspilot.storage.migrations import apply_migrations
from opspilot.tools.base import ToolSpec
from opspilot.workflow.failures import WorkflowError
from opspilot.workflow.models import Actor, RemediationAction
from opspilot.workflow.service import RemediationWorkflowService

_DATABASE_URL = os.getenv("OPSPILOT_TEST_DATABASE_URL")
_EVIDENCE_ID = "log:postgres-workflow-restart"
_NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


class EvidenceTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="fetch_postgres_evidence",
            description="Return a durable workflow test record.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )

    def execute(self, arguments: Mapping[str, object]) -> list[EvidenceItem]:
        if arguments:
            raise ValueError("the durable evidence tool takes no arguments")
        return [
            EvidenceItem(
                evidence_id=_EVIDENCE_ID,
                kind="log",
                title="Synthetic deployment stalled",
                source="synthetic://postgres-test",
                content="The deployment stopped progressing and needs a rolling restart.",
                occurred_at=datetime(2026, 8, 2, 9, 55, tzinfo=UTC),
                metadata={"environment": "synthetic", "service": "orders"},
            )
        ]


class DiagnosingGateway:
    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn:
        del tools
        if not trace:
            return ModelTurn(
                tool_calls=[
                    ToolCall(
                        call_id="postgres-evidence-1",
                        name="fetch_postgres_evidence",
                        arguments={},
                    )
                ],
                report=None,
            )
        return ModelTurn(
            tool_calls=[],
            report=DiagnosisReport(
                incident_id=request.incident_id,
                status="diagnosed",
                affected_services=request.services,
                summary="The synthetic deployment is stalled.",
                timeline=[],
                hypotheses=[
                    RankedHypothesis(
                        rank=1,
                        statement="A rolling restart is required.",
                        confidence="high",
                        evidence_ids=[evidence[0].evidence_id],
                    )
                ],
                probable_root_cause=CitedClaim(
                    statement="The deployment stopped progressing.",
                    evidence_ids=[evidence[0].evidence_id],
                ),
                confidence="high",
                next_actions=[],
                unanswered_questions=[],
            ),
        )


def _actor(
    actor_id: str,
    actor_type: Literal["human", "service", "system"] = "human",
) -> Actor:
    return Actor(actor_type=actor_type, actor_id=actor_id, display_name=actor_id.title())


def _request() -> IncidentRequest:
    return IncidentRequest(
        incident_id="inc-postgres-orders-101",
        summary="Orders deployment is stalled",
        environment="synthetic",
        started_at=datetime(2026, 8, 2, 9, 45, tzinfo=UTC),
        ended_at=_NOW,
        services=["orders"],
    )


def _action() -> RemediationAction:
    return RemediationAction(
        service="orders",
        environment="synthetic",
        deployment="orders-api",
        reason="Restart the stalled deployment after reviewing the evidence.",
        evidence_ids=[_EVIDENCE_ID],
    )


@unittest.skipUnless(_DATABASE_URL, "OPSPILOT_TEST_DATABASE_URL is not configured")
class PostgresWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert _DATABASE_URL is not None
        apply_migrations(_DATABASE_URL, Path("migrations"))

    def setUp(self) -> None:
        assert _DATABASE_URL is not None
        with psycopg.connect(_DATABASE_URL, autocommit=True) as connection:
            connection.execute(
                """
                TRUNCATE workflow_audit_events, remediation_executions,
                         remediation_proposals, investigation_runs CASCADE
                """
            )
        self.store = PostgresWorkflowStore(
            _DATABASE_URL,
            pool_min_size=1,
            pool_max_size=2,
        )
        self.executor = SyntheticRemediationExecutor()
        self.service = RemediationWorkflowService(
            IncidentInvestigator(DiagnosingGateway(), [EvidenceTool()]),
            self.store,
            self.executor,
            approval_ttl=timedelta(minutes=10),
            clock=lambda: _NOW,
        )
        self.operator = _actor("operator@example.com")
        self.approver = _actor("approver@example.com")
        self.runner = _actor("workflow-runner", "service")

    def tearDown(self) -> None:
        self.service.close()

    def _approved_proposal(self) -> tuple[str, str]:
        run = self.service.create_investigation(_request(), created_by=self.operator)
        proposal = self.service.create_proposal(
            run.run_id,
            _action(),
            created_by=self.operator,
        )
        self.service.decide_proposal(
            proposal.proposal_id,
            decision="approve",
            expected_plan_digest=proposal.plan_digest,
            decided_by=self.approver,
            reason="The exact digest and synthetic dry run were reviewed.",
        )
        return run.run_id, proposal.proposal_id

    def test_state_and_idempotent_execution_survive_store_recreation(self) -> None:
        run_id, proposal_id = self._approved_proposal()
        first = self.service.execute_proposal(
            proposal_id,
            idempotency_key="postgres-restart-orders-101",
            requested_by=self.runner,
        )
        self.service.close()

        assert _DATABASE_URL is not None
        reopened_store = PostgresWorkflowStore(
            _DATABASE_URL,
            pool_min_size=1,
            pool_max_size=2,
        )
        reopened_executor = SyntheticRemediationExecutor()
        self.service = RemediationWorkflowService(
            IncidentInvestigator(DiagnosingGateway(), [EvidenceTool()]),
            reopened_store,
            reopened_executor,
            approval_ttl=timedelta(minutes=10),
            clock=lambda: _NOW,
        )
        replay = self.service.execute_proposal(
            proposal_id,
            idempotency_key="postgres-restart-orders-101",
            requested_by=self.runner,
        )

        self.assertEqual(first, replay)
        self.assertEqual(0, reopened_executor.execution_count)
        self.assertEqual("completed", self.service.get_proposal(proposal_id).status)
        self.assertEqual(run_id, self.service.get_investigation(run_id).run_id)
        self.assertEqual(5, len(self.service.audit_events(run_id)))

    def test_conflicting_idempotency_key_is_rejected(self) -> None:
        _, proposal_id = self._approved_proposal()
        self.service.execute_proposal(
            proposal_id,
            idempotency_key="postgres-restart-orders-101",
            requested_by=self.runner,
        )
        with self.assertRaisesRegex(WorkflowError, "idempotency_key_conflict"):
            self.service.execute_proposal(
                proposal_id,
                idempotency_key="different-restart-key-101",
                requested_by=self.runner,
            )

    def test_database_plan_tampering_is_detected_before_approval(self) -> None:
        run = self.service.create_investigation(_request(), created_by=self.operator)
        proposal = self.service.create_proposal(
            run.run_id,
            _action(),
            created_by=self.operator,
        )
        assert _DATABASE_URL is not None
        with psycopg.connect(_DATABASE_URL) as connection:
            connection.execute(
                """
                UPDATE remediation_proposals
                SET action = jsonb_set(action, '{deployment}', '"tampered-api"')
                WHERE proposal_id = %s
                """,
                (proposal.proposal_id,),
            )
        with self.assertRaisesRegex(WorkflowError, "plan_digest_mismatch"):
            self.service.decide_proposal(
                proposal.proposal_id,
                decision="approve",
                expected_plan_digest=proposal.plan_digest,
                decided_by=self.approver,
                reason="A modified plan must not be approved.",
            )

    def test_audit_rows_are_database_immutable(self) -> None:
        run = self.service.create_investigation(_request(), created_by=self.operator)
        assert _DATABASE_URL is not None
        with self.assertRaises(psycopg.Error), psycopg.connect(_DATABASE_URL) as connection:
            connection.execute(
                "UPDATE workflow_audit_events SET payload = '{}' WHERE run_id = %s",
                (run.run_id,),
            )


if __name__ == "__main__":
    unittest.main()
