import unittest

from opspilot.adapters.postgres import PostgresHybridRetriever, _serialize_vector
from opspilot.retrieval.embedding import HashEmbeddingProvider


class PostgresAdapterContractTests(unittest.TestCase):
    def test_vector_serialization_is_stable(self) -> None:
        self.assertEqual("[0,1,-0.25]", _serialize_vector([0.0, 1.0, -0.25]))

    def test_schema_dimension_mismatch_is_rejected_before_connecting(self) -> None:
        with self.assertRaisesRegex(ValueError, "1536-dimension"):
            PostgresHybridRetriever(
                "postgresql://unused",
                HashEmbeddingProvider(dimensions=192),
            )


if __name__ == "__main__":
    unittest.main()
