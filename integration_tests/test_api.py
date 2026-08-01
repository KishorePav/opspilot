import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from opspilot.adapters.synthetic_remediation import SyntheticRemediationExecutor
from opspilot.api import (
    create_app,
    get_authenticator,
    get_investigator,
    get_observability,
    get_retriever,
    get_workflow_service,
)
from opspilot.auth import Principal, StaticTokenAuthenticator
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
from opspilot.observability import RecordingObservability
from opspilot.tools.base import ToolSpec
from opspilot.workflow.memory import InMemoryWorkflowStore
from opspilot.workflow.service import RemediationWorkflowService

_WORKFLOW_EVIDENCE_ID = "log:api-workflow-restart"


def _principal(
    subject: str,
    *roles: str,
    actor_type: str = "human",
    tenant_id: str = "tenant-alpha",
) -> Principal:
    return Principal.model_validate(
        {
            "subject": subject,
            "display_name": subject,
            "tenant_id": tenant_id,
            "actor_type": actor_type,
            "roles": list(roles),
        }
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
        get_authenticator.cache_clear()
        get_observability.cache_clear()
        self.app = create_app()
        self.observability = RecordingObservability()
        authenticator = StaticTokenAuthenticator(
            {
                "operator": _principal(
                    "operator@example.com", "investigator", "remediation_proposer"
                ),
                "approver": _principal("approver@example.com", "remediation_approver"),
                "runner": _principal(
                    "workflow-runner", "remediation_executor", actor_type="service"
                ),
                "auditor": _principal("auditor@example.com", "auditor"),
                "service-approver": _principal(
                    "automated-approver",
                    "remediation_approver",
                    actor_type="service",
                ),
                "other-tenant": _principal(
                    "other@example.com",
                    "auditor",
                    tenant_id="tenant-beta",
                ),
            }
        )

        def override_authenticator() -> StaticTokenAuthenticator:
            return authenticator

        def override_observability() -> RecordingObservability:
            return self.observability

        self.app.dependency_overrides[get_authenticator] = override_authenticator
        self.app.dependency_overrides[get_observability] = override_observability
        investigator = IncidentInvestigator(InsufficientEvidenceGateway(), [])

        def override_investigator() -> IncidentInvestigator:
            return investigator

        self.app.dependency_overrides[get_investigator] = override_investigator
        workflow = RemediationWorkflowService(
            IncidentInvestigator(WorkflowGateway(), [WorkflowEvidenceTool()]),
            InMemoryWorkflowStore(),
            SyntheticRemediationExecutor(),
            approval_ttl=timedelta(minutes=10),
            worker_id="api-worker",
            observability=self.observability,
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
        get_authenticator.cache_clear()
        get_observability.cache_clear()

    async def test_health_endpoint(self) -> None:
        response = await self.client.get("/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())

    async def test_openapi_contract_requires_bearer_auth_and_has_no_actor_inputs(self) -> None:
        schema = self.app.openapi()
        durable_schema = schema["components"]["schemas"]["DurableInvestigationRequest"]
        proposal_schema = schema["components"]["schemas"]["ProposalRequest"]
        decision_schema = schema["components"]["schemas"]["ProposalDecisionRequest"]
        execution_schema = schema["components"]["schemas"]["ExecutionRequest"]

        self.assertEqual("0.8.0", schema["info"]["version"])
        self.assertIn("HTTPBearer", schema["components"]["securitySchemes"])
        self.assertEqual({"incident"}, set(durable_schema["properties"]))
        self.assertEqual({"action"}, set(proposal_schema["properties"]))
        self.assertNotIn("decided_by", decision_schema["properties"])
        self.assertNotIn("requested_by", execution_schema["properties"])
        self.assertTrue(schema["paths"]["/v1/retrieve"]["post"]["security"])

    async def test_retrieval_endpoint_returns_cited_evidence(self) -> None:
        response = await self.client.post(
            "/v1/retrieve",
            json={"query": "Dataflow cannot act as service account", "top_k": 3},
            headers=_auth("operator"),
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
            headers=_auth("operator"),
        )
        self.assertEqual(422, response.status_code)

    async def test_investigation_endpoint_returns_structured_report(self) -> None:
        response = await self.client.post(
            "/v1/investigate",
            json={
                "incident_id": "inc-dataflow-042",
                "summary": "Workers cannot start",
                "environment": "synthetic",
                "started_at": datetime.fromisoformat("2026-08-01T10:00:00+00:00").isoformat(),
                "ended_at": datetime.fromisoformat("2026-08-01T10:15:00+00:00").isoformat(),
                "services": ["dataflow-worker"],
            },
            headers=_auth("operator"),
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
            headers=_auth("operator"),
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
            },
            headers=_auth("operator"),
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
            },
            headers=_auth("operator"),
        )
        self.assertEqual(201, proposed.status_code)
        proposal = proposed.json()
        self.assertFalse(proposal["dry_run"]["side_effects_performed"])

        approved = await self.client.post(
            f"/v1/remediation-proposals/{proposal['proposal_id']}/decisions",
            json={
                "decision": "approve",
                "expected_plan_digest": proposal["plan_digest"],
                "reason": "The exact plan digest and dry run were reviewed.",
            },
            headers=_auth("approver"),
        )
        self.assertEqual(200, approved.status_code)
        self.assertEqual("approved", approved.json()["status"])

        execution_body = {"idempotency_key": "api-orders-restart-101"}
        first = await self.client.post(
            f"/v1/remediation-proposals/{proposal['proposal_id']}/executions",
            json=execution_body,
            headers=_auth("runner"),
        )
        replay = await self.client.post(
            f"/v1/remediation-proposals/{proposal['proposal_id']}/executions",
            json=execution_body,
            headers=_auth("runner"),
        )
        self.assertEqual(200, first.status_code)
        self.assertEqual(first.json(), replay.json())
        self.assertEqual("completed", first.json()["status"])
        self.assertTrue(first.json()["outcome"]["simulated"])

        audit = await self.client.get(
            f"/v1/investigations/{run_id}/audit-events",
            headers=_auth("auditor"),
        )
        self.assertEqual(200, audit.status_code)
        self.assertTrue(audit.json()["verified"])
        self.assertEqual(5, len(audit.json()["events"]))

    async def test_non_human_approval_is_rejected(self) -> None:
        created = await self.client.post(
            "/v1/investigations",
            json={
                "incident": {
                    "incident_id": "inc-service-approval-101",
                    "summary": "Orders deployment is stuck",
                    "environment": "synthetic",
                    "started_at": "2026-08-02T09:45:00Z",
                    "ended_at": "2026-08-02T10:00:00Z",
                    "services": ["orders"],
                }
            },
            headers=_auth("operator"),
        )
        run_id = created.json()["run_id"]
        proposed = await self.client.post(
            f"/v1/investigations/{run_id}/remediation-proposals",
            json={
                "action": {
                    "action_type": "restart_deployment",
                    "service": "orders",
                    "environment": "synthetic",
                    "deployment": "orders-api",
                    "reason": "Restart only after a verified human reviews the plan.",
                    "evidence_ids": [_WORKFLOW_EVIDENCE_ID],
                }
            },
            headers=_auth("operator"),
        )
        proposal = proposed.json()
        response = await self.client.post(
            f"/v1/remediation-proposals/{proposal['proposal_id']}/decisions",
            json={
                "decision": "approve",
                "expected_plan_digest": proposal["plan_digest"],
                "reason": "Automation cannot approve a remediation.",
            },
            headers=_auth("service-approver"),
        )
        self.assertEqual(422, response.status_code)
        self.assertEqual("approval_actor_required", response.json()["detail"]["code"])

    async def test_missing_token_and_wrong_role_fail_closed(self) -> None:
        missing = await self.client.post(
            "/v1/retrieve",
            json={"query": "database latency"},
        )
        wrong_role = await self.client.post(
            "/v1/retrieve",
            json={"query": "database latency"},
            headers=_auth("auditor"),
        )

        self.assertEqual(401, missing.status_code)
        self.assertEqual("authentication_required", missing.json()["detail"]["code"])
        self.assertEqual(403, wrong_role.status_code)
        self.assertEqual("forbidden", wrong_role.json()["detail"]["code"])

    async def test_tenant_scoping_hides_another_tenants_run(self) -> None:
        created = await self.client.post(
            "/v1/investigations",
            json={
                "incident": {
                    "incident_id": "inc-tenant-scope-101",
                    "summary": "Tenant-scoped synthetic incident",
                    "environment": "synthetic",
                    "started_at": "2026-08-02T09:45:00Z",
                    "ended_at": "2026-08-02T10:00:00Z",
                    "services": ["orders"],
                }
            },
            headers=_auth("operator"),
        )
        run_id = created.json()["run_id"]
        hidden = await self.client.get(
            f"/v1/investigations/{run_id}/audit-events",
            headers=_auth("other-tenant"),
        )

        self.assertEqual(404, hidden.status_code)
        self.assertEqual("run_not_found", hidden.json()["detail"]["code"])


if __name__ == "__main__":
    unittest.main()
