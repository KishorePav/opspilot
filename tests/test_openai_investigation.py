from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import cast

from opspilot.adapters.openai_investigation import OpenAIInvestigationGateway
from opspilot.investigation.models import IncidentRequest
from opspilot.tools.base import ToolSpec


class FakeResponses:
    def __init__(self) -> None:
        self.arguments: dict[str, object] | None = None

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.arguments = kwargs
        return SimpleNamespace(
            status="completed",
            model="gpt-5.6",
            usage=SimpleNamespace(
                input_tokens=120,
                input_tokens_details=SimpleNamespace(cached_tokens=20),
                output_tokens=30,
                output_tokens_details=SimpleNamespace(reasoning_tokens=10),
                total_tokens=150,
            ),
            output=[
                SimpleNamespace(
                    type="function_call",
                    name="search_logs",
                    call_id="call-123",
                    arguments=(
                        '{"service":"dataflow-worker","environment":"synthetic"}'
                    ),
                )
            ],
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


class OpenAIInvestigationGatewayTests(unittest.TestCase):
    def assert_strict_object_schemas(self, node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                self.assertFalse(node["additionalProperties"])
                properties = node.get("properties", {})
                self.assertEqual(list(properties), node.get("required", []))
            for value in node.values():
                self.assert_strict_object_schemas(value)
        elif isinstance(node, list):
            for value in node:
                self.assert_strict_object_schemas(value)

    def test_responses_adapter_requires_strict_function_calls(self) -> None:
        client = FakeClient()
        gateway = OpenAIInvestigationGateway("gpt-5.6", client=client)
        request = IncidentRequest(
            incident_id="inc-dataflow-042",
            summary="Workers cannot start",
            environment="synthetic",
            started_at=datetime.fromisoformat("2026-08-01T10:00:00+00:00"),
            ended_at=datetime.fromisoformat("2026-08-01T10:15:00+00:00"),
            services=["dataflow-worker"],
        )
        tool = ToolSpec(
            name="search_logs",
            description="Search logs",
            input_schema={
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "environment": {"type": "string"},
                },
            },
        )

        turn = gateway.next_turn(request, evidence=[], trace=[], tools=[tool])

        self.assertEqual("search_logs", turn.tool_calls[0].name)
        self.assertEqual("dataflow-worker", turn.tool_calls[0].arguments["service"])
        self.assertIsNotNone(turn.usage)
        assert turn.usage is not None
        self.assertEqual(150, turn.usage.total_tokens)
        self.assertEqual(20, turn.usage.cached_input_tokens)
        self.assertIsNotNone(client.responses.arguments)
        assert client.responses.arguments is not None
        self.assertEqual("required", client.responses.arguments["tool_choice"])
        self.assertFalse(client.responses.arguments["parallel_tool_calls"])
        self.assertEqual(4096, client.responses.arguments["max_output_tokens"])
        self.assertNotIn("reasoning", client.responses.arguments)
        definitions = cast(
            list[dict[str, object]], client.responses.arguments["tools"]
        )
        first = definitions[0]
        self.assertTrue(first["strict"])
        parameters = cast(dict[str, object], first["parameters"])
        self.assertEqual(
            ["service", "environment"],
            parameters["required"],
        )
        self.assertFalse(parameters["additionalProperties"])
        for definition in definitions:
            self.assert_strict_object_schemas(definition["parameters"])

    def test_live_adapter_applies_explicit_reasoning_and_output_limits(self) -> None:
        client = FakeClient()
        gateway = OpenAIInvestigationGateway(
            "gpt-5.6",
            max_output_tokens=2048,
            reasoning_effort="low",
            client=client,
        )
        request = IncidentRequest(
            incident_id="inc-dataflow-042",
            summary="Workers cannot start",
            environment="synthetic",
            started_at=datetime.fromisoformat("2026-08-01T10:00:00+00:00"),
            ended_at=datetime.fromisoformat("2026-08-01T10:15:00+00:00"),
            services=["dataflow-worker"],
        )
        tool = ToolSpec(
            name="search_logs",
            description="Search logs",
            input_schema={"type": "object", "properties": {}},
        )

        gateway.next_turn(request, evidence=[], trace=[], tools=[tool])

        assert client.responses.arguments is not None
        self.assertEqual(2048, client.responses.arguments["max_output_tokens"])
        self.assertEqual({"effort": "low"}, client.responses.arguments["reasoning"])


if __name__ == "__main__":
    unittest.main()
