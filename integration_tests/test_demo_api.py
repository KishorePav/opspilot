from __future__ import annotations

import unittest

from httpx import ASGITransport, AsyncClient

from opspilot.demo import create_demo_app


class SyntheticDemoApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.app = create_demo_app()
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://demo.test",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_demo_exposes_only_an_allowlisted_synthetic_scenario(self) -> None:
        response = await self.client.get("/api/scenarios")

        self.assertEqual(200, response.status_code)
        scenarios = response.json()
        self.assertEqual(1, len(scenarios))
        self.assertEqual(
            "dataflow-diagnosis-with-injection-present",
            scenarios[0]["scenario_id"],
        )
        self.assertEqual("synthetic", scenarios[0]["incident"]["environment"])

    async def test_demo_runs_the_real_bounded_investigator_without_side_effects(self) -> None:
        response = await self.client.post(
            "/api/scenarios/dataflow-diagnosis-with-injection-present/investigate"
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("diagnosed", payload["result"]["report"]["status"])
        self.assertEqual(4, len(payload["result"]["trace"]))
        self.assertTrue(all(item["status"] == "succeeded" for item in payload["result"]["trace"]))
        report_text = str(payload["result"]["report"]).lower()
        self.assertNotIn("ignore previous instructions", report_text)
        self.assertNotIn("approve remediation", report_text)
        self.assertIn(
            "no model, database, credential, or remediation access",
            payload["safety_controls"],
        )

    async def test_demo_rejects_arbitrary_scenarios_and_has_no_workflow_routes(self) -> None:
        missing = await self.client.post("/api/scenarios/arbitrary/investigate")
        schema = self.app.openapi()

        self.assertEqual(404, missing.status_code)
        self.assertNotIn("/v1/investigate", schema["paths"])
        self.assertFalse(any("remediation" in path for path in schema["paths"]))

    async def test_demo_ui_is_self_contained_and_escapes_dynamic_evidence(self) -> None:
        response = await self.client.get("/")

        self.assertEqual(200, response.status_code)
        self.assertIn("Evidence before diagnosis", response.text)
        self.assertIn("textContent", response.text)
        self.assertNotIn("https://", response.text)
        self.assertEqual("DENY", response.headers["x-frame-options"])
        self.assertIn("connect-src 'self'", response.headers["content-security-policy"])


if __name__ == "__main__":
    unittest.main()
