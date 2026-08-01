from __future__ import annotations

import unittest
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from opspilot.corpus import load_markdown_documents
from opspilot.evaluation.agent import (
    AgentEvaluationRegressionError,
    AgentEvaluator,
    enforce_thresholds,
    evaluate_cases,
    load_agent_eval_cases,
    load_thresholds,
)
from opspilot.investigation.gateway import (
    InvestigationModelGateway,
    ModelGatewayError,
    ProviderDiagnostic,
)
from opspilot.investigation.models import (
    EvidenceItem,
    IncidentRequest,
    ModelTurn,
    ToolTrace,
)
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.retrieval.service import HybridRetriever
from opspilot.tools.base import ReadOnlyTool, ToolSpec
from opspilot.tools.operational import OperationalFixtureStore, build_operational_tools
from opspilot.tools.retrieval import RunbookSearchTool

_DATASET = Path("evals/investigation_cases.jsonl")
_THRESHOLDS = Path("evals/agent_thresholds.json")


class DiagnosticFailureGateway(InvestigationModelGateway):
    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn:
        del request, evidence, trace, tools
        raise ModelGatewayError(
            "provider message is intentionally not exported",
            diagnostic=ProviderDiagnostic(
                provider="gemini",
                error_type="ClientError",
                error_code="RESOURCE_EXHAUSTED",
                http_status=429,
                request_id="request-123",
            ),
        )


class AgentEvaluationTests(unittest.TestCase):
    tools: list[ReadOnlyTool]

    @classmethod
    def setUpClass(cls) -> None:
        retriever = HybridRetriever(HashEmbeddingProvider())
        retriever.index_documents(load_markdown_documents(Path("fixtures/runbooks")))
        store = OperationalFixtureStore.from_path(
            Path("fixtures/operations/dataflow-permission-denied.json")
        )
        cls.tools = [
            RunbookSearchTool(retriever),
            *build_operational_tools(store),
        ]

    def test_versioned_agent_dataset_passes_every_grader(self) -> None:
        thresholds = load_thresholds(_THRESHOLDS)
        report = evaluate_cases(
            load_agent_eval_cases(_DATASET),
            tools=self.tools,
            dataset_version=thresholds.dataset_version,
        )

        enforce_thresholds(report, thresholds)
        self.assertEqual(6, report.summary.cases)
        self.assertEqual(6, report.summary.passed_cases)
        self.assertEqual(1.0, report.summary.safety_pass_rate)
        self.assertEqual(1.0, report.summary.citation_precision)
        self.assertEqual(1.0, report.summary.citation_recall)
        self.assertEqual(9380, report.summary.total_tokens)
        self.assertEqual(Decimal("0.009585"), report.summary.estimated_cost_usd)
        self.assertEqual(
            {"budget": 1, "safety_policy": 4},
            report.summary.observed_failures_by_category,
        )

    def test_injection_attempt_is_observable_but_cannot_succeed(self) -> None:
        thresholds = load_thresholds(_THRESHOLDS)
        report = evaluate_cases(
            load_agent_eval_cases(_DATASET),
            tools=self.tools,
            dataset_version=thresholds.dataset_version,
        )
        case = next(
            item
            for item in report.cases
            if item.case_id == "injection-driven-remediation-attempt-is-blocked"
        )

        attempted = next(item for item in case.trace if item.tool_name == "approve_remediation")
        self.assertEqual("failed", attempted.status)
        self.assertEqual("unknown_tool", attempted.error_code)
        self.assertTrue(case.passed)

    def test_threshold_regression_fails_the_gate(self) -> None:
        thresholds = load_thresholds(_THRESHOLDS)
        report = evaluate_cases(
            load_agent_eval_cases(_DATASET),
            tools=self.tools,
            dataset_version=thresholds.dataset_version,
        )
        regressed = thresholds.model_copy(update={"maximum_total_tokens": 1})

        with self.assertRaisesRegex(
            AgentEvaluationRegressionError, "total_tokens"
        ):
            enforce_thresholds(report, regressed)

    def test_provider_diagnostic_is_recorded_without_exception_text(self) -> None:
        case = load_agent_eval_cases(_DATASET)[0]

        result = AgentEvaluator(self.tools).evaluate_gateway(
            case_id=case.case_id,
            request=case.request,
            expected=case.expected,
            budgets=case.budgets,
            gateway=DiagnosticFailureGateway(),
        )

        diagnostic = result.provider_diagnostic
        assert diagnostic is not None
        self.assertEqual("gemini", diagnostic.provider)
        self.assertEqual("RESOURCE_EXHAUSTED", diagnostic.error_code)
        self.assertEqual(429, diagnostic.http_status)
        self.assertNotIn("provider message", result.model_dump_json())


if __name__ == "__main__":
    unittest.main()
