import unittest

from opspilot.domain.models import Document
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.retrieval.service import HybridRetriever


class HybridRetrieverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.retriever = HybridRetriever(HashEmbeddingProvider())
        self.retriever.index_documents(
            [
                Document(
                    document_id="kafka",
                    title="Kafka lag",
                    content="Consumer lag and repeated group rebalancing after a deployment.",
                    source="kafka.md",
                    metadata={"service": "orders"},
                ),
                Document(
                    document_id="postgres",
                    title="Postgres pool",
                    content="Database connection pool exhaustion causes API latency and timeouts.",
                    source="postgres.md",
                    metadata={"service": "catalogue"},
                ),
            ]
        )

    def test_relevant_evidence_is_ranked_first(self) -> None:
        hits = self.retriever.search("consumer lag rebalancing", top_k=2)
        self.assertEqual("kafka", hits[0].chunk.document_id)
        self.assertIsNotNone(hits[0].lexical_rank)
        self.assertIsNotNone(hits[0].vector_rank)

    def test_metadata_filter_is_applied_before_ranking(self) -> None:
        hits = self.retriever.search(
            "latency",
            top_k=2,
            filters={"service": "catalogue"},
        )
        self.assertEqual(["postgres"], [hit.chunk.document_id for hit in hits])

    def test_invalid_query_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.retriever.search("   ")


if __name__ == "__main__":
    unittest.main()
