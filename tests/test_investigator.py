from __future__ import annotations

import unittest
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from opspilot.domain.models import Document
from opspilot.investigation.failures import InvestigationFailedError
from opspilot.investigation.models import (
    CitedClaim,
    DiagnosisReport,
    EvidenceItem,
    IncidentRequest,
    ModelTurn,
    ModelUsage,
    NextAction,
    RankedHypothesis,
    TimelineEvent,
    ToolCall,
    ToolTrace,
)
from opspilot.investigation.orchestrator import IncidentInvestigator
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.retrieval.service import HybridRetriever
from opspilot.tools.base import ReadOnlyTool, ToolSpec
from opspilot.tools.operational import OperationalFixtureStore, build_operational_tools
from opspilot.tools.retrieval import RunbookSearchTool

_FIXTURE = Path("fixtures/operations/dataflow-permission-denied.json")


def _request() -> IncidentRequest:
    return IncidentRequest(
        incident_id="inc-dataflow-042",
        summary="Dataflow workers cannot start after the latest release",
        environment="synthetic",
        started_at=datetime.fromisoformat("2026-08-01T10:00:00+00:00"),
        ended_at=datetime.fromisoformat("2026-08-01T10:15:00+00:00"),
        services=["dataflow-worker"],
    )


def _report(runbook_id: str, *, root_cause_id: str) -> DiagnosisReport:
    return DiagnosisReport(
        incident_id="inc-dataflow-042",
        status="diagnosed",
        affected_services=["dataflow-worker"],
        summary="Worker launches began failing after the worker identity changed.",
        timeline=[
            TimelineEvent(
                occurred_at=datetime.fromisoformat("2026-08-01T10:02:00+00:00"),
                description="The deployment changed the configured worker identity.",
                evidence_ids=["deployment:dataflow-release-042"],
            ),
            TimelineEvent(
                occurred_at=datetime.fromisoformat("2026-08-01T10:05:00+00:00"),
                description="The launcher was denied permission to act as the new identity.",
                evidence_ids=["log:dataflow-actas-denied-1005"],
            ),
        ],
        hypotheses=[
            RankedHypothesis(
                rank=1,
                statement="The release introduced an unauthorized worker identity.",
                confidence="high",
                evidence_ids=[
                    "deployment:dataflow-release-042",
                    "log:dataflow-actas-denied-1005",
                    runbook_id,
                ],
            )
        ],
        probable_root_cause=CitedClaim(
            statement="The release selected a worker identity the launcher cannot impersonate.",
            evidence_ids=[root_cause_id, "deployment:dataflow-release-042"],
        ),
        confidence="high",
        next_actions=[
            NextAction(
                description="Verify the intended worker identity and its narrow actAs binding.",
                rationale=(
                    "The runbook requires checking launcher and worker identities separately."
                ),
                evidence_ids=[runbook_id, "log:dataflow-actas-denied-1005"],
            )
        ],
        unanswered_questions=[],
    )


class ScriptedGateway:
    def __init__(self, *, hallucinate_citation: bool = False) -> None:
        self._hallucinate_citation = hallucinate_citation

    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn:
        del request, tools
        if not trace:
            return ModelTurn(
                tool_calls=[
                    ToolCall(
                        call_id="call-runbook",
                        name="search_runbooks",
                        arguments={"query": "cannot act as service account", "top_k": 3},
                    )
                ],
                report=None,
            )
        if len(trace) == 1:
            window = {
                "service": "dataflow-worker",
                "environment": "synthetic",
                "started_at": "2026-08-01T10:00:00Z",
                "ended_at": "2026-08-01T10:15:00Z",
                "limit": 20,
            }
            return ModelTurn(
                tool_calls=[
                    ToolCall(
                        call_id="call-logs",
                        name="search_logs",
                        arguments=window,
                    ),
                    ToolCall(
                        call_id="call-deployments",
                        name="list_deployments",
                        arguments=window,
                    ),
                    ToolCall(
                        call_id="call-metrics",
                        name="query_metrics",
                        arguments={
                            **window,
                            "metric_names": ["worker_launch_failures"],
                        },
                    ),
                ],
                report=None,
            )

        runbook_id = next(item.evidence_id for item in evidence if item.kind == "runbook")
        root_cause_id = (
            "log:invented-evidence"
            if self._hallucinate_citation
            else "log:dataflow-actas-denied-1005"
        )
        return ModelTurn(
            tool_calls=[],
            report=_report(runbook_id, root_cause_id=root_cause_id),
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
                    call_id="repeated-call",
                    name="search_runbooks",
                    arguments={"query": "permission denied", "top_k": 3},
                )
            ],
            report=None,
        )


