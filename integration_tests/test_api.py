import unittest
from collections.abc import Sequence
from datetime import datetime

from httpx import ASGITransport, AsyncClient

from opspilot.api import create_app, get_investigator, get_retriever
from opspilot.investigation.models import (
    DiagnosisReport,
    EvidenceItem,
    IncidentRequest,
    ModelTurn,
    ToolCall,
    ToolTrace,
)
from opspilot.investigation.orchestrator import IncidentInvestigator
from opspilot.tools.base import ToolSpec


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
        self.app = create_app()
        investigator = IncidentInvestigator(InsufficientEvidenceGateway(), [])

        def override_investigator() -> IncidentInvestigator:
            return investigator

        self.app.dependency_overrides[get_investigator] = override_investigator
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://test",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        self.app.dependency_overrides.clear()
        get_investigator.cache_clear()
        get_retriever.cache_clear()

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


if __name__ == "__main__":
    unittest.main()
