import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from time import perf_counter
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from opspilot.auth import AuthenticationError, Authenticator, Principal, Role
from opspilot.bootstrap import (
    build_authenticator,
    build_investigator,
    build_retriever,
    build_telemetry,
    build_workflow_service,
)
from opspilot.config import Settings
from opspilot.investigation.failures import InvestigationFailedError
from opspilot.investigation.models import IncidentRequest, InvestigationResult
from opspilot.investigation.orchestrator import IncidentInvestigator
from opspilot.observability import Observability
from opspilot.retrieval.base import (
    ClosableRetriever,
    EvidenceRetriever,
    RetrievalUnavailableError,
)
from opspilot.workflow.failures import WorkflowError
from opspilot.workflow.models import (
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


class ProposalRequest(BaseModel):
    action: RemediationAction


class ProposalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    expected_plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=3, max_length=1_000)


class ExecutionRequest(BaseModel):
    idempotency_key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{8,128}$")


class AuditResponse(BaseModel):
    run_id: str
    verified: Literal[True] = True
    events: list[AuditEvent]


_bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def get_observability() -> Observability:
    return build_telemetry(Settings.from_environment())


@lru_cache(maxsize=1)
def get_authenticator() -> Authenticator:
    return build_authenticator(Settings.from_environment())


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    authenticator: Annotated[Authenticator, Depends(get_authenticator)],
    observability: Annotated[Observability, Depends(get_observability)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        observability.record_auth(outcome="denied", reason="missing_token")
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message": "A bearer token is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return authenticator.authenticate(credentials.credentials)
    except AuthenticationError as exc:
        observability.record_auth(outcome="denied", reason="invalid_token")
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_token", "message": "The bearer token is invalid."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


class RoleAuthorizer:
    def __init__(self, required: frozenset[Role]) -> None:
        self._required = required

    def __call__(
        self,
        principal: Annotated[Principal, Depends(get_principal)],
        observability: Annotated[Observability, Depends(get_observability)],
    ) -> Principal:
        if not principal.has_any_role(self._required):
            observability.record_auth(outcome="denied", reason="insufficient_role")
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "The token lacks the required role."},
            )
        observability.record_auth(outcome="allowed", reason="role_authorized")
        return principal


def require_roles(*roles: Role) -> RoleAuthorizer:
    return RoleAuthorizer(frozenset(roles))


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
    return build_workflow_service(settings, get_investigator(), get_observability())


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
    get_authenticator.cache_clear()
    if get_observability.cache_info().currsize:
        get_observability().shutdown()
        get_observability.cache_clear()


def create_app() -> FastAPI:
    app = FastAPI(title="OpsPilot Investigation API", version="0.8.0", lifespan=_lifespan)

    investigator_access = require_roles("investigator")
    workflow_read_access = require_roles(
        "investigator",
        "remediation_proposer",
        "remediation_approver",
        "remediation_executor",
        "auditor",
    )
    proposer_access = require_roles("remediation_proposer")
    approver_access = require_roles("remediation_approver")
    executor_access = require_roles("remediation_executor")
    auditor_access = require_roles("auditor")

    @app.middleware("http")
    async def record_http_telemetry(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route_object = request.scope.get("route")
            route = getattr(route_object, "path", "unmatched")
            get_observability().record_http(
                route=str(route),
                method=request.method,
                status_code=status_code,
                duration=perf_counter() - started,
            )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/livez")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readiness(
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> dict[str, str]:
        settings = Settings.from_environment()
        auth_configured = bool(
            settings.auth_jwks_url and settings.auth_issuer and settings.auth_audience
        )
        if not auth_configured or not workflow.is_ready():
            raise HTTPException(status_code=503, detail="not ready")
        return {"status": "ready"}

    @app.post("/v1/retrieve", response_model=RetrievalResponse)
    def retrieve(
        request: RetrievalRequest,
        principal: Annotated[Principal, Depends(investigator_access)],
    ) -> RetrievalResponse:
        del principal
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
        principal: Annotated[Principal, Depends(investigator_access)],
        investigator: Annotated[IncidentInvestigator, Depends(get_investigator)],
    ) -> InvestigationResult:
        del principal
        try:
            return investigator.investigate(request)
        except InvestigationFailedError as exc:
            raise HTTPException(status_code=503, detail=exc.public_detail()) from exc

    @app.post("/v1/investigations", response_model=InvestigationRun, status_code=201)
    def create_durable_investigation(
        request: DurableInvestigationRequest,
        principal: Annotated[Principal, Depends(investigator_access)],
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> InvestigationRun:
        try:
            return workflow.create_investigation(
                request.incident,
                created_by=principal.actor(),
                tenant_id=principal.tenant_id,
            )
        except WorkflowError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc

    @app.get("/v1/investigations/{run_id}", response_model=InvestigationRun)
    def get_durable_investigation(
        run_id: str,
        principal: Annotated[Principal, Depends(workflow_read_access)],
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> InvestigationRun:
        try:
            return workflow.get_investigation(run_id, tenant_id=principal.tenant_id)
        except WorkflowError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc

    @app.post(
        "/v1/investigations/{run_id}/remediation-proposals",
        response_model=RemediationProposal,
        status_code=201,
    )
    def create_remediation_proposal(
        run_id: str,
        request: ProposalRequest,
        principal: Annotated[Principal, Depends(proposer_access)],
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> RemediationProposal:
        try:
            return workflow.create_proposal(
                run_id,
                request.action,
                created_by=principal.actor(),
                tenant_id=principal.tenant_id,
            )
        except WorkflowError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc

    @app.post(
        "/v1/remediation-proposals/{proposal_id}/decisions",
        response_model=RemediationProposal,
    )
    def decide_remediation_proposal(
        proposal_id: str,
        request: ProposalDecisionRequest,
        principal: Annotated[Principal, Depends(approver_access)],
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> RemediationProposal:
        try:
            return workflow.decide_proposal(
                proposal_id,
                decision=request.decision,
                expected_plan_digest=request.expected_plan_digest,
                decided_by=principal.actor(),
                reason=request.reason,
                tenant_id=principal.tenant_id,
            )
        except WorkflowError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc

    @app.post(
        "/v1/remediation-proposals/{proposal_id}/executions",
        response_model=RemediationExecution,
    )
    def execute_remediation_proposal(
        proposal_id: str,
        request: ExecutionRequest,
        principal: Annotated[Principal, Depends(executor_access)],
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> RemediationExecution:
        try:
            return workflow.execute_proposal(
                proposal_id,
                idempotency_key=request.idempotency_key,
                requested_by=principal.actor(),
                tenant_id=principal.tenant_id,
            )
        except WorkflowError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc

    @app.get("/v1/investigations/{run_id}/audit-events", response_model=AuditResponse)
    def investigation_audit_events(
        run_id: str,
        principal: Annotated[Principal, Depends(auditor_access)],
        workflow: Annotated[RemediationWorkflowService, Depends(get_workflow_service)],
    ) -> AuditResponse:
        try:
            return AuditResponse(
                run_id=run_id,
                events=workflow.audit_events(run_id, tenant_id=principal.tenant_id),
            )
        except WorkflowError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.public_detail()) from exc

    return app
