from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from opspilot.bootstrap import build_investigator, build_retriever, build_workflow_service
from opspilot.config import Settings
from opspilot.investigation.failures import InvestigationFailedError
from opspilot.investigation.models import IncidentRequest, InvestigationResult
from opspilot.investigation.orchestrator import IncidentInvestigator
from opspilot.retrieval.base import (
    ClosableRetriever,
    EvidenceRetriever,
    RetrievalUnavailableError,
)
from opspilot.workflow.failures import WorkflowError
from opspilot.workflow.models import (
    Actor,
    AuditEvent,
    InvestigationRun,
    RemediationAction,
    RemediationExecution,
    RemediationProposal,
)
from opspilot.workflow.service import RemediationWorkflowService

_FILTER_KEY = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict)

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, filters: dict[str, str]) -> dict[str, str]:
        if len(filters) > 10:
            raise ValueError("no more than 10 metadata filters are allowed")
        for key, value in filters.items():
            if not _FILTER_KEY.fullmatch(key):
                raise ValueError(f"invalid metadata filter key: {key!r}")
            if not value or len(value) > 128:
                raise ValueError("metadata filter values must contain 1 to 128 characters")
        return filters


class EvidenceResponse(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    source: str
    content: str
    metadata: dict[str, str]
    score: float
    lexical_rank: int | None
    vector_rank: int | None


class RetrievalResponse(BaseModel):
    query: str
    evidence: list[EvidenceResponse]


class DurableInvestigationRequest(BaseModel):
    incident: IncidentRequest
    created_by: Actor


class ProposalRequest(BaseModel):
    action: RemediationAction
    created_by: Actor


class ProposalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    expected_plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decided_by: Actor
    reason: str = Field(min_length=3, max_length=1_000)


class ExecutionRequest(BaseModel):
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{8,128}$")
    requested_by: Actor


class AuditResponse(BaseModel):
    run_id: str
    verified: Literal[True] = True
    events: list[AuditEvent]


@lru_cache(maxsize=1)
def get_retriever() -> EvidenceRetriever:
    return build_retriever(Settings.from_environment())


@lru_cache(maxsize=1)
def get_investigator() -> IncidentInvestigator:
    settings = Settings.from_environment()
    return build_investigator(settings, get_retriever())


@lru_cache(maxsize=1)
def get_workflow_service() -> RemediationWorkflowService:
    settings = Settings.from_environment()
    return build_workflow_service(settings, get_investigator())


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    if get_workflow_service.cache_info().currsize:
        get_workflow_service().close()
        get_workflow_service.cache_clear()
    get_investigator.cache_clear()
    if get_retriever.cache_info().currsize:
        retriever = get_retriever()
        if isinstance(retriever, ClosableRetriever):
            retriever.close()
        get_retriever.cache_clear()


def create_app() -> FastAPI:
    app = FastAPI(title="OpsPilot Investigation API", version="0.5.0", lifespan=_lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/retrieve", response_model=RetrievalResponse)
    def retrieve(request: RetrievalRequest) -> RetrievalResponse:
        try:
            hits = get_retriever().search(
                request.query,
                top_k=request.top_k,
                filters=request.filters,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (RetrievalUnavailableError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        evidence = [
            EvidenceResponse(
                chunk_id=hit.chunk.chunk_id,
                document_id=hit.chunk.document_id,
                title=hit.chunk.title,
                source=hit.chunk.source,
                content=hit.chunk.content,
                metadata=dict(hit.chunk.metadata),
                score=hit.score,
                lexical_rank=hit.lexical_rank,
                vector_rank=hit.vector_rank,
            )
            for hit in hits
        ]
        return RetrievalResponse(query=request.query, evidence=evidence)

    @app.post("/v1/investigate", response_model=InvestigationResult)
    def investigate(
        request: IncidentRequest,
        investigator: Annotated[IncidentInvestigator, Depends(get_investigator)],
    ) -> InvestigationResult:
        try:
            return investigator.investigate(request)
        except InvestigationFailedError as exc:
            raise HTTPException(status_code=503, detail=exc.public_detail()) from exc

    @app.post("/v1/investigations", response_model=InvestigationRun, status_code=201)
    def create_durable_investigation(
        request: DurableInvestigationRequest,
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> InvestigationRun:
        try:
            return workflow.create_investigation(
                request.incident,
                created_by=request.created_by,
            )
        except WorkflowError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.public_detail()
            ) from exc

    @app.get("/v1/investigations/{run_id}", response_model=InvestigationRun)
    def get_durable_investigation(
        run_id: str,
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> InvestigationRun:
        try:
            return workflow.get_investigation(run_id)
        except WorkflowError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.public_detail()
            ) from exc

    @app.post(
        "/v1/investigations/{run_id}/remediation-proposals",
        response_model=RemediationProposal,
        status_code=201,
    )
    def create_remediation_proposal(
        run_id: str,
        request: ProposalRequest,
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> RemediationProposal:
        try:
            return workflow.create_proposal(
                run_id,
                request.action,
                created_by=request.created_by,
            )
        except WorkflowError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.public_detail()
            ) from exc

    @app.post(
        "/v1/remediation-proposals/{proposal_id}/decisions",
        response_model=RemediationProposal,
    )
    def decide_remediation_proposal(
        proposal_id: str,
        request: ProposalDecisionRequest,
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> RemediationProposal:
        try:
            return workflow.decide_proposal(
                proposal_id,
                decision=request.decision,
                expected_plan_digest=request.expected_plan_digest,
                decided_by=request.decided_by,
                reason=request.reason,
            )
        except WorkflowError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.public_detail()
            ) from exc

    @app.post(
        "/v1/remediation-proposals/{proposal_id}/executions",
        response_model=RemediationExecution,
    )
    def execute_remediation_proposal(
        proposal_id: str,
        request: ExecutionRequest,
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> RemediationExecution:
        try:
            return workflow.execute_proposal(
                proposal_id,
                idempotency_key=request.idempotency_key,
                requested_by=request.requested_by,
            )
        except WorkflowError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.public_detail()
            ) from exc

    @app.get("/v1/investigations/{run_id}/audit-events", response_model=AuditResponse)
    def investigation_audit_events(
        run_id: str,
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> AuditResponse:
        try:
            return AuditResponse(run_id=run_id, events=workflow.audit_events(run_id))
        except WorkflowError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.public_detail()
            ) from exc

    return app
