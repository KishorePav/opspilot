from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Confidence = Literal["low", "medium", "high"]
InvestigationStatus = Literal["diagnosed", "insufficient_evidence"]
EvidenceKind = Literal["runbook", "log", "deployment", "metric"]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelUsage(DomainModel):
    model: str = Field(min_length=1, max_length=160)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_token_accounting(self) -> ModelUsage:
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached input tokens cannot exceed input tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning tokens cannot exceed output tokens")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total tokens must equal input plus output tokens")
        return self


class UsageSummary(DomainModel):
    model_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal | None
    pricing_version: str | None


class IncidentRequest(DomainModel):
    incident_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{3,96}$")
    summary: str = Field(min_length=3, max_length=2_000)
    environment: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    started_at: datetime
    ended_at: datetime
    services: list[str] = Field(min_length=1, max_length=10)

    @field_validator("started_at", "ended_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("incident timestamps must include a timezone")
        return value

    @field_validator("services")
    @classmethod
    def validate_services(cls, services: list[str]) -> list[str]:
        normalized = [service.strip() for service in services]
        if any(not service or len(service) > 128 for service in normalized):
            raise ValueError("services must contain 1 to 128 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("services must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_window(self) -> IncidentRequest:
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at must be after started_at")
        if self.ended_at - self.started_at > timedelta(hours=24):
            raise ValueError("investigation window cannot exceed 24 hours")
        return self


class EvidenceItem(DomainModel):
    evidence_id: str = Field(pattern=r"^[a-z]+:[a-zA-Z0-9_.:-]{3,160}$")
    kind: EvidenceKind
    title: str = Field(min_length=1, max_length=300)
    source: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=6_000)
    occurred_at: datetime | None
    metadata: dict[str, str]

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, metadata: dict[str, str]) -> dict[str, str]:
        if len(metadata) > 20:
            raise ValueError("evidence metadata cannot exceed 20 entries")
        if any(not key or len(key) > 64 for key in metadata):
            raise ValueError("evidence metadata keys must contain 1 to 64 characters")
        if any(len(value) > 500 for value in metadata.values()):
            raise ValueError("evidence metadata values cannot exceed 500 characters")
        return metadata


class ToolCall(DomainModel):
    call_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,128}$")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    arguments: dict[str, object]


class CitedClaim(DomainModel):
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class TimelineEvent(DomainModel):
    occurred_at: datetime
    description: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class RankedHypothesis(DomainModel):
    rank: int = Field(ge=1, le=10)
    statement: str = Field(min_length=1, max_length=2_000)
    confidence: Confidence
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class NextAction(DomainModel):
    description: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class DiagnosisReport(DomainModel):
    incident_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{3,96}$")
    status: InvestigationStatus
    affected_services: list[str] = Field(max_length=20)
    summary: str = Field(min_length=1, max_length=2_000)
    timeline: list[TimelineEvent] = Field(max_length=100)
    hypotheses: list[RankedHypothesis] = Field(max_length=10)
    probable_root_cause: CitedClaim | None
    confidence: Confidence
    next_actions: list[NextAction] = Field(max_length=20)
    unanswered_questions: list[str] = Field(max_length=20)

    @field_validator("affected_services")
    @classmethod
    def validate_affected_services(cls, services: list[str]) -> list[str]:
        if len(services) != len(set(services)):
            raise ValueError("affected services must be unique")
        return services

    @field_validator("unanswered_questions")
    @classmethod
    def validate_unanswered_questions(cls, questions: list[str]) -> list[str]:
        if any(not question.strip() or len(question) > 1_000 for question in questions):
            raise ValueError("unanswered questions must contain 1 to 1000 characters")
        return questions

    @model_validator(mode="after")
    def validate_status_contract(self) -> DiagnosisReport:
        ranks = [hypothesis.rank for hypothesis in self.hypotheses]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("hypothesis ranks must be contiguous and start at 1")
        if [event.occurred_at for event in self.timeline] != sorted(
            event.occurred_at for event in self.timeline
        ):
            raise ValueError("timeline events must be chronological")
        if self.status == "diagnosed":
            if self.probable_root_cause is None:
                raise ValueError("a diagnosed report requires a probable root cause")
            if not self.hypotheses:
                raise ValueError("a diagnosed report requires at least one hypothesis")
        if self.status == "insufficient_evidence":
            if self.probable_root_cause is not None:
                raise ValueError("insufficient evidence cannot assert a probable root cause")
            if not self.unanswered_questions:
                raise ValueError("insufficient evidence requires unanswered questions")
        return self


class ModelTurn(DomainModel):
    tool_calls: list[ToolCall] = Field(max_length=3)
    report: DiagnosisReport | None
    usage: ModelUsage | None = None

    @model_validator(mode="after")
    def validate_exactly_one_action(self) -> ModelTurn:
        if bool(self.tool_calls) == (self.report is not None):
            raise ValueError("a model turn must contain tool calls or one report")
        return self


class ToolTrace(DomainModel):
    round_number: int = Field(ge=1)
    call_id: str
    tool_name: str
    status: Literal["succeeded", "failed"]
    evidence_ids: list[str]
    error_code: str | None


class InvestigationResult(DomainModel):
    report: DiagnosisReport
    evidence: list[EvidenceItem]
    trace: list[ToolTrace]
    usage: UsageSummary
