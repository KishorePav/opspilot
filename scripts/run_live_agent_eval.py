from __future__ import annotations

import argparse
import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from opspilot.adapters.openai_investigation import OpenAIInvestigationGateway
from opspilot.corpus import load_markdown_documents
from opspilot.evaluation.live import (
    LiveAgentEvaluationReport,
    dataset_sha256,
    enforce_live_thresholds,
    evaluate_live_cases,
    load_live_eval_cases,
    load_live_thresholds,
    pricing_from_values,
)
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.retrieval.service import HybridRetriever
from opspilot.tools.base import ReadOnlyTool
from opspilot.tools.operational import OperationalFixtureStore, build_operational_tools
from opspilot.tools.retrieval import RunbookSearchTool

_MODEL_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{1,127}$")


def _decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except ArithmeticError as exc:
        raise argparse.ArgumentTypeError("pricing rates must be decimals") from exc
    if value < 0:
        raise argparse.ArgumentTypeError("pricing rates cannot be negative")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an opt-in, budget-capped OpsPilot evaluation against the OpenAI "
            "Responses API. This command can spend API credits."
        )
    )
    parser.add_argument("--confirm-live-api", action="store_true")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/live_investigation_cases.jsonl"),
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path("evals/live_thresholds.json"),
    )
    parser.add_argument("--corpus", type=Path, default=Path("fixtures/runbooks"))
    parser.add_argument(
        "--operations",
        type=Path,
        default=Path("fixtures/operations/dataflow-permission-denied.json"),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPSPILOT_LIVE_EVAL_MODEL", "gpt-5.6"),
    )
    parser.add_argument("--max-cases", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-output-tokens", type=int, default=4_096)
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high"),
        default="low",
    )
    parser.add_argument("--pricing-version")
    parser.add_argument("--input-usd-per-million", type=_decimal)
    parser.add_argument("--cached-input-usd-per-million", type=_decimal)
    parser.add_argument("--output-usd-per-million", type=_decimal)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evaluations/live-agent-eval.json"),
    )
    return parser.parse_args()


def validate_live_execution(
    *,
    confirmed: bool,
    api_key_present: bool,
    model: str,
    max_cases: int,
) -> None:
    if not confirmed:
        raise ValueError("--confirm-live-api is required because this command spends API credits")
    if not api_key_present:
        raise ValueError("OPENAI_API_KEY is required in the runtime environment")
    if not _MODEL_NAME.fullmatch(model):
        raise ValueError("model name is invalid")
    if max_cases < 1 or max_cases > 10:
        raise ValueError("max cases must be between 1 and 10")


def main() -> None:
    args = _parse_args()
    try:
        validate_live_execution(
            confirmed=args.confirm_live_api,
            api_key_present=bool(os.getenv("OPENAI_API_KEY")),
            model=args.model,
            max_cases=args.max_cases,
        )
        pricing = pricing_from_values(
            model=args.model,
            version=args.pricing_version,
            input_rate=args.input_usd_per_million,
            cached_input_rate=args.cached_input_usd_per_million,
            output_rate=args.output_usd_per_million,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    thresholds = load_live_thresholds(args.thresholds)
    cases = load_live_eval_cases(args.dataset)[: args.max_cases]

    retriever = HybridRetriever(HashEmbeddingProvider())
    retriever.index_documents(load_markdown_documents(args.corpus))
    store = OperationalFixtureStore.from_path(args.operations)
    tools: list[ReadOnlyTool] = [
        RunbookSearchTool(retriever),
        *build_operational_tools(store),
    ]

    started = perf_counter()
    evaluation = evaluate_live_cases(
        cases,
        tools=tools,
        gateway_factory=lambda: OpenAIInvestigationGateway(
            args.model,
            timeout_seconds=args.timeout_seconds,
            max_output_tokens=args.max_output_tokens,
            reasoning_effort=args.reasoning_effort,
        ),
        dataset_version=thresholds.dataset_version,
        pricing=pricing,
    )
    report = LiveAgentEvaluationReport(
        generated_at=datetime.now(UTC),
        requested_model=args.model,
        dataset_sha256=dataset_sha256(args.dataset),
        selected_case_ids=[case.case_id for case in cases],
        duration_ms=round((perf_counter() - started) * 1_000),
        evaluation=evaluation,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    enforce_live_thresholds(evaluation, thresholds)

    summary = evaluation.summary
    print(
        "Live agent eval: "
        f"cases={summary.passed_cases}/{summary.cases} "
        f"models={','.join(summary.observed_models)} "
        f"safety={summary.safety_pass_rate:.3f} "
        f"citation_precision={summary.citation_precision:.3f} "
        f"citation_recall={summary.citation_recall:.3f} "
        f"tokens={summary.total_tokens} "
        f"estimated_cost_usd={summary.estimated_cost_usd}"
    )


if __name__ == "__main__":
    main()
