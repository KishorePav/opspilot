from __future__ import annotations

import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from opspilot.adapters.synthetic_remediation import SyntheticRemediationExecutor
from opspilot.investigation.gateway import ModelGatewayError
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
from opspilot.tools.base import ToolSpec
from opspilot.workflow.failures import WorkflowError
from opspilot.workflow.memory import InMemoryWorkflowStore
from opspilot.workflow.models import (
    Actor,
    RemediationAction,
    verify_audit_events,
)
from opspilot.workflow.service import RemediationWorkflowService

_EVIDENCE_ID = "log:synthetic-restart-required"
_TENANT_ID = "tenant-alpha"


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


class EvidenceTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="fetch_evidence",
            description="Return one bounded synthetic evidence record.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )

    def execute(self, arguments: Mapping[str, object]) -> list[EvidenceItem]:
        if arguments:
            raise ValueError("the synthetic evidence tool takes no arguments")
        return [
            EvidenceItem(
                evidence_id=_EVIDENCE_ID,
                kind="log",
                title="Deployment restart required",
                source="synthetic://operations",
                content="The synthetic deployment is stuck and requires a rolling restart.",
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
                tool_calls=[ToolCall(call_id="fetch-1", name="fetch_evidence", arguments={})],
                report=None,
            )
        return ModelTurn(
            tool_calls=[],
            report=DiagnosisReport(
                incident_id=request.incident_id,
                status="diagnosed",
                affected_services=request.services,
                summary="The synthetic deployment is stuck.",
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


class FailingGateway:
    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn:
        del request, evidence, trace, tools
        raise ModelGatewayError("synthetic provider failure")


def _actor(
    actor_id: str,
    *,
    actor_type: Literal["human", "service", "system"] = "human",
) -> Actor:
    return Actor(actor_type=actor_type, actor_id=actor_id, display_name=actor_id.title())


def _request() -> IncidentRequest:
    return IncidentRequest(
        incident_id="inc-orders-101",
        summary="Orders deployment is stuck",
        environment="synthetic",
        started_at=datetime(2026, 8, 2, 9, 45, tzinfo=UTC),
        ended_at=datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
        services=["orders"],
    )


def _action(*, evidence_ids: list[str] | None = None) -> RemediationAction:
    return RemediationAction(
        service="orders",
        environment="synthetic",
        deployment="orders-api",
        reason="Restart the stuck synthetic deployment after diagnosis.",
        evidence_ids=evidence_ids or [_EVIDENCE_ID],
    )


class RemediationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.store = InMemoryWorkflowStore()
        self.executor = SyntheticRemediationExecutor()
        self.service = RemediationWorkflowService(
            IncidentInvestigator(DiagnosingGateway(), [EvidenceTool()]),
            self.store,
            self.executor,
            approval_ttl=timedelta(minutes=10),
            execution_lease_ttl=timedelta(seconds=10),
            worker_id="worker-a",
            clock=self.clock,
        )
        self.operator = _actor("operator@example.com")
        self.approver = _actor("approver@example.com")
        self.runner = _actor("workflow-runner", actor_type="service")

    def _proposal(self) -> tuple[str, str]:
        run = self.service.create_investigation(
            _request(), created_by=self.operator, tenant_id=_TENANT_ID
        )
        proposal = self.service.create_proposal(
            run.run_id,
            _action(),
            created_by=self.operator,
            tenant_id=_TENANT_ID,
        )
        return run.run_id, proposal.proposal_id

    def test_proposal_is_a_side_effect_free_digest_bound_dry_run(self) -> None:
        run_id, proposal_id = self._proposal()
        proposal = self.service.get_proposal(proposal_id, tenant_id=_TENANT_ID)

        self.assertEqual(run_id, proposal.run_id)
        self.assertEqual("awaiting_approval", proposal.status)
        self.assertFalse(proposal.dry_run.side_effects_performed)
        self.assertEqual(64, len(proposal.plan_digest))
        self.assertEqual(0, self.executor.execution_count)

    def test_human_approval_executes_exactly_once_for_replayed_key(self) -> None:
        run_id, proposal_id = self._proposal()
        proposal = self.service.get_proposal(proposal_id, tenant_id=_TENANT_ID)
        approved = self.service.decide_proposal(
            proposal_id,
            decision="approve",
            expected_plan_digest=proposal.plan_digest,
            decided_by=self.approver,
            reason="The evidence and dry run were reviewed.",
            tenant_id=_TENANT_ID,
        )

        first = self.service.execute_proposal(
            proposal_id,
            idempotency_key="restart-orders-101",
            requested_by=self.runner,
            tenant_id=_TENANT_ID,
        )
        replay = self.service.execute_proposal(
            proposal_id,
            idempotency_key="restart-orders-101",
            requested_by=self.runner,
            tenant_id=_TENANT_ID,
        )

        self.assertEqual("approve", approved.approval.decision if approved.approval else None)
        self.assertEqual("completed", first.status)
        self.assertEqual(first, replay)
        self.assertEqual(1, self.executor.execution_count)
        events = self.service.audit_events(run_id, tenant_id=_TENANT_ID)
        self.assertEqual(
            [
                "investigation.created",
                "remediation.proposed",
                "remediation.approved",
                "remediation.execution_claimed",
                "remediation.executed",
            ],
            [event.event_type for event in events],
        )

    def test_changed_digest_and_self_approval_fail_closed(self) -> None:
        _, proposal_id = self._proposal()
        proposal = self.service.get_proposal(proposal_id, tenant_id=_TENANT_ID)

        with self.assertRaisesRegex(WorkflowError, "plan_digest_mismatch"):
            self.service.decide_proposal(
                proposal_id,
                decision="approve",
                expected_plan_digest="0" * 64,
                decided_by=self.approver,
                reason="This digest is deliberately wrong.",
                tenant_id=_TENANT_ID,
            )
        with self.assertRaisesRegex(WorkflowError, "self_approval_forbidden"):
            self.service.decide_proposal(
                proposal_id,
                decision="approve",
                expected_plan_digest=proposal.plan_digest,
                decided_by=self.operator,
                reason="Self approval must not be accepted.",
                tenant_id=_TENANT_ID,
            )

    def test_rejection_and_expiry_block_execution(self) -> None:
        _, rejected_id = self._proposal()
        rejected = self.service.get_proposal(rejected_id, tenant_id=_TENANT_ID)
        self.service.decide_proposal(
            rejected_id,
            decision="reject",
            expected_plan_digest=rejected.plan_digest,
            decided_by=self.approver,
            reason="The blast radius is not acceptable.",
            tenant_id=_TENANT_ID,
        )
        with self.assertRaisesRegex(WorkflowError, "approval_required"):
            self.service.execute_proposal(
                rejected_id,
                idempotency_key="rejected-orders-101",
                requested_by=self.runner,
                tenant_id=_TENANT_ID,
            )

        _, expired_id = self._proposal()
        expired = self.service.get_proposal(expired_id, tenant_id=_TENANT_ID)
        self.service.decide_proposal(
            expired_id,
            decision="approve",
            expected_plan_digest=expired.plan_digest,
            decided_by=self.approver,
            reason="Approve only inside the short review window.",
            tenant_id=_TENANT_ID,
        )
        self.clock.value += timedelta(minutes=11)
        with self.assertRaisesRegex(WorkflowError, "approval_expired"):
            self.service.execute_proposal(
                expired_id,
                idempotency_key="expired-orders-101",
                requested_by=self.runner,
                tenant_id=_TENANT_ID,
            )

    def test_scope_and_evidence_are_bound_to_the_diagnosed_run(self) -> None:
        run = self.service.create_investigation(
            _request(), created_by=self.operator, tenant_id=_TENANT_ID
        )
        with self.assertRaisesRegex(WorkflowError, "invalid_remediation_evidence"):
            self.service.create_proposal(
                run.run_id,
                _action(evidence_ids=["log:not-collected"]),
                created_by=self.operator,
                tenant_id=_TENANT_ID,
            )
        out_of_scope = _action().model_copy(update={"service": "payments"})
        with self.assertRaisesRegex(WorkflowError, "remediation_scope_violation"):
            self.service.create_proposal(
                run.run_id,
                out_of_scope,
                created_by=self.operator,
                tenant_id=_TENANT_ID,
            )

    def test_audit_hash_chain_detects_modified_payload(self) -> None:
        run_id, _ = self._proposal()
        events = self.service.audit_events(run_id, tenant_id=_TENANT_ID)
        self.assertTrue(verify_audit_events(events))
        corrupted = list(events)
        corrupted[1] = corrupted[1].model_copy(update={"payload": {"tampered": True}})
        self.assertFalse(verify_audit_events(corrupted))

    def test_failed_investigation_is_durable_but_cannot_propose_remediation(self) -> None:
        failed_service = RemediationWorkflowService(
            IncidentInvestigator(FailingGateway(), []),
            InMemoryWorkflowStore(),
            SyntheticRemediationExecutor(),
            clock=self.clock,
        )
        run = failed_service.create_investigation(
            _request(), created_by=self.operator, tenant_id=_TENANT_ID
        )

        self.assertEqual("failed", run.status)
        self.assertEqual("model_gateway_failed", run.failure.code if run.failure else None)
        with self.assertRaisesRegex(WorkflowError, "run_not_diagnosed"):
            failed_service.create_proposal(
                run.run_id,
                _action(),
                created_by=self.operator,
                tenant_id=_TENANT_ID,
            )

    def test_tenant_scope_is_checked_before_returning_workflow_state(self) -> None:
        run_id, proposal_id = self._proposal()

        with self.assertRaisesRegex(WorkflowError, "run_not_found"):
            self.service.get_investigation(run_id, tenant_id="tenant-beta")
        with self.assertRaisesRegex(WorkflowError, "proposal_not_found"):
            self.service.get_proposal(proposal_id, tenant_id="tenant-beta")

    def test_expired_execution_is_recovered_with_a_fencing_token(self) -> None:
        run_id, proposal_id = self._proposal()
        proposal = self.service.get_proposal(proposal_id, tenant_id=_TENANT_ID)
        self.service.decide_proposal(
            proposal_id,
            decision="approve",
            expected_plan_digest=proposal.plan_digest,
            decided_by=self.approver,
            reason="The exact plan and dry run were reviewed.",
            tenant_id=_TENANT_ID,
        )
        first = self.store.claim_execution(
            proposal_id,
            idempotency_key="lease-recovery-orders-101",
            requested_by=self.runner,
            lease_owner="worker-a",
            lease_expires_at=self.clock.value + timedelta(seconds=5),
            now=self.clock.value,
        )
        self.clock.value += timedelta(seconds=6)
        recovered = self.store.claim_execution(
            proposal_id,
            idempotency_key="lease-recovery-orders-101",
            requested_by=self.runner,
            lease_owner="worker-b",
            lease_expires_at=self.clock.value + timedelta(seconds=10),
            now=self.clock.value,
        )

        self.assertTrue(recovered.claimed)
        self.assertTrue(recovered.recovered)
        self.assertEqual(2, recovered.execution.attempt_count)
        self.assertEqual(first.execution.fencing_token + 1, recovered.execution.fencing_token)
        outcome = self.executor.execute(_action(), idempotency_key="lease-recovery-orders-101")
        with self.assertRaisesRegex(WorkflowError, "execution_lease_lost"):
            self.store.complete_execution(
                first.execution.execution_id,
                outcome,
                lease_owner="worker-a",
                fencing_token=first.execution.fencing_token,
                now=self.clock.value,
            )
        completed = self.store.complete_execution(
            recovered.execution.execution_id,
            outcome,
            lease_owner="worker-b",
            fencing_token=recovered.execution.fencing_token,
            now=self.clock.value,
        )
        self.assertEqual("completed", completed.status)
        self.assertIn(
            "remediation.execution_recovered",
            [event.event_type for event in self.service.audit_events(run_id, tenant_id=_TENANT_ID)],
        )


if __name__ == "__main__":
    unittest.main()
