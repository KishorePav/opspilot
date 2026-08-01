from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from pydantic import Field

from opspilot.evaluation.agent import (
    AgentEvalCase,
    AgentEvaluationRegressionError,
    AgentEvaluationReport,
    AgentEvaluator,
    CaseExpectations,
    EvalModel,
    EvaluationPricing,
    InvestigatorBudgets,
    summarize_case_evaluations,
)
from opspilot.investigation.gateway import InvestigationModelGateway
from opspilot.investigation.models import IncidentRequest
from opspilot.tools.base import ReadOnlyTool


class LiveAgentEvalCase(EvalModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    description: str = Field(min_length=3, max_length=500)
    request: IncidentRequest
    budgets: InvestigatorBudgets = Field(default_factory=InvestigatorBudgets)
    expected: CaseExpectations


class LiveEvaluationThresholds(EvalModel):
    dataset_version: str
    minimum_case_pass_rate: float = Field(ge=0, le=1)
    minimum_safety_pass_rate: float = Field(ge=0, le=1)
    minimum_citation_precision: float = Field(ge=0, le=1)
    minimum_citation_recall: float = Field(ge=0, le=1)
    maximum_total_tokens: int = Field(ge=1)


class LiveAgentEvaluationReport(EvalModel):
    generated_at: datetime
    requested_model: str
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_case_ids: list[str]
    duration_ms: int = Field(ge=0)
    evaluation: AgentEvaluationReport


def _load_jsonl(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("live evaluation dataset could not be read") from exc


def load_live_eval_cases(path: Path) -> list[LiveAgentEvalCase]:
    cases: list[LiveAgentEvalCase] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(_load_jsonl(path), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            case = LiveAgentEvalCase.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"invalid live evaluation case at line {line_number}") from exc
        if case.case_id in seen_ids:
            raise ValueError(f"duplicate live evaluation case ID: {case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("live evaluation dataset is empty")
    return cases


def load_live_thresholds(path: Path) -> LiveEvaluationThresholds:
    try:
        return LiveEvaluationThresholds.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("live evaluation thresholds are invalid") from exc


def dataset_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("live evaluation dataset could not be hashed") from exc


def evaluate_live_cases(
    cases: Sequence[LiveAgentEvalCase],
    *,
    tools: Sequence[ReadOnlyTool],
    gateway_factory: Callable[[], InvestigationModelGateway],
    dataset_version: str,
    pricing: EvaluationPricing | None = None,
) -> AgentEvaluationReport:
    evaluator = AgentEvaluator(tools)
    results = []
    for case in cases:
        started = perf_counter()
        evaluation = evaluator.evaluate_gateway(
            case_id=case.case_id,
            request=case.request,
            expected=case.expected,
            budgets=case.budgets,
            gateway=gateway_factory(),
            pricing=pricing,
        )
        results.append(
            evaluation.model_copy(update={"duration_ms": round((perf_counter() - started) * 1_000)})
        )
    return summarize_case_evaluations(results, dataset_version=dataset_version)


def enforce_live_thresholds(
    report: AgentEvaluationReport,
    thresholds: LiveEvaluationThresholds,
) -> None:
    summary = report.summary
    failures: list[str] = []
    if summary.dataset_version != thresholds.dataset_version:
        failures.append("dataset_version")
    if summary.case_pass_rate < thresholds.minimum_case_pass_rate:
        failures.append("case_pass_rate")
    if summary.safety_pass_rate < thresholds.minimum_safety_pass_rate:
        failures.append("safety_pass_rate")
    if summary.citation_precision < thresholds.minimum_citation_precision:
        failures.append("citation_precision")
    if summary.citation_recall < thresholds.minimum_citation_recall:
        failures.append("citation_recall")
    if summary.total_tokens > thresholds.maximum_total_tokens:
        failures.append("total_tokens")
    if failures:
        raise AgentEvaluationRegressionError(
            f"live agent evaluation thresholds failed: {', '.join(failures)}"
        )


def replay_case_as_live(case: AgentEvalCase) -> LiveAgentEvalCase:
    """Test/demo helper that removes scripted model turns from a replay case."""

    return LiveAgentEvalCase(
        case_id=case.case_id,
        description=case.description,
        request=case.request,
        budgets=case.budgets,
        expected=case.expected,
    )


def pricing_from_values(
    *,
    model: str,
    version: str | None,
    input_rate: Decimal | None,
    cached_input_rate: Decimal | None,
    output_rate: Decimal | None,
) -> EvaluationPricing | None:
    values = (input_rate, cached_input_rate, output_rate)
    configured = sum(value is not None for value in values)
    if configured == 0 and version is None:
        return None
    if configured != 3 or not version:
        raise ValueError("live pricing requires a version and all three rates")
    assert input_rate is not None
    assert cached_input_rate is not None
    assert output_rate is not None
    return EvaluationPricing(
        model=model,
        version=version,
        input_usd_per_million=input_rate,
        cached_input_usd_per_million=cached_input_rate,
        output_usd_per_million=output_rate,
    )
