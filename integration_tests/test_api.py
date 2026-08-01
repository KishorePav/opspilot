import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from opspilot.adapters.synthetic_remediation import SyntheticRemediationExecutor
from opspilot.api import (
    create_app,
    get_investigator,
    get_retriever,
    get_workflow_service,
)
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
from opspilot.workflow.memory import InMemoryWorkflowStore
from opspilot.workflow.service import RemediationWorkflowService

_WORKFLOW_EVIDENCE_ID = "log:api-workflow-restart"


class WorkflowEvidenceTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="fetch_workflow_evidence",
            description="Return one synthetic workflow evidence record.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )

    def execute(self, arguments: Mapping[str, object]) -> list[EvidenceItem]:
        if arguments:
            raise ValueError("workflow evidence takes no arguments")
        return [
            EvidenceItem(
                evidence_id=_WORKFLOW_EVIDENCE_ID,
                kind="log",
                title="Orders deployment stuck",
                source="synthetic://api-test",
                content="The synthetic deployment stopped progressing.",
                occurred_at=datetime(2026, 8, 2, 9, 55, tzinfo=UTC),
                metadata={"service": "orders", "environment": "synthetic"},
            )
        ]


class WorkflowGateway:
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
                        call_id="workflow-evidence-1",
                        name="fetch_workflow_evidence",
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
                summary="The synthetic orders deployment is stuck.",
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


class InsufficientEvidenceGateway:
    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn:
        del evidence, trace, tools
        return ModelTurn(
            tool_calls=[],
            report=DiagnosisReport(
                incident_id=request.incident_id,
                status="insufficient_evidence",
                affected_services=request.services,
                summary="No operational evidence has been collected yet.",
                timeline=[],
                hypotheses=[],
                probable_root_cause=None,
                confidence="low",
                next_actions=[],
                unanswered_questions=["Which read-only evidence source should be queried?"],
            ),
        )


class RepeatingGateway:
    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn:
        del request, evidence, trace, tools
        return ModelTurn(
            tool_calls=[
                ToolCall(
                    call_id="repeat",
                    name="search_logs",
                    arguments={"service": "dataflow-worker"},
                )
            ],
            report=None,
        )


class RetrievalApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        get_retriever.cache_clear()
        get_investigator.cache_clear()
        get_workflow_service.cache_clear()
        self.app = create_app()
        investigator = IncidentInvestigator(InsufficientEvidenceGateway(), [])

        def override_investigator() -> IncidentInvestigator:
            return investigator

        self.app.dependency_overrides[get_investigator] = override_investigator
        workflow = RemediationWorkflowService(
            IncidentInvestigator(WorkflowGateway(), [WorkflowEvidenceTool()]),
            InMemoryWorkflowStore(),
            SyntheticRemediationExecutor(),
            approval_ttl=timedelta(minutes=10),
            clock=lambda: datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
        )

        def override_workflow() -> RemediationWorkflowService:
            return workflow

        self.app.dependency_overrides[get_workflow_service] = override_workflow
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://test",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        self.app.dependency_overrides.clear()
        get_investigator.cache_clear()
        get_retriever.cache_clear()
        get_workflow_service.cache_clear()

    async def test_health_endpoint(self) -> None:
        response = await self.client.get("/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())

    async def test_retrieval_endpoint_returns_cited_evidence(self) -> None:
        response = await self.client.post(
            "/v1/retrieve",
            json={"query": "Dataflow cannot act as service account", "top_k": 3},
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("dataflow-permission-denied", payload["evidence"][0]["document_id"])
        self.assertTrue(payload["evidence"][0]["chunk_id"])
        self.assertTrue(payload["evidence"][0]["source"].endswith(".md"))
        self.assertEqual("synthetic", payload["evidence"][0]["metadata"]["environment"])

    async def test_rejects_invalid_filter_keys(self) -> None:
        response = await self.client.post(
            "/v1/retrieve",
            json={"query": "database latency", "filters": {"unsafe key": "value"}},
        )
        self.assertEqual(422, response.status_code)

    async def test_investigation_endpoint_returns_structured_report(self) -> None:
        response = await self.client.post(
            "/v1/investigate",
            json={
                "incident_id": "inc-dataflow-042",
                "summary": "Workers cannot start",
                "environment": "synthetic",
                "started_at": datetime.fromisoformat(
                    "2026-08-01T10:00:00+00:00"
                ).isoformat(),
                "ended_at": datetime.fromisoformat(
                    "2026-08-01T10:15:00+00:00"
                ).isoformat(),
                "services": ["dataflow-worker"],
            },
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("inc-dataflow-042", payload["report"]["incident_id"])
        self.assertEqual("insufficient_evidence", payload["report"]["status"])
        self.assertEqual([], payload["evidence"])
        self.assertEqual([], payload["trace"])
        self.assertEqual(1, payload["usage"]["model_calls"])
        self.assertEqual(0, payload["usage"]["total_tokens"])

    async def test_investigation_failure_returns_typed_public_detail(self) -> None:
        failing = IncidentInvestigator(RepeatingGateway(), [])

        def override_investigator() -> IncidentInvestigator:
            return failing

        self.app.dependency_overrides[get_investigator] = override_investigator
        response = await self.client.post(
            "/v1/investigate",
            json={
                "incident_id": "inc-dataflow-042",
                "summary": "Workers cannot start",
                "environment": "synthetic",
                "started_at": "2026-08-01T10:00:00Z",
                "ended_at": "2026-08-01T10:15:00Z",
                "services": ["dataflow-worker"],
            },
        )

        self.assertEqual(503, response.status_code)
        self.assertEqual(
            {
                "code": "duplicate_tool_call",
                "category": "safety_policy",
                "retryable": False,
                "message": "The investigation repeated an identical tool call.",
            },
            response.json()["detail"],
        )

    async def test_durable_approval_api_is_digest_bound_and_idempotent(self) -> None:
        operator = {
            "actor_type": "human",
            "actor_id": "operator@example.com",
            "display_name": "Operator",
        }
        approver = {
            "actor_type": "human",
            "actor_id": "approver@example.com",
            "display_name": "Approver",
        }
        runner = {
            "actor_type": "service",
            "actor_id": "workflow-runner",
            "display_name": "Workflow Runner",
        }
        created = await self.client.post(
            "/v1/investigations",
            json={
                "incident": {
                    "incident_id": "inc-orders-api-101",
                    "summary": "Orders deployment is stuck",
                    "environment": "synthetic",
                    "started_at": "2026-08-02T09:45:00Z",
                    "ended_at": "2026-08-02T10:00:00Z",
                    "services": ["orders"],
                },
                "created_by": operator,
            },
        )
        self.assertEqual(201, created.status_code)
        run_id = created.json()["run_id"]

        proposed = await self.client.post(
            f"/v1/investigations/{run_id}/remediation-proposals",
            json={
                "action": {
                    "action_type": "restart_deployment",
                    "service": "orders",
                    "environment": "synthetic",
                    "deployment": "orders-api",
                    "reason": "Restart the stuck deployment after reviewing its evidence.",
                    "evidence_ids": [_WORKFLOW_EVIDENCE_ID],
                },
                "created_by": operator,
            },
        )
        self.assertEqual(201, proposed.status_code)
        proposal = proposed.json()
        self.assertFalse(proposal["dry_run"]["side_effects_performed"])

        approved = await self.client.post(
            f"/v1/remediation-proposals/{proposal['proposal_id']}/decisions",
            json={
                "decision": "approve",
                "expected_plan_digest": proposal["plan_digest"],
                "decided_by": approver,
                "reason": "The exact plan digest and dry run were reviewed.",
            },
        )
        self.assertEqual(200, approved.status_code)
        self.assertEqual("approved", approved.json()["status"])

        execution_body = {
            "idempotency_key": "api-orders-restart-101",
            "requested_by": runner,
        }
        first = await self.client.post(
            f"/v1/remediation-proposals/{proposal['proposal_id']}/executions",
            json=execution_body,
        )
        replay = await self.client.post(
            f"/v1/remediation-proposals/{proposal['proposal_id']}/executions",
            json=execution_body,
        )
        self.assertEqual(200, first.status_code)
        self.assertEqual(first.json(), replay.json())
        self.assertEqual("completed", first.json()["status"])
        self.assertTrue(first.json()["outcome"]["simulated"])

        audit = await self.client.get(f"/v1/investigations/{run_id}/audit-events")
        self.assertEqual(200, audit.status_code)
        self.assertTrue(audit.json()["verified"])
        self.assertEqual(5, len(audit.json()["events"]))

    async def test_non_human_approval_is_rejected(self) -> None:
        response = await self.client.post(
            "/v1/remediation-proposals/prop_00000000000000000000000000000000/decisions",
            json={
                "decision": "approve",
                "expected_plan_digest": "0" * 64,
                "decided_by": {
                    "actor_type": "service",
                    "actor_id": "auto-approver",
                    "display_name": "Automation",
                },
                "reason": "Automation cannot approve a remediation.",
            },
        )
        self.assertEqual(422, response.status_code)
        self.assertEqual("approval_actor_required", response.json()["detail"]["code"])


if __name__ == "__main__":
    unittest.main()
