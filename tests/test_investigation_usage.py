from __future__ import annotations

import unittest
from decimal import Decimal

from opspilot.investigation.models import ModelUsage
from opspilot.investigation.usage import PricingPolicy, summarize_usage


class InvestigationUsageTests(unittest.TestCase):
    def test_summarizes_tokens_and_versioned_cost(self) -> None:
        records = [
            ModelUsage(
                model="replay-agent-v1",
                input_tokens=1000,
                cached_input_tokens=400,
                output_tokens=200,
                reasoning_tokens=50,
                total_tokens=1200,
            )
        ]
        pricing = PricingPolicy(
            model="replay-agent-v1",
            version="synthetic-rates-v1",
            input_usd_per_million=Decimal("1.00"),
            cached_input_usd_per_million=Decimal("0.25"),
            output_usd_per_million=Decimal("2.00"),
        )

        summary = summarize_usage(records, model_calls=1, pricing=pricing)

        self.assertEqual(1200, summary.total_tokens)
        self.assertEqual(400, summary.cached_input_tokens)
        self.assertEqual(Decimal("0.001100"), summary.estimated_cost_usd)
        self.assertEqual("synthetic-rates-v1", summary.pricing_version)

    def test_rejects_inconsistent_provider_token_accounting(self) -> None:
        with self.assertRaisesRegex(ValueError, "total tokens"):
            ModelUsage(
                model="replay-agent-v1",
                input_tokens=10,
                output_tokens=5,
                total_tokens=14,
            )

    def test_refuses_to_apply_rates_for_another_model(self) -> None:
        pricing = PricingPolicy(
            model="expected-model",
            version="rates-v1",
            input_usd_per_million=Decimal("1"),
            cached_input_usd_per_million=Decimal("1"),
            output_usd_per_million=Decimal("1"),
        )
        record = ModelUsage(
            model="different-model",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )

        with self.assertRaisesRegex(ValueError, "cannot price"):
            pricing.estimate([record])


if __name__ == "__main__":
    unittest.main()
