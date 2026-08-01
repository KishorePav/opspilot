from __future__ import annotations

import argparse
from pathlib import Path

from opspilot.corpus import load_markdown_documents
from opspilot.evaluation.agent import (
    enforce_thresholds,
    evaluate_cases,
    load_agent_eval_cases,
    load_thresholds,
)
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.retrieval.service import HybridRetriever
from opspilot.tools.base import ReadOnlyTool
from opspilot.tools.operational import OperationalFixtureStore, build_operational_tools
from opspilot.tools.retrieval import RunbookSearchTool


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay and grade the versioned OpsPilot agent evaluation dataset."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/investigation_cases.jsonl"),
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path("evals/agent_thresholds.json"),
    )
    parser.add_argument("--corpus", type=Path, default=Path("fixtures/runbooks"))
    parser.add_argument(
        "--operations",
        type=Path,
        default=Path("fixtures/operations/dataflow-permission-denied.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluations/agent-eval.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    thresholds = load_thresholds(args.thresholds)
    cases = load_agent_eval_cases(args.dataset)

    retriever = HybridRetriever(HashEmbeddingProvider())
    retriever.index_documents(load_markdown_documents(args.corpus))
    store = OperationalFixtureStore.from_path(args.operations)
    tools: list[ReadOnlyTool] = [
        RunbookSearchTool(retriever),
        *build_operational_tools(store),
    ]

    report = evaluate_cases(
        cases,
        tools=tools,
        dataset_version=thresholds.dataset_version,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    enforce_thresholds(report, thresholds)

    summary = report.summary
    print(
        "Agent eval: "
        f"cases={summary.passed_cases}/{summary.cases} "
        f"safety={summary.safety_pass_rate:.3f} "
        f"citation_precision={summary.citation_precision:.3f} "
        f"citation_recall={summary.citation_recall:.3f} "
        f"tokens={summary.total_tokens} "
        f"estimated_cost_usd={summary.estimated_cost_usd}"
    )


if __name__ == "__main__":
    main()
