from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from opspilot.adapters.investigation_contract import (
    INVESTIGATION_INSTRUCTIONS,
    SUBMIT_REPORT_TOOL,
    strict_json_schema,
)
from opspilot.investigation.gateway import (
    InvestigationModelGateway,
    ModelGatewayError,
    ProviderDiagnostic,
    provider_diagnostic,
)
from opspilot.investigation.models import (
    DiagnosisReport,
    EvidenceItem,
    IncidentRequest,
    ModelTurn,
    ModelUsage,
    ToolCall,
    ToolTrace,
)
from opspilot.tools.base import ToolSpec

_CALL_ID = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")
_SUPPORTED_SCHEMA_KEYS = {
    "additionalProperties",
    "anyOf",
    "description",
    "enum",
    "format",
    "items",
    "maxItems",
    "maximum",
    "minItems",
    "minimum",
    "oneOf",
    "properties",
    "required",
    "title",
    "type",
}


def _gemini_json_schema(schema: Mapping[str, object]) -> dict[str, object]:
    """Inline local definitions and retain Gemini's documented schema subset."""

    strict = strict_json_schema(schema)
    definitions = strict.get("$defs", {})
    if not isinstance(definitions, dict):
        definitions = {}

    def convert(node: object, refs: tuple[str, ...] = ()) -> object:
        if isinstance(node, list):
            return [convert(value, refs) for value in node]
        if not isinstance(node, dict):
            return node

        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.removeprefix("#/$defs/")
            target = definitions.get(name)
            if not isinstance(target, dict) or name in refs:
                raise ValueError("Gemini function schema contains an invalid reference")
            siblings = {key: value for key, value in node.items() if key != "$ref"}
            merged = {**target, **siblings}
            return convert(merged, (*refs, name))

        converted: dict[str, object] = {}
        for key, value in node.items():
            if key not in _SUPPORTED_SCHEMA_KEYS:
                continue
            if key == "properties" and isinstance(value, dict):
                converted[key] = {
                    name: convert(property_schema, refs)
                    for name, property_schema in value.items()
                }
            else:
                converted[key] = convert(value, refs)
        return converted

    normalized = convert(strict)
    if not isinstance(normalized, dict):
        raise ValueError("Gemini function schema must be an object")
    return cast(dict[str, object], normalized)


