import unittest

from opspilot.domain.models import Document
from opspilot.retrieval.chunking import ChunkingConfig, WordChunker


class WordChunkerTests(unittest.TestCase):
    def test_chunk_ids_are_stable_and_overlap_is_preserved(self) -> None:
        document = Document(
            document_id="runbook-1",
            title="Runbook",
            content=" ".join(f"word-{index}" for index in range(30)),
            source="fixture",
        )
        chunker = WordChunker(ChunkingConfig(max_words=12, overlap_words=3))

        first = chunker.chunk(document)
        second = chunker.chunk(document)

        self.assertEqual([chunk.chunk_id for chunk in first], [chunk.chunk_id for chunk in second])
        self.assertEqual(first[0].content.split()[-3:], first[1].content.split()[:3])
        self.assertEqual([chunk.ordinal for chunk in first], list(range(len(first))))

    def test_invalid_overlap_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ChunkingConfig(max_words=10, overlap_words=10)


if __name__ == "__main__":
    unittest.main()
