from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from opspilot.investigation.failures import InvestigationFailedError
from opspilot.investigation.gateway import InvestigationModelGateway, ModelGatewayError
from opspilot.investigation.models import (
    DiagnosisReport,
    EvidenceItem,
    IncidentRequest,
    InvestigationResult,
    ModelUsage,
    ToolCall,
    ToolTrace,
    UsageSummary,
)
from opspilot.investigation.usage import PricingPolicy, summarize_usage
from opspilot.tools.base import ReadOnlyTool, ToolExecutionError


class IncidentInvestigator:
    def __init__(
        self,
        gateway: InvestigationModelGateway,
        tools: Sequence[ReadOnlyTool],
        *,
        max_rounds: int = 8,
        max_tool_calls: int = 12,
        max_evidence_items: int = 40,
        max_total_tokens: int = 20_000,
        pricing: PricingPolicy | None = None,
    ) -> None:
        if (
            max_rounds < 1
            or max_tool_calls < 1
            or max_evidence_items < 1
            or max_total_tokens < 1
        ):
            raise ValueError("investigation budgets must be positive")
        names = [tool.spec.name for tool in tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        self._gateway = gateway
        self._tools = {tool.spec.name: tool for tool in tools}
        self._max_rounds = max_rounds
        self._max_tool_calls = max_tool_calls
        self._max_evidence_items = max_evidence_items
        self._max_total_tokens = max_total_tokens
        self._pricing = pricing

    def investigate(self, request: IncidentRequest) -> InvestigationResult:
        ledger: dict[str, EvidenceItem] = {}
        trace: list[ToolTrace] = []
        usage_records: list[ModelUsage] = []
        seen_calls: set[str] = set()
        total_calls = 0
        model_calls = 0

        try:
            for round_number in range(1, self._max_rounds + 1):
                model_calls += 1
                try:
                    turn = self._gateway.next_turn(
                        request,
                        evidence=tuple(ledger.values()),
                        trace=tuple(trace),
                        tools=tuple(tool.spec for tool in self._tools.values()),
                    )
                except ModelGatewayError as exc:
                    failure = InvestigationFailedError("model_gateway_failed")
                    failure.attach_provider_diagnostic(exc.diagnostic)
                    raise failure from exc
                if turn.usage is not None:
                    usage_records.append(turn.usage)
                    if sum(item.total_tokens for item in usage_records) > self._max_total_tokens:
                        raise InvestigationFailedError("token_budget_exhausted")

                if turn.report is not None:
                    self._validate_report(request, turn.report, ledger)
                    return InvestigationResult(
                        report=turn.report,
                        evidence=list(ledger.values()),
                        trace=trace,
                        usage=self._summarize_usage(
                            usage_records,
                            model_calls=model_calls,
                        ),
                    )

                for call in turn.tool_calls:
                    total_calls += 1
                    if total_calls > self._max_tool_calls:
                        raise InvestigationFailedError("tool_call_budget_exhausted")
                    signature = self._call_signature(call)
                    if signature in seen_calls:
                        raise InvestigationFailedError("duplicate_tool_call")
                    seen_calls.add(signature)
                    self._execute_call(round_number, call, request, ledger, trace)

            raise InvestigationFailedError("investigation_round_budget_exhausted")
        except InvestigationFailedError as exc:
            try:
                failure_usage = summarize_usage(
                    usage_records,
                    model_calls=model_calls,
                    pricing=self._pricing,
                )
            except ValueError:
                failure_usage = summarize_usage(
                    usage_records,
                    model_calls=model_calls,
                    pricing=None,
                )
            exc.attach_context(
                trace=trace,
                evidence=list(ledger.values()),
                usage=failure_usage,
            )
            raise

    def _summarize_usage(
        self,
        records: Sequence[ModelUsage],
        *,
        model_calls: int,
    ) -> UsageSummary:
        try:
            return summarize_usage(
                records,
                model_calls=model_calls,
                pricing=self._pricing,
            )
        except ValueError as exc:
            raise InvestigationFailedError("pricing_policy_mismatch") from exc

    @staticmethod
    def _call_signature(call: ToolCall) -> str:
        try:
            arguments = json.dumps(call.arguments, sort_keys=True, separators=(",", ":"))
        except TypeError as exc:
            raise InvestigationFailedError("non_json_tool_arguments") from exc
        return f"{call.name}:{arguments}"

    def _execute_call(
        self,
        round_number: int,
        call: ToolCall,
        request: IncidentRequest,
        ledger: dict[str, EvidenceItem],
        trace: list[ToolTrace],
    ) -> None:
        tool = self._tools.get(call.name)
        if tool is None:
            trace.append(
                ToolTrace(
                    round_number=round_number,
                    call_id=call.call_id,
                    tool_name=call.name,
                    status="failed",
                    evidence_ids=[],
                    error_code="unknown_tool",
                )
            )
            return

        try:
            self._validate_scope(call, request)
            items = tool.execute(call.arguments)
            new_ids = {item.evidence_id for item in items} - set(ledger)
            if len(ledger) + len(new_ids) > self._max_evidence_items:
                raise InvestigationFailedError("evidence_budget_exhausted")
            for item in items:
                existing = ledger.get(item.evidence_id)
                if existing is not None and existing != item:
                    raise InvestigationFailedError("evidence_id_collision")
                ledger[item.evidence_id] = item
        except ToolExecutionError as exc:
            trace.append(
                ToolTrace(
                    round_number=round_number,
                    call_id=call.call_id,
                    tool_name=call.name,
                    status="failed",
                    evidence_ids=[],
                    error_code=exc.error_code,
                )
            )
            return

        trace.append(
            ToolTrace(
                round_number=round_number,
                call_id=call.call_id,
                tool_name=call.name,
                status="succeeded",
                evidence_ids=[item.evidence_id for item in items],
                error_code=None,
            )
        )

    @staticmethod
    def _validate_scope(call: ToolCall, request: IncidentRequest) -> None:
        environment = call.arguments.get("environment")
        if environment is not None and environment != request.environment:
            raise ToolExecutionError("scope_violation")
        service = call.arguments.get("service")
        if service is not None and service not in request.services:
            raise ToolExecutionError("scope_violation")

        for key in ("started_at", "ended_at"):
            value = call.arguments.get(key)
            if value is None:
                continue
            try:
                parsed = (
                    value
                    if isinstance(value, datetime)
                    else datetime.fromisoformat(str(value))
                )
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("tool timestamps must include a timezone")
            except ValueError as exc:
                raise ToolExecutionError("invalid_arguments") from exc
            if key == "started_at" and parsed < request.started_at:
                raise ToolExecutionError("scope_violation")
            if key == "ended_at" and parsed > request.ended_at:
                raise ToolExecutionError("scope_violation")

    @classmethod
    def _validate_report(
        cls,
        request: IncidentRequest,
        report: DiagnosisReport,
        ledger: dict[str, EvidenceItem],
    ) -> None:
        if report.incident_id != request.incident_id:
            raise InvestigationFailedError("report_incident_mismatch")
        unknown_services = set(report.affected_services) - set(request.services)
        if unknown_services:
            raise InvestigationFailedError("report_service_scope_violation")

        cited_ids = cls._report_citations(report)
        unknown_ids = cited_ids - set(ledger)
        if unknown_ids:
            raise InvestigationFailedError("report_contains_unknown_citation")
        if report.status == "diagnosed" and not cited_ids:
            raise InvestigationFailedError("diagnosis_has_no_citations")

    @staticmethod
    def _report_citations(report: DiagnosisReport) -> set[str]:
        citations = {
            evidence_id
            for event in report.timeline
            for evidence_id in event.evidence_ids
        }
        citations.update(
            evidence_id
            for hypothesis in report.hypotheses
            for evidence_id in hypothesis.evidence_ids
        )
        citations.update(
            evidence_id
            for action in report.next_actions
            for evidence_id in action.evidence_ids
        )
        if report.probable_root_cause is not None:
            citations.update(report.probable_root_cause.evidence_ids)
        return citations
