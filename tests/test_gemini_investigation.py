from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import cast

from opspilot.adapters.gemini_investigation import GeminiInvestigationGateway
from opspilot.investigation.gateway import ModelGatewayError
from opspilot.investigation.models import IncidentRequest
from opspilot.tools.base import ToolSpec


class FakeModels:
    def __init__(self, function_calls: list[SimpleNamespace]) -> None:
        self.function_calls = function_calls
        self.arguments: dict[str, object] | None = None

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: object,
    ) -> SimpleNamespace:
        self.arguments = {"model": model, "contents": contents, "config": config}
        return SimpleNamespace(
            model_version="models/gemini-3.6-flash-001",
            function_calls=self.function_calls,
            usage_metadata=SimpleNamespace(
                prompt_token_count=120,
                tool_use_prompt_token_count=5,
                cached_content_token_count=20,
                candidates_token_count=30,
                thoughts_token_count=10,
                total_token_count=165,
            ),
        )


class FakeClient:
    def __init__(self, function_calls: list[SimpleNamespace]) -> None:
        self.models = FakeModels(function_calls)


class FakeProviderError(RuntimeError):
    code = 429
    status = "RESOURCE_EXHAUSTED"
    response = SimpleNamespace(headers={"x-goog-request-id": "google-request-123"})


class FailingModels:
    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: object,
    ) -> SimpleNamespace:
        del model, contents, config
        raise FakeProviderError("secret-bearing provider message must not be retained")


class FailingClient:
    def __init__(self) -> None:
        self.models = FailingModels()


def _request() -> IncidentRequest:
    return IncidentRequest(
        incident_id="inc-dataflow-042",
        summary="Workers cannot start",
        environment="synthetic",
        started_at=datetime.fromisoformat("2026-08-01T10:00:00+00:00"),
        ended_at=datetime.fromisoformat("2026-08-01T10:15:00+00:00"),
        services=["dataflow-worker"],
    )


class GeminiInvestigationGatewayTests(unittest.TestCase):
    def assert_supported_schema(self, node: object) -> None:
        if isinstance(node, dict):
            self.assertNotIn("$defs", node)
            self.assertNotIn("$ref", node)
            self.assertNotIn("pattern", node)
            self.assertNotIn("maxLength", node)
            for value in node.values():
                self.assert_supported_schema(value)
        elif isinstance(node, list):
            for value in node:
                self.assert_supported_schema(value)

    def test_native_adapter_forces_manual_bounded_function_calls(self) -> None:
        client = FakeClient(
            [
                SimpleNamespace(
                    name="search_logs",
                    id=None,
                    args={"service": "dataflow-worker", "environment": "synthetic"},
                )
            ]
        )
        gateway = GeminiInvestigationGateway(
            "gemini-3.6-flash",
            max_output_tokens=2_048,
            reasoning_effort="low",
            client=client,
        )
        tool = ToolSpec(
            name="search_logs",
            description="Search logs",
            input_schema={
                "type": "object",
                "properties": {
                    "service": {"type": "string", "minLength": 1},
                    "environment": {"type": "string", "pattern": "^[a-z]+$"},
                },
            },
        )

        turn = gateway.next_turn(_request(), evidence=[], trace=[], tools=[tool])

        self.assertEqual("search_logs", turn.tool_calls[0].name)
        self.assertRegex(turn.tool_calls[0].call_id, r"^gemini-[a-f0-9]{20}$")
        assert turn.usage is not None
        self.assertEqual(125, turn.usage.input_tokens)
        self.assertEqual(165, turn.usage.total_tokens)
        self.assertEqual(40, turn.usage.output_tokens)
        self.assertEqual(10, turn.usage.reasoning_tokens)
        assert client.models.arguments is not None
        config = cast(dict[str, object], client.models.arguments["config"])
        self.assertEqual(2_048, config["max_output_tokens"])
        self.assertEqual({"disable": True}, config["automatic_function_calling"])
        self.assertEqual({"thinking_level": "low"}, config["thinking_config"])
        tool_config = cast(dict[str, object], config["tool_config"])
        function_config = cast(
            dict[str, object], tool_config["function_calling_config"]
        )
        self.assertEqual("ANY", function_config["mode"])
        definitions = cast(
            list[dict[str, object]],
            cast(list[dict[str, object]], config["tools"])[0][
                "function_declarations"
            ],
        )
        self.assertEqual(
            ["search_logs", "submit_incident_report"],
            [definition["name"] for definition in definitions],
        )
        for definition in definitions:
            self.assert_supported_schema(definition["parameters_json_schema"])

    def test_provider_failure_retains_only_safe_diagnostics(self) -> None:
        gateway = GeminiInvestigationGateway(
            "gemini-3.6-flash",
            client=FailingClient(),
        )

        with self.assertRaises(ModelGatewayError) as raised:
            gateway.next_turn(_request(), evidence=[], trace=[], tools=[])

        diagnostic = raised.exception.diagnostic
        assert diagnostic is not None
        self.assertEqual("gemini", diagnostic.provider)
        self.assertEqual("FakeProviderError", diagnostic.error_type)
        self.assertEqual("RESOURCE_EXHAUSTED", diagnostic.error_code)
        self.assertEqual(429, diagnostic.http_status)
        self.assertEqual("google-request-123", diagnostic.request_id)
        self.assertNotIn("secret-bearing", repr(diagnostic))


if __name__ == "__main__":
    unittest.main()
