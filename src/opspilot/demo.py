from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from opspilot.corpus import load_markdown_documents
from opspilot.evaluation.agent import AgentEvalCase, ReplayGateway, load_agent_eval_cases
from opspilot.investigation.models import IncidentRequest, InvestigationResult
from opspilot.investigation.orchestrator import IncidentInvestigator
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.retrieval.service import HybridRetriever
from opspilot.tools.base import ReadOnlyTool
from opspilot.tools.operational import OperationalFixtureStore, build_operational_tools
from opspilot.tools.retrieval import RunbookSearchTool

_ALLOWED_SCENARIOS = frozenset({"dataflow-diagnosis-with-injection-present"})
_UI_PATH = Path(__file__).with_name("demo_ui") / "index.html"


class DemoModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DemoScenario(DemoModel):
    scenario_id: str
    title: str
    description: str
    incident: IncidentRequest


class DemoRun(DemoModel):
    scenario: DemoScenario
    result: InvestigationResult
    safety_controls: list[str]


def _scenario(case: AgentEvalCase) -> DemoScenario:
    return DemoScenario(
        scenario_id=case.case_id,
        title="Dataflow worker launch failure",
        description=case.description,
        incident=case.request,
    )


def _build_tools(corpus_path: Path, operations_path: Path) -> list[ReadOnlyTool]:
    retriever = HybridRetriever(HashEmbeddingProvider())
    retriever.index_documents(load_markdown_documents(corpus_path))
    store = OperationalFixtureStore.from_path(operations_path)
    return [RunbookSearchTool(retriever), *build_operational_tools(store)]


def create_demo_app(
    *,
    dataset_path: Path = Path("evals/investigation_cases.jsonl"),
    corpus_path: Path = Path("fixtures/runbooks"),
    operations_path: Path = Path("fixtures/operations/dataflow-permission-denied.json"),
) -> FastAPI:
    cases = {
        case.case_id: case
        for case in load_agent_eval_cases(dataset_path)
        if case.case_id in _ALLOWED_SCENARIOS
    }
    if set(cases) != set(_ALLOWED_SCENARIOS):
        raise RuntimeError("the allowlisted demo scenario is missing")
    tools = _build_tools(corpus_path, operations_path)
    html = _UI_PATH.read_text(encoding="utf-8")

    app = FastAPI(
        title="OpsPilot Synthetic Demo",
        version="0.8.0",
        description=(
            "Credential-free, read-only replay of one allowlisted synthetic incident. "
            "This application exposes no arbitrary prompt or remediation endpoint."
        ),
    )

    @app.middleware("http")
    async def add_browser_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return html

    @app.get("/livez")
    def liveness() -> dict[str, str]:
        return {"status": "ok", "mode": "synthetic-demo"}

    @app.get("/api/scenarios", response_model=list[DemoScenario])
    def scenarios() -> list[DemoScenario]:
        return [_scenario(case) for case in cases.values()]

    @app.post("/api/scenarios/{scenario_id}/investigate", response_model=DemoRun)
    def investigate(scenario_id: str) -> DemoRun:
        case = cases.get(scenario_id)
        if case is None:
            raise HTTPException(status_code=404, detail="demo scenario not found")
        investigator = IncidentInvestigator(
            ReplayGateway(case.turns),
            tools,
            max_rounds=case.budgets.max_rounds,
            max_tool_calls=case.budgets.max_tool_calls,
            max_evidence_items=case.budgets.max_evidence_items,
            max_total_tokens=case.budgets.max_total_tokens,
            pricing=case.pricing.to_policy() if case.pricing is not None else None,
        )
        result = investigator.investigate(case.request)
        return DemoRun(
            scenario=_scenario(case),
            result=result,
            safety_controls=[
                "allowlisted synthetic scenario",
                "read-only typed tools",
                "evidence-ledger citation validation",
                "prompt-injection payload treated as data",
                "no model, database, credential, or remediation access",
            ],
        )

    return app


app = create_demo_app()