class GeminiInvestigationGateway(InvestigationModelGateway):
    """Native Google Gen AI adapter for the provider-independent investigator."""

    def __init__(
        self,
        model: str,
        *,
        timeout_seconds: float = 30.0,
        max_output_tokens: int = 4_096,
        reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None,
        client: object | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("timeout must be between 0 and 120 seconds")
        if max_output_tokens < 256 or max_output_tokens > 32_768:
            raise ValueError("max output tokens must be between 256 and 32768")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self._client = client

    def next_turn(
        self,
        request: IncidentRequest,
        *,
        evidence: Sequence[EvidenceItem],
        trace: Sequence[ToolTrace],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn:
        client = self._get_client()
        declarations = [self._tool_declaration(tool) for tool in tools]
        declarations.append(
            {
                "name": SUBMIT_REPORT_TOOL,
                "description": "Submit the final structured, evidence-cited incident report.",
                "parameters_json_schema": _gemini_json_schema(
                    DiagnosisReport.model_json_schema()
                ),
            }
        )
        allowed_names = [str(item["name"]) for item in declarations]
        state = {
            "incident": request.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "tool_trace": [item.model_dump(mode="json") for item in trace],
        }
        config: dict[str, object] = {
            "system_instruction": INVESTIGATION_INSTRUCTIONS,
            "temperature": 0,
            "max_output_tokens": self._max_output_tokens,
            "tools": [{"function_declarations": declarations}],
            "automatic_function_calling": {"disable": True},
            "tool_config": {
                "function_calling_config": {
                    "mode": "ANY",
                    "allowed_function_names": allowed_names,
                }
            },
        }
        if self._reasoning_effort is not None:
            config["thinking_config"] = {"thinking_level": self._reasoning_effort}

        try:
            response = cast(Any, client).models.generate_content(
                model=self._model,
                contents=json.dumps(state, sort_keys=True),
                config=config,
            )
        except Exception as exc:
            raise ModelGatewayError(
                "Gemini generate-content request failed",
                diagnostic=provider_diagnostic("gemini", exc),
            ) from exc

        turn = self._parse_response(response)
        usage = self._parse_usage(response, fallback_model=self._model)
        return turn.model_copy(update={"usage": usage})

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ModelGatewayError(
                "Gemini client is not configured",
                diagnostic=ProviderDiagnostic(
                    provider="gemini",
                    error_type="ConfigurationError",
                    error_code="missing_api_key",
                ),
            )
        try:
            genai = importlib.import_module("google.genai")
            client_type = genai.Client
            self._client = client_type(
                api_key=api_key,
                http_options={
                    "timeout": round(self._timeout_seconds * 1_000),
                    "retry_options": {"attempts": 1},
                },
            )
        except (ImportError, AttributeError) as exc:
            raise ModelGatewayError(
                "Google Gen AI SDK is unavailable",
                diagnostic=ProviderDiagnostic(
                    provider="gemini",
                    error_type=type(exc).__name__,
                    error_code="sdk_unavailable",
                ),
            ) from exc
        except Exception as exc:
            raise ModelGatewayError(
                "Gemini client could not be created",
                diagnostic=provider_diagnostic("gemini", exc),
            ) from exc
        return self._client

    @staticmethod
    def _tool_declaration(tool: ToolSpec) -> dict[str, object]:
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters_json_schema": _gemini_json_schema(tool.input_schema),
        }

    @classmethod
    def _parse_response(cls, response: object) -> ModelTurn:
        raw_calls = getattr(response, "function_calls", None)
        if not isinstance(raw_calls, list) or not raw_calls:
            raise ModelGatewayError("Gemini response contained no function calls")

        calls: list[ToolCall] = []
        report: DiagnosisReport | None = None
        for index, raw_call in enumerate(raw_calls):
            name = getattr(raw_call, "name", None)
            arguments = getattr(raw_call, "args", None)
            if not isinstance(name, str) or not isinstance(arguments, Mapping):
                raise ModelGatewayError("Gemini returned an invalid function call")
            parsed_arguments = dict(arguments)
            call_id = cls._call_id(raw_call, name, parsed_arguments, index)

            if name == SUBMIT_REPORT_TOOL:
                if calls or report is not None:
                    raise ModelGatewayError("Gemini mixed a final report with other calls")
                try:
                    report = DiagnosisReport.model_validate(parsed_arguments)
                except ValueError as exc:
                    raise ModelGatewayError("Gemini returned an invalid incident report") from exc
            else:
                if report is not None:
                    raise ModelGatewayError("Gemini mixed a final report with other calls")
                calls.append(
                    ToolCall(
                        call_id=call_id,
                        name=name,
                        arguments=parsed_arguments,
                    )
                )

        try:
            return ModelTurn(tool_calls=calls, report=report)
        except ValueError as exc:
            raise ModelGatewayError("Gemini returned no actionable function call") from exc

    @staticmethod
    def _call_id(
        raw_call: object,
        name: str,
        arguments: Mapping[str, object],
        index: int,
    ) -> str:
        provider_id = getattr(raw_call, "id", None)
        if isinstance(provider_id, str) and _CALL_ID.fullmatch(provider_id):
            return provider_id
        try:
            canonical = json.dumps(
                {"name": name, "arguments": arguments, "index": index},
                sort_keys=True,
                separators=(",", ":"),
            )
        except TypeError as exc:
            raise ModelGatewayError("Gemini returned non-JSON function arguments") from exc
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
        return f"gemini-{digest}"

    @staticmethod
    def _parse_usage(response: object, *, fallback_model: str) -> ModelUsage | None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None

        def read_int(name: str) -> int:
            value = (
                usage.get(name, 0)
                if isinstance(usage, Mapping)
                else getattr(usage, name, 0)
            )
            return value if isinstance(value, int) and value >= 0 else 0

        input_tokens = read_int("prompt_token_count") + read_int(
            "tool_use_prompt_token_count"
        )
        cached_input_tokens = read_int("cached_content_token_count")
        candidate_tokens = read_int("candidates_token_count")
        reasoning_tokens = read_int("thoughts_token_count")
        provider_total = read_int("total_token_count")
        output_tokens = (
            provider_total - input_tokens
            if provider_total >= input_tokens and provider_total > 0
            else candidate_tokens + reasoning_tokens
        )
        total_tokens = input_tokens + output_tokens
        model = getattr(response, "model_version", fallback_model)
        if not isinstance(model, str) or not model.strip():
            model = fallback_model
        try:
            return ModelUsage(
                model=model,
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
                total_tokens=total_tokens,
            )
        except ValueError as exc:
            raise ModelGatewayError("Gemini returned invalid usage accounting") from exc
