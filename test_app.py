import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app import BusinessError, ReviewServer, ReviewStore
from decisions import DecisionService
from recommendation import recommend


class RecommendationTests(unittest.TestCase):
    """建议计算：平均分决定接收/拒稿，中间档按较低分区分小修/大修。"""

    def test_accept_when_average_at_least_4(self):
        self.assertEqual(recommend([4, 4]), {"average": 4.0, "recommendation": "accept"})
        self.assertEqual(recommend([5, 3])["recommendation"], "accept")

    def test_reject_when_average_at_most_2(self):
        self.assertEqual(recommend([2, 2])["recommendation"], "reject")
        self.assertEqual(recommend([1, 2])["recommendation"], "reject")

    def test_middle_band_uses_lower_score(self):
        self.assertEqual(recommend([3, 3])["recommendation"], "minor_revision")
        self.assertEqual(recommend([3, 4])["recommendation"], "minor_revision")
        self.assertEqual(recommend([2, 5])["recommendation"], "major_revision")
        self.assertEqual(recommend([1, 5])["recommendation"], "major_revision")

    def test_empty_scores_rejected(self):
        with self.assertRaises(ValueError):
            recommend([])


class ReviewFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReviewStore(Path(self.tmp.name) / "test.db")
        self.store.seed()
        self.decisions = DecisionService(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _paper(self):
        return self.store.submit_paper("alice", "可靠分布式提交协议", "本文提出一种用于弱网环境的可靠提交协议，并通过模拟实验验证其安全性和性能。")["id"]

    def _reviewed_paper(self, scores=(4, 3)):
        paper_id = self._paper()
        texts = ["方法严谨，缺少与最近工作的对比。", "实验充分，但部分结论需要进一步解释。"]
        for reviewer, score, text in zip(("r1", "r2"), scores, texts):
            assignment_id = self.store.assign("chair", paper_id, reviewer)["id"]
            self.store.respond_assignment(reviewer, assignment_id, True)
            self.store.submit_review(reviewer, assignment_id, score, text)
        return paper_id

    def test_complete_flow_and_double_blind_view(self):
        paper_id = self._reviewed_paper((4, 3))
        self.store.submit_rebuttal("alice", paper_id, "感谢意见，我们将补充对比并解释实验结论。")
        result = self.decisions.decide("chair", paper_id, "minor_revision", "补充实验后接收。")
        self.assertEqual(result["decision"], "minor_revision")
        self.assertEqual(result["average_score"], 3.5)
        self.assertEqual(result["recommendation"], "minor_revision")
        self.assertEqual(result["override_reason"], "")
        self.assertIsNone(self.store.get_paper("r1", paper_id)["author_id"])
        self.assertIsNotNone(self.store.get_paper("chair", paper_id)["author_id"])
        history = self.store.history("chair", paper_id)
        self.assertEqual(history[-1]["action"], "decision.record")
        self.assertEqual(history[-1]["detail"]["average"], 3.5)
        self.assertEqual(history[-1]["detail"]["recommendation"], "minor_revision")
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

    def test_override_reason_required_when_deviating(self):
        paper_id = self._reviewed_paper((4, 4))  # 均分 4.0，建议 accept。
        with self.assertRaises(BusinessError) as ctx:
            self.decisions.decide("chair", paper_id, "reject")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.code, "override_reason_required")
        # 决定未保存：论文状态不变，也没有决定记录。
        self.assertEqual(self.store.get_paper("chair", paper_id)["status"], "under_review")
        with self.assertRaises(BusinessError) as ctx:
            self.decisions.decision_view("chair", paper_id)
        self.assertEqual(ctx.exception.code, "decision_pending")
        # 填写覆盖理由后可以保存，均分、建议、覆盖理由一起留存。
        result = self.decisions.decide("chair", paper_id, "reject", override_reason="评审遗漏了严重的实验缺陷")
        self.assertEqual(result["recommendation"], "accept")
        self.assertEqual(result["average_score"], 4.0)
        self.assertEqual(result["override_reason"], "评审遗漏了严重的实验缺陷")

    def test_decision_matching_recommendation_needs_no_reason(self):
        paper_id = self._reviewed_paper((5, 4))  # 均分 4.5，建议 accept。
        result = self.decisions.decide("chair", paper_id, "accept")
        self.assertEqual(result["recommendation"], "accept")
        self.assertEqual(result["average_score"], 4.5)
        with self.assertRaises(BusinessError) as ctx:
            self.decisions.decide("chair", paper_id, "accept")
        self.assertEqual(ctx.exception.code, "paper_decided")

    def test_decide_requires_two_completed_reviews(self):
        paper_id = self._paper()
        with self.assertRaises(BusinessError) as ctx:
            self.decisions.decide("chair", paper_id, "accept")
        self.assertEqual(ctx.exception.code, "insufficient_reviews")

    def test_summary_for_chair_page(self):
        paper_id = self._reviewed_paper((2, 5))  # 均分 3.5，较低分 2，建议大修。
        summary = self.decisions.summary("chair", paper_id)
        self.assertTrue(summary["ready"])
        self.assertEqual(summary["average"], 3.5)
        self.assertEqual(summary["recommendation"], "major_revision")
        self.assertEqual(len(summary["reviews"]), 2)
        self.assertIsNone(summary["decision"])
        with self.assertRaises(BusinessError) as ctx:
            self.decisions.summary("alice", paper_id)
        self.assertEqual(ctx.exception.status, 403)

    def test_summary_not_ready_until_two_reviews(self):
        paper_id = self._paper()
        assignment_id = self.store.assign("chair", paper_id, "r1")["id"]
        self.store.respond_assignment("r1", assignment_id, True)
        self.store.submit_review("r1", assignment_id, 5, "非常扎实的工作，实验与写作都很成熟。")
        summary = self.decisions.summary("chair", paper_id)
        self.assertFalse(summary["ready"])
        self.assertIsNone(summary["average"])
        self.assertIsNone(summary["recommendation"])

    def test_author_sees_only_final_decision(self):
        paper_id = self._reviewed_paper((3, 3))
        with self.assertRaises(BusinessError) as ctx:
            self.decisions.decision_view("alice", paper_id)
        self.assertEqual(ctx.exception.code, "decision_pending")
        self.decisions.decide("chair", paper_id, "minor_revision")
        view = self.decisions.decision_view("alice", paper_id)
        self.assertEqual(view["decision"], "minor_revision")
        for field in ("average_score", "recommendation", "override_reason", "decided_by", "note"):
            self.assertNotIn(field, view)
        with self.assertRaises(BusinessError) as ctx:
            self.decisions.decision_view("r1", paper_id)
        self.assertEqual(ctx.exception.status, 403)

    def test_author_history_hides_reviewer_identity_and_reviews(self):
        paper_id = self._reviewed_paper((4, 3))
        self.decisions.decide("chair", paper_id, "minor_revision")
        history = self.store.history("alice", paper_id)
        self.assertEqual([item["action"] for item in history], ["paper.submit", "decision.record"])
        self.assertEqual(history[-1]["detail"], {"decision": "minor_revision"})
        self.assertNotIn("r1", json.dumps(history, ensure_ascii=False))


