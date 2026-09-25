import unittest

from recommendation import (
    ACCEPT,
    MAJOR_REVISION,
    MINOR_REVISION,
    REJECT,
    average_score,
    recommend_decision,
)


class RecommendationTests(unittest.TestCase):
    def test_average(self):
        self.assertEqual(average_score([3, 4]), 3.5)
        self.assertEqual(average_score([5, 5, 2]), 4.0)

    def test_accept_when_average_at_or_above_four(self):
        self.assertEqual(recommend_decision([4, 4])["suggested_decision"], ACCEPT)
        self.assertEqual(recommend_decision([5, 3])["suggested_decision"], ACCEPT)  # 均分 4

    def test_reject_when_average_at_or_below_two(self):
        self.assertEqual(recommend_decision([2, 2])["suggested_decision"], REJECT)
        self.assertEqual(recommend_decision([1, 3])["suggested_decision"], REJECT)  # 均分 2

    def test_middle_range_uses_lower_score(self):
        # 2 < 均分 < 4：较低分 >= 3 → 小修
        self.assertEqual(recommend_decision([3, 4])["suggested_decision"], MINOR_REVISION)
        # 较低分 <= 2 → 大修
        self.assertEqual(recommend_decision([2, 4])["suggested_decision"], MAJOR_REVISION)
        self.assertEqual(recommend_decision([1, 5])["suggested_decision"], MAJOR_REVISION)  # 均分 3

    def test_payload_fields(self):
        result = recommend_decision([2, 5])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["min_score"], 2)
        self.assertEqual(result["average_score"], 3.5)

    def test_invalid_scores(self):
        with self.assertRaises(ValueError):
            recommend_decision([])
        with self.assertRaises(ValueError):
            recommend_decision([3, 6])
        with self.assertRaises(ValueError):
            recommend_decision([True, 3])


if __name__ == "__main__":
    unittest.main()
