import unittest

from httpx import ASGITransport, AsyncClient

from opspilot.api import create_app, get_retriever


class RetrievalApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        get_retriever.cache_clear()
        self.client = AsyncClient(
            transport=ASGITransport(app=create_app()),
            base_url="http://test",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        get_retriever.cache_clear()

    async def test_health_endpoint(self) -> None:
        response = await self.client.get("/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.json())

    async def test_retrieval_endpoint_returns_cited_evidence(self) -> None:
        response = await self.client.post(
            "/v1/retrieve",
            json={"query": "Dataflow cannot act as service account", "top_k": 3},
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("dataflow-permission-denied", payload["evidence"][0]["document_id"])
        self.assertTrue(payload["evidence"][0]["chunk_id"])
        self.assertTrue(payload["evidence"][0]["source"].endswith(".md"))


if __name__ == "__main__":
    unittest.main()
