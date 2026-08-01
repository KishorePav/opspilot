from __future__ import annotations

import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from opspilot.config import Settings


class SettingsTests(unittest.TestCase):
    def test_pricing_rates_must_be_configured_as_one_versioned_policy(self) -> None:
        with patch.dict(
            os.environ,
            {"OPSPILOT_INPUT_USD_PER_MILLION": "1.00"},
            clear=True,
        ), self.assertRaisesRegex(ValueError, "configured together"):
            Settings.from_environment()

    def test_complete_pricing_policy_is_parsed_without_a_default_claim(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPSPILOT_PRICING_VERSION": "provider-card-2026-08-01",
                "OPSPILOT_INPUT_USD_PER_MILLION": "1.00",
                "OPSPILOT_CACHED_INPUT_USD_PER_MILLION": "0.25",
                "OPSPILOT_OUTPUT_USD_PER_MILLION": "2.00",
            },
            clear=True,
        ):
            settings = Settings.from_environment()

        self.assertEqual("provider-card-2026-08-01", settings.pricing_version)
        self.assertEqual(Decimal("1.00"), settings.input_usd_per_million)


if __name__ == "__main__":
    unittest.main()
