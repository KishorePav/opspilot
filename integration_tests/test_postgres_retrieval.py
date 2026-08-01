from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import psycopg

from opspilot.adapters.postgres import PostgresHybridRetriever
from opspilot.domain.models import Document
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.storage.migrations import MigrationDriftError, apply_migrations

_DATABASE_URL = os.getenv("OPSPILOT_TEST_DATABASE_URL")


@unittest.skipUnless(_DATABASE_URL, "OPSPILOT_TEST_DATABASE_URL is not configured")
class PostgresHybridRetrieverTests(unittest.TestCase):
    retriever: PostgresHybridRetriever

    @classmethod
    def setUpClass(cls) -> None:
        assert _DATABASE_URL is not None
        apply_migrations(_DATABASE_URL, Path("migrations"))

    def setUp(self) -> None:
        assert _DATABASE_URL is not None
        with psycopg.connect(_DATABASE_URL) as connection:
            connection.execute("TRUNCATE TABLE evidence_chunks")
        self.retriever = PostgresHybridRetriever(
            _DATABASE_URL,
            HashEmbeddingProvider(dimensions=1536),
            pool_min_size=1,
            pool_max_size=2,
        )

    def tearDown(self) -> None:
        self.retriever.close()

    def test_persists_and_filters_candidates_before_fusion(self) -> None:
        self.retriever.index_documents(
            [
                Document(
                    document_id="orders-kafka",
                    title="Orders consumer lag",
                    content="Consumer lag and group rebalancing after deployment.",
                    source="orders.md",
                    metadata={"environment": "qa", "service": "orders"},
                ),
                Document(
                    document_id="catalogue-kafka",
                    title="Catalogue consumer lag",
                    content="Consumer lag and group rebalancing after deployment.",
                    source="catalogue.md",
                    metadata={"environment": "qa", "service": "catalogue"},
                ),
            ]
        )

        hits = self.retriever.search(
            "consumer lag rebalancing",
            top_k=5,
            filters={"environment": "qa", "service": "orders"},
        )

        self.assertEqual(["orders-kafka"], [hit.chunk.document_id for hit in hits])
        self.assertEqual("orders", hits[0].chunk.metadata["service"])
        self.assertIsNotNone(hits[0].lexical_rank)
        self.assertIsNotNone(hits[0].vector_rank)

    def test_reindex_replaces_stale_chunks_atomically(self) -> None:
        original = Document(
            document_id="runbook",
            title="Original",
            content="old content " * 200,
            source="runbook.md",
        )
        replacement = Document(
            document_id="runbook",
            title="Replacement",
            content="new bounded recovery procedure",
            source="runbook.md",
        )
        self.assertGreater(self.retriever.index_documents([original]), 1)
        self.assertEqual(1, self.retriever.index_documents([replacement]))

        assert _DATABASE_URL is not None
        with psycopg.connect(_DATABASE_URL) as connection:
            count, title = connection.execute(
                "SELECT count(*), min(title) FROM evidence_chunks WHERE document_id = %s",
                ("runbook",),
            ).fetchone() or (0, "")
        self.assertEqual(1, count)
        self.assertEqual("Replacement", title)

    def test_filter_values_are_bound_as_data(self) -> None:
        self.retriever.index_documents(
            [
                Document(
                    document_id="orders",
                    title="Orders",
                    content="database connection exhaustion",
                    source="orders.md",
                    metadata={"service": "orders"},
                )
            ]
        )
        hits = self.retriever.search(
            "database connection",
            filters={"service": "orders' OR true --"},
        )
        self.assertEqual([], hits)

    def test_migrations_are_idempotent_and_checksum_protected(self) -> None:
        assert _DATABASE_URL is not None
        result = apply_migrations(_DATABASE_URL, Path("migrations"))
        self.assertEqual((), result.applied)
        self.assertIn("0001_retrieval_schema", result.already_applied)

        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "0001_retrieval_schema.sql"
            original = Path("migrations/0001_retrieval_schema.sql").read_text(encoding="utf-8")
            changed.write_text(original + "\n-- changed after application\n", encoding="utf-8")
            with self.assertRaises(MigrationDriftError):
                apply_migrations(_DATABASE_URL, Path(directory))


if __name__ == "__main__":
    unittest.main()