class HighUsageGateway:
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
                    call_id="over-token-budget",
                    name="search_runbooks",
                    arguments={"query": "permission denied", "top_k": 1},
                )
            ],
            report=None,
            usage=ModelUsage(
                model="synthetic-model",
                input_tokens=80,
                output_tokens=20,
                total_tokens=100,
            ),
        )


class OutOfScopeThenStopGateway:
    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn:
        del request, evidence, tools
        if not trace:
            return ModelTurn(
                tool_calls=[
                    ToolCall(
                        call_id="out-of-scope",
                        name="search_logs",
                        arguments={
                            "service": "payments",
                            "environment": "production",
                            "started_at": "2026-08-01T10:00:00Z",
                            "ended_at": "2026-08-01T10:15:00Z",
                            "limit": 10,
                        },
                    )
                ],
                report=None,
            )
        return ModelTurn(
            tool_calls=[],
            report=DiagnosisReport(
                incident_id="inc-dataflow-042",
                status="insufficient_evidence",
                affected_services=["dataflow-worker"],
                summary="The attempted query exceeded the incident scope.",
                timeline=[],
                hypotheses=[],
                probable_root_cause=None,
                confidence="low",
                next_actions=[],
                unanswered_questions=["What evidence is available inside the allowed scope?"],
            ),
        )


class IncidentInvestigatorTests(unittest.TestCase):
    def setUp(self) -> None:
        retriever = HybridRetriever(HashEmbeddingProvider())
        retriever.index_documents(
            [
                Document(
                    document_id="dataflow-runbook",
                    title="Dataflow service account permission denied",
                    content=(
                        "Identify the launcher and worker identities. The launcher requires "
                        "iam.serviceAccounts.actAs on the selected worker identity."
                    ),
                    source="synthetic-runbook.md",
                )
            ]
        )
        store = OperationalFixtureStore.from_path(_FIXTURE)
        self.tools: list[ReadOnlyTool] = [
            RunbookSearchTool(retriever),
            *build_operational_tools(store),
        ]

    def test_agent_executes_bounded_tools_and_returns_cited_report(self) -> None:
        result = IncidentInvestigator(ScriptedGateway(), self.tools).investigate(_request())

        self.assertEqual("diagnosed", result.report.status)
        self.assertEqual(4, len(result.trace))
        self.assertTrue(all(item.status == "succeeded" for item in result.trace))
        evidence_ids = {item.evidence_id for item in result.evidence}
        self.assertIn("log:dataflow-actas-denied-1005", evidence_ids)
        self.assertIn("deployment:dataflow-release-042", evidence_ids)
        self.assertIn("metric:dataflow-launch-failures-1007", evidence_ids)

    def test_agent_rejects_a_hallucinated_evidence_id(self) -> None:
        investigator = IncidentInvestigator(
            ScriptedGateway(hallucinate_citation=True),
            self.tools,
        )
        with self.assertRaisesRegex(
            InvestigationFailedError, "report_contains_unknown_citation"
        ):
            investigator.investigate(_request())

    def test_duplicate_tool_call_fails_closed(self) -> None:
        investigator = IncidentInvestigator(RepeatingGateway(), self.tools)
        with self.assertRaisesRegex(
            InvestigationFailedError, "duplicate_tool_call"
        ) as raised:
            investigator.investigate(_request())

        self.assertEqual("safety_policy", raised.exception.category)
        self.assertEqual(1, len(raised.exception.trace))
        self.assertIsNotNone(raised.exception.usage)
        assert raised.exception.usage is not None
        self.assertEqual(2, raised.exception.usage.model_calls)

    def test_out_of_scope_call_is_not_executed(self) -> None:
        result = IncidentInvestigator(OutOfScopeThenStopGateway(), self.tools).investigate(
            _request()
        )

        self.assertEqual("insufficient_evidence", result.report.status)
        self.assertEqual("failed", result.trace[0].status)
        self.assertEqual("scope_violation", result.trace[0].error_code)
        self.assertEqual([], result.evidence)

    def test_model_token_budget_stops_before_another_tool_call(self) -> None:
        investigator = IncidentInvestigator(
            HighUsageGateway(),
            self.tools,
            max_total_tokens=50,
        )

        with self.assertRaisesRegex(
            InvestigationFailedError, "token_budget_exhausted"
        ) as raised:
            investigator.investigate(_request())

        self.assertEqual([], list(raised.exception.trace))
        assert raised.exception.usage is not None
        self.assertEqual(100, raised.exception.usage.total_tokens)


if __name__ == "__main__":
    unittest.main()
