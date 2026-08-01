import unittest

from opspilot.evaluation.metrics import ndcg_at_k, recall_at_k, reciprocal_rank, summarize


class RetrievalMetricTests(unittest.TestCase):
    def test_metrics_reward_early_relevant_results(self) -> None:
        expected = {"target"}
        ranked = ["other", "target", "last"]
        self.assertEqual(1.0, recall_at_k(expected, ranked, 2))
        self.assertEqual(0.5, reciprocal_rank(expected, ranked))
        self.assertGreater(ndcg_at_k(expected, ranked, 3), 0.6)

    def test_summary_averages_cases(self) -> None:
        result = summarize(
            [({"a"}, ["a", "b"]), ({"b"}, ["a", "b"])],
            k=2,
        )
        self.assertEqual(2, result.cases)
        self.assertEqual(1.0, result.recall_at_k)
        self.assertEqual(0.75, result.mean_reciprocal_rank)


if __name__ == "__main__":
    unittest.main()
