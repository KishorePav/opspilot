from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from opspilot.corpus import load_markdown_documents
from opspilot.evaluation.agent import AgentEvaluator, ReplayGateway, load_agent_eval_cases
from opspilot.evaluation.live import (
    dataset_sha256,
    load_live_eval_cases,
    load_live_thresholds,
    pricing_from_values,
    replay_case_as_live,
)
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.retrieval.service import HybridRetriever
from opspilot.tools.base import ReadOnlyTool
from opspilot.tools.operational import OperationalFixtureStore, build_operational_tools
from opspilot.tools.retrieval import RunbookSearchTool

_LIVE_DATASET = Path("evals/live_investigation_cases.jsonl")


class LiveEvaluationTests(unittest.TestCase):
    def test_live_dataset_is_versioned_bounded_and_hashable(self) -> None:
        cases = load_live_eval_cases(_LIVE_DATASET)
        thresholds = load_live_thresholds(Path("evals/live_thresholds.json"))

        self.assertEqual(2, len(cases))
        self.assertEqual("live-synthetic-v1", thresholds.dataset_version)
        self.assertTrue(all(case.budgets.max_total_tokens <= 12_000 for case in cases))
        self.assertRegex(dataset_sha256(_LIVE_DATASET), r"^[a-f0-9]{64}$")

    def test_replay_gateway_can_grade_through_the_live_boundary(self) -> None:
        replay = load_agent_eval_cases(Path("evals/investigation_cases.jsonl"))[0]
        live = replay_case_as_live(replay)
        retriever = HybridRetriever(HashEmbeddingProvider())
        retriever.index_documents(load_markdown_documents(Path("fixtures/runbooks")))
        store = OperationalFixtureStore.from_path(
            Path("fixtures/operations/dataflow-permission-denied.json")
        )
        tools: list[ReadOnlyTool] = [
            RunbookSearchTool(retriever),
            *build_operational_tools(store),
        ]

        result = AgentEvaluator(tools).evaluate_gateway(
            case_id=live.case_id,
            request=live.request,
            expected=live.expected,
            budgets=live.budgets,
            gateway=ReplayGateway(replay.turns),
            pricing=replay.pricing,
        )

        self.assertTrue(result.passed)
        self.assertEqual("diagnosed", result.report.status if result.report else None)
        self.assertIn("replay-agent-v1", result.usage.models)

    def test_live_pricing_is_optional_but_never_partially_configured(self) -> None:
        self.assertIsNone(
            pricing_from_values(
                model="gpt-5.6",
                version=None,
                input_rate=None,
                cached_input_rate=None,
                output_rate=None,
            )
        )
        with self.assertRaisesRegex(ValueError, "all three rates"):
            pricing_from_values(
                model="gpt-5.6",
                version="provider-card-2026-08-02",
                input_rate=Decimal("1"),
                cached_input_rate=None,
                output_rate=Decimal("2"),
            )


if __name__ == "__main__":
    unittest.main()
