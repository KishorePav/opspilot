from __future__ import annotations

import unittest

from opspilot.investigation.failures import (
    FAILURE_TAXONOMY,
    InvestigationFailedError,
    failure_definition,
)


class FailureTaxonomyTests(unittest.TestCase):
    def test_public_failure_is_structured_and_sanitized(self) -> None:
        failure = InvestigationFailedError("report_contains_unknown_citation")

        self.assertEqual(
            {
                "code": "report_contains_unknown_citation",
                "category": "safety_policy",
                "retryable": False,
                "message": "The report cited evidence that was not collected.",
            },
            failure.public_detail(),
        )

    def test_taxonomy_covers_runtime_and_trace_failures(self) -> None:
        required = {
            "model_gateway_failed",
            "duplicate_tool_call",
            "tool_call_budget_exhausted",
            "evidence_budget_exhausted",
            "report_contains_unknown_citation",
            "pricing_policy_mismatch",
            "scope_violation",
            "unknown_tool",
            "invalid_arguments",
            "retrieval_unavailable",
        }
        self.assertLessEqual(required, set(FAILURE_TAXONOMY))

    def test_unknown_failure_code_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unregistered"):
            failure_definition("not-registered")


if __name__ == "__main__":
    unittest.main()
