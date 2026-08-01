from __future__ import annotations

import unittest

from opspilot.observability import RecordingObservability


class ObservabilityTests(unittest.TestCase):
    def test_bounded_signals_exclude_sensitive_identifiers_and_content(self) -> None:
        observability = RecordingObservability()

        with observability.operation(
            "workflow.execute_proposal",
            {"component": "workflow", "recovered": False},
        ):
            pass
        observability.record_auth(outcome="allowed", reason="role_authorized")
        observability.record_http(
            route="/v1/investigations/{run_id}",
            method="GET",
            status_code=200,
            duration=0.02,
        )

        serialized = str(observability.signals)
        for forbidden in (
            "tenant-alpha",
            "operator@example.com",
            "Bearer",
            "incident_id",
            "evidence",
            "prompt",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_unregistered_operation_attributes_fail_before_export(self) -> None:
        observability = RecordingObservability()

        with (
            self.assertRaisesRegex(ValueError, "unsupported telemetry attributes"),
            observability.operation(
                "workflow.create_investigation",
                {"incident_id": "inc-secret-101"},
            ),
        ):
            pass


if __name__ == "__main__":
    unittest.main()
