import tempfile
import unittest
from pathlib import Path

from app import BusinessError, ReviewStore


class ReviewFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReviewStore(Path(self.tmp.name) / "test.db")
        self.store.seed()

    def tearDown(self):
        self.tmp.cleanup()

    def _paper(self):
        return self.store.submit_paper("alice", "可靠分布式提交协议", "本文提出一种用于弱网环境的可靠提交协议，并通过模拟实验验证其安全性和性能。")["id"]

    def test_complete_flow_and_double_blind_view(self):
        paper_id = self._paper()
        a1 = self.store.assign("chair", paper_id, "r1")["id"]
        a2 = self.store.assign("chair", paper_id, "r2")["id"]
        self.store.respond_assignment("r1", a1, True)
        self.store.respond_assignment("r2", a2, True)
        self.store.submit_review("r1", a1, 4, "方法严谨，缺少与最近工作的对比。")
        self.store.submit_review("r2", a2, 3, "实验充分，但部分结论需要进一步解释。")
        self.store.submit_rebuttal("alice", paper_id, "感谢意见，我们将补充对比并解释实验结论。")
        result = self.store.decide("chair", paper_id, "minor_revision", "补充实验后接收。")
        self.assertEqual(result["decision"], "minor_revision")
        self.assertIsNone(self.store.get_paper("r1", paper_id)["author_id"])
        self.assertIsNotNone(self.store.get_paper("chair", paper_id)["author_id"])
        history = self.store.history("chair", paper_id)
        self.assertEqual(history[-1]["action"], "decision.record")
        self.assertGreaterEqual(len(history), 8)

    def test_conflict_blocks_assignment_and_role_is_enforced(self):
        paper_id = self._paper()
        self.store.add_conflict("chair", paper_id, "r1", "同一导师团队成员")
        with self.assertRaises(BusinessError) as ctx:
            self.store.assign("chair", paper_id, "r1")
        self.assertEqual(ctx.exception.code, "conflict_of_interest")
        with self.assertRaises(BusinessError) as ctx:
            self.store.assign("alice", paper_id, "r2")
        self.assertEqual(ctx.exception.status, 403)
        with self.assertRaises(BusinessError) as ctx:
            self.store.get_paper("r2", paper_id)
        self.assertEqual(ctx.exception.status, 403)

    def _two_reviews(self, score1, score2):
        paper_id = self._paper()
        a1 = self.store.assign("chair", paper_id, "r1")["id"]
        a2 = self.store.assign("chair", paper_id, "r2")["id"]
        self.store.respond_assignment("r1", a1, True)
        self.store.respond_assignment("r2", a2, True)
        self.store.submit_review("r1", a1, score1, "方法严谨，缺少与最近工作的对比。")
        self.store.submit_review("r2", a2, score2, "实验充分，但部分结论需要进一步解释。")
        return paper_id

    def test_suggested_decision_needs_no_override_and_is_persisted(self):
        paper_id = self._two_reviews(4, 3)  # 均分 3.5、低分 3 → 小修
        view = self.store.get_decision_view("chair", paper_id)
        self.assertEqual(view["recommendation"]["suggested_decision"], "minor_revision")
        self.assertEqual(view["recommendation"]["average_score"], 3.5)
        result = self.store.decide("chair", paper_id, "minor_revision", "按建议处理。")
        self.assertFalse(result["overridden"])
        self.assertEqual(result["average_score"], 3.5)
        self.assertEqual(result["suggested_decision"], "minor_revision")
        self.assertEqual(result["override_reason"], "")
        # 留存数据可在决定视图中取回。
        again = self.store.get_decision_view("chair", paper_id)
        self.assertEqual(again["decision"]["decision"], "minor_revision")
        self.assertEqual(again["decision"]["average_score"], 3.5)

    def test_override_without_reason_returns_422_and_nothing_saved(self):
        paper_id = self._two_reviews(5, 5)  # 建议接收
        with self.assertRaises(BusinessError) as ctx:
            self.store.decide("chair", paper_id, "reject", "想拒。", "   ")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.code, "override_reason_required")
        # 决定未保存，论文仍是 under_review。
        self.assertEqual(self.store.get_paper("chair", paper_id)["status"], "under_review")
        self.assertIsNone(self.store.get_decision_view("chair", paper_id)["decision"])

    def test_override_with_reason_is_persisted(self):
        paper_id = self._two_reviews(5, 5)
        result = self.store.decide("chair", paper_id, "major_revision", "需重做实验。", "发现一作有未披露的学术不端嫌疑。")
        self.assertTrue(result["overridden"])
        self.assertEqual(result["override_reason"], "发现一作有未披露的学术不端嫌疑。")
        stored = self.store.get_decision_view("chair", paper_id)["decision"]
        self.assertEqual(stored["override_reason"], "发现一作有未披露的学术不端嫌疑。")

    def test_thresholds_accept_reject_and_revision_split(self):
        self.assertEqual(
            self.store.get_decision_view("chair", self._two_reviews(4, 4))["recommendation"]["suggested_decision"],
            "accept",
        )
        self.assertEqual(
            self.store.get_decision_view("chair", self._two_reviews(2, 2))["recommendation"]["suggested_decision"],
            "reject",
        )
        self.assertEqual(
            self.store.get_decision_view("chair", self._two_reviews(2, 5))["recommendation"]["suggested_decision"],
            "major_revision",
        )

    def test_author_sees_only_final_decision_after_decided(self):
        paper_id = self._two_reviews(4, 3)
        # 决定前：409
        with self.assertRaises(BusinessError) as ctx:
            self.store.get_decision_view("alice", paper_id)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "decision_not_ready")
        self.store.decide("chair", paper_id, "minor_revision", "小修后录用。")
        view = self.store.get_decision_view("alice", paper_id)
        self.assertNotIn("reviews", view)
        self.assertNotIn("recommendation", view)
        self.assertEqual(view["decision"]["decision"], "minor_revision")
        self.assertNotIn("override_reason", view["decision"])
        self.assertNotIn("suggested_decision", view["decision"])
        # 论文视图携带最终结论，评审人视图不携带。
        self.assertEqual(self.store.get_paper("alice", paper_id)["decision"], "minor_revision")
        self.assertNotIn("decision", self.store.get_paper("r1", paper_id))

    def test_author_history_hides_reviewer_identity_and_scores(self):
        paper_id = self._two_reviews(4, 2)
        self.store.decide("chair", paper_id, "major_revision", "大修。")
        history = self.store.history("alice", paper_id)
        actions = {row["action"] for row in history}
        self.assertNotIn("review.submit", actions)
        self.assertNotIn("assignment.invite", actions)
        self.assertIn("decision.record", actions)
        decision_row = next(row for row in history if row["action"] == "decision.record")
        self.assertEqual(set(decision_row["detail"].keys()), {"decision"})
        self.assertNotIn("r1", [row["actor_id"] for row in history])
        self.assertNotIn("r2", [row["actor_id"] for row in history])

    def test_reviewer_cannot_open_decision_view(self):
        paper_id = self._two_reviews(3, 3)
        with self.assertRaises(BusinessError) as ctx:
            self.store.get_decision_view("r1", paper_id)
        self.assertEqual(ctx.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
