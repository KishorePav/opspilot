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

    def test_approval_ttl_is_bounded(self) -> None:
        with patch.dict(
            os.environ,
            {"OPSPILOT_APPROVAL_TTL_SECONDS": "3601"},
            clear=True,
        ), self.assertRaisesRegex(ValueError, "approval TTL"):
            Settings.from_environment()

    def test_execution_lease_and_auth_configuration_fail_closed(self) -> None:
        with patch.dict(
            os.environ,
            {"OPSPILOT_EXECUTION_LEASE_TTL_SECONDS": "4"},
            clear=True,
        ), self.assertRaisesRegex(ValueError, "execution lease TTL"):
            Settings.from_environment()

        with patch.dict(
            os.environ,
            {"OPSPILOT_AUTH_JWKS_URL": "https://identity.example.test/jwks"},
            clear=True,
        ), self.assertRaisesRegex(ValueError, "configured together"):
            Settings.from_environment()

    def test_live_model_limits_are_bounded(self) -> None:
        with patch.dict(
            os.environ,
            {"OPSPILOT_INVESTIGATION_MAX_OUTPUT_TOKENS": "128"},
            clear=True,
        ), self.assertRaisesRegex(ValueError, "output budget"):
            Settings.from_environment()

        with patch.dict(
            os.environ,
            {"OPSPILOT_INVESTIGATION_REASONING_EFFORT": "unbounded"},
            clear=True,
        ), self.assertRaisesRegex(ValueError, "reasoning effort"):
            Settings.from_environment()

    def test_gemini_is_an_explicit_investigation_provider(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPSPILOT_INVESTIGATION_PROVIDER": "gemini",
                "OPSPILOT_INVESTIGATION_MODEL": "gemini-3.6-flash",
            },
            clear=True,
        ):
            settings = Settings.from_environment()

        self.assertEqual("gemini", settings.investigation_provider)
        self.assertEqual("gemini-3.6-flash", settings.investigation_model)


if __name__ == "__main__":
    unittest.main()
