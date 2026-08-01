from __future__ import annotations

from datetime import timedelta

from opspilot.adapters.gemini_investigation import GeminiInvestigationGateway
from opspilot.adapters.openai_investigation import (
    DisabledInvestigationGateway,
    OpenAIInvestigationGateway,
)
from opspilot.adapters.postgres import PostgresHybridRetriever
from opspilot.adapters.postgres_workflow import PostgresWorkflowStore
from opspilot.adapters.synthetic_remediation import SyntheticRemediationExecutor
from opspilot.auth import Authenticator, JWKSAuthenticator
from opspilot.config import Settings
from opspilot.corpus import load_markdown_documents
from opspilot.investigation.gateway import InvestigationModelGateway
from opspilot.investigation.orchestrator import IncidentInvestigator
from opspilot.investigation.usage import PricingPolicy
from opspilot.observability import Observability, build_observability
from opspilot.retrieval.base import EvidenceRetriever
from opspilot.retrieval.embedding import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from opspilot.retrieval.service import HybridRetriever
from opspilot.tools.base import ReadOnlyTool
from opspilot.tools.operational import OperationalFixtureStore, build_operational_tools
from opspilot.tools.retrieval import RunbookSearchTool
from opspilot.workflow.service import RemediationWorkflowService


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
    if settings.embedding_provider == "hash":
        return HashEmbeddingProvider(dimensions=settings.embedding_dimensions)
    raise RuntimeError(f"unsupported embedding provider: {settings.embedding_provider}")


def build_retriever(settings: Settings) -> EvidenceRetriever:
    embedder = build_embedding_provider(settings)
    if settings.retrieval_backend == "postgres":
        return PostgresHybridRetriever(
            settings.database_url,
            embedder,
            pool_min_size=settings.database_pool_min_size,
            pool_max_size=settings.database_pool_max_size,
        )

    retriever = HybridRetriever(embedder)
    documents = load_markdown_documents(settings.corpus_dir)
    if not documents:
        raise RuntimeError(f"no Markdown documents found in {settings.corpus_dir}")
    retriever.index_documents(documents)
    return retriever


def build_investigator(
    settings: Settings,
    retriever: EvidenceRetriever,
) -> IncidentInvestigator:
    if settings.investigation_provider == "openai":
        gateway: InvestigationModelGateway = OpenAIInvestigationGateway(
            settings.investigation_model,
            timeout_seconds=settings.investigation_timeout_seconds,
            max_output_tokens=settings.investigation_max_output_tokens,
            reasoning_effort=settings.investigation_reasoning_effort,
        )
    elif settings.investigation_provider == "gemini":
        gateway = GeminiInvestigationGateway(
            settings.investigation_model,
            timeout_seconds=settings.investigation_timeout_seconds,
            max_output_tokens=settings.investigation_max_output_tokens,
            reasoning_effort=settings.investigation_reasoning_effort,
        )
    else:
        gateway = DisabledInvestigationGateway()

    store = OperationalFixtureStore.from_path(settings.operational_fixture_path)
    tools: list[ReadOnlyTool] = [
        RunbookSearchTool(retriever),
        *build_operational_tools(store),
    ]
    pricing = None
    if settings.input_usd_per_million is not None:
        assert settings.cached_input_usd_per_million is not None
        assert settings.output_usd_per_million is not None
        assert settings.pricing_version is not None
        pricing = PricingPolicy(
            model=settings.investigation_model,
            version=settings.pricing_version,
            input_usd_per_million=settings.input_usd_per_million,
            cached_input_usd_per_million=settings.cached_input_usd_per_million,
            output_usd_per_million=settings.output_usd_per_million,
        )
    return IncidentInvestigator(
        gateway,
        tools,
        max_rounds=settings.investigation_max_rounds,
        max_tool_calls=settings.investigation_max_tool_calls,
        max_evidence_items=settings.investigation_max_evidence_items,
        max_total_tokens=settings.investigation_max_total_tokens,
        pricing=pricing,
    )


def build_workflow_service(
    settings: Settings,
    investigator: IncidentInvestigator,
    observability: Observability,
) -> RemediationWorkflowService:
    store = PostgresWorkflowStore(
        settings.database_url,
        pool_min_size=settings.database_pool_min_size,
        pool_max_size=settings.database_pool_max_size,
    )
    return RemediationWorkflowService(
        investigator,
        store,
        SyntheticRemediationExecutor(),
        approval_ttl=timedelta(seconds=settings.approval_ttl_seconds),
        execution_lease_ttl=timedelta(seconds=settings.execution_lease_ttl_seconds),
        worker_id=settings.worker_id,
        observability=observability,
    )


def build_authenticator(settings: Settings) -> Authenticator:
    if not settings.auth_jwks_url or not settings.auth_issuer or not settings.auth_audience:
        raise RuntimeError("OIDC authentication is not configured")
    return JWKSAuthenticator(
        jwks_url=settings.auth_jwks_url,
        issuer=settings.auth_issuer,
        audience=settings.auth_audience,
    )


def build_telemetry(settings: Settings) -> Observability:
    return build_observability(
        exporter=settings.telemetry_exporter,
        endpoint=settings.otlp_endpoint,
        service_version="0.8.0",
        environment=settings.environment,
    )