class DecisionApiTests(unittest.TestCase):
    """接口层：偏离建议且未填覆盖理由时返回 422，且决定不保存。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = ReviewStore(Path(cls.tmp.name) / "http.db")
        cls.store.seed()
        cls.server = ReviewServer(("127.0.0.1", 0), cls.store)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def _post(self, path, payload, user):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-User-Id": user},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_deviating_decision_without_override_returns_422(self):
        paper_id = self.store.submit_paper("alice", "面向边缘缓存的调度策略", "本文研究边缘缓存场景下的调度策略，给出理论分析与大规模实验评估。")["id"]
        for reviewer in ("r1", "r2"):
            assignment_id = self.store.assign("chair", paper_id, reviewer)["id"]
            self.store.respond_assignment(reviewer, assignment_id, True)
            self.store.submit_review(reviewer, assignment_id, 5, "工作完整，实验充分，写作清晰，建议接收。")
        status, body = self._post(f"/api/papers/{paper_id}/decision", {"decision": "reject"}, "chair")
        self.assertEqual(status, 422)
        self.assertEqual(body["error"]["code"], "override_reason_required")
        # 未保存：带覆盖理由后仍可正常决定。
        status, body = self._post(
            f"/api/papers/{paper_id}/decision",
            {"decision": "reject", "override_reason": "评审未发现的伦理问题"},
            "chair",
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["recommendation"], "accept")
        self.assertEqual(body["override_reason"], "评审未发现的伦理问题")


if __name__ == "__main__":
    unittest.main()
