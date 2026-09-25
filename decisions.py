"""决定事务：覆盖理由校验与决定留存，独立于建议计算和主席页面维护。"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from common import BusinessError, VALID_DECISIONS, utcnow
from recommendation import MIN_COMPLETED_REVIEWS, recommend

if TYPE_CHECKING:  # 避免与 app.py 循环导入。
    from app import ReviewStore


class DecisionService:
    """主席决定用例。与 ReviewStore 约定一致：每个公开方法使用独立连接。"""

    def __init__(self, store: ReviewStore):
        self.store = store

    def summary(self, chair_id: str, paper_id: int) -> dict:
        """主席页面数据：已完成评审、均分、建议与已有决定。"""
        with self.store.connect() as conn:
            chair = self.store._user(conn, chair_id)
            self.store._require(chair, "chair")
            paper = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
            if not paper:
                raise BusinessError("论文不存在", 404, "not_found")
            rows = conn.execute(
                "SELECT * FROM assignments WHERE paper_id=? AND status='completed' ORDER BY id",
                (paper_id,),
            ).fetchall()
            reviews = [
                {
                    "assignment_id": row["id"],
                    "reviewer_id": row["reviewer_id"],
                    "score": row["score"],
                    "review_text": row["review_text"],
                    "submitted_at": row["updated_at"],
                }
                for row in rows
            ]
            ready = len(reviews) >= MIN_COMPLETED_REVIEWS
            rec = recommend([r["score"] for r in reviews]) if ready else {"average": None, "recommendation": None}
            decision = conn.execute("SELECT * FROM decisions WHERE paper_id=?", (paper_id,)).fetchone()
            return {
                "paper_id": paper_id,
                "status": paper["status"],
                "reviews": reviews,
                "completed": len(reviews),
                "required": MIN_COMPLETED_REVIEWS,
                "ready": ready,
                "average": rec["average"],
                "recommendation": rec["recommendation"],
                "decision": self._decision_dict(decision) if decision else None,
            }

    def decide(self, chair_id: str, paper_id: int, decision: str, note: str = "", override_reason: str = "") -> dict:
        if decision not in VALID_DECISIONS:
            raise BusinessError("决定值不合法", 422, "invalid_decision")
        with self.store.connect() as conn:
            chair = self.store._user(conn, chair_id)
            self.store._require(chair, "chair")
            try:
                conn.execute("BEGIN IMMEDIATE")
                paper = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
                if not paper or paper["status"] not in {"submitted", "under_review"}:
                    raise BusinessError("论文不存在或已经决定", 409, "paper_decided")
                scores = [
                    row[0]
                    for row in conn.execute(
                        "SELECT score FROM assignments WHERE paper_id=? AND status='completed' ORDER BY id",
                        (paper_id,),
                    )
                ]
                if len(scores) < MIN_COMPLETED_REVIEWS:
                    raise BusinessError(f"至少需要 {MIN_COMPLETED_REVIEWS} 份已完成评审才能作出决定", 409, "insufficient_reviews")
                rec = recommend(scores)
                override_reason = override_reason.strip()
                if decision != rec["recommendation"] and not override_reason:
                    raise BusinessError("决定与系统建议不一致，必须填写覆盖理由", 422, "override_reason_required")
                cur = conn.execute(
                    """INSERT INTO decisions(paper_id,decision,note,average_score,recommendation,override_reason,decided_by,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (paper_id, decision, note.strip(), rec["average"], rec["recommendation"], override_reason, chair_id, utcnow()),
                )
                conn.execute("UPDATE papers SET status='decided' WHERE id=?", (paper_id,))
                self.store._audit(conn, paper_id, chair_id, "decision.record", {
                    "decision": decision,
                    "note": note.strip(),
                    "average": rec["average"],
                    "recommendation": rec["recommendation"],
                    "override_reason": override_reason,
                })
                row = conn.execute("SELECT * FROM decisions WHERE id=?", (cur.lastrowid,)).fetchone()
                return self._decision_dict(row)
            except Exception:
                conn.rollback()
                raise

    def decision_view(self, user_id: str, paper_id: int) -> dict:
        """作者只能在决定后看到最终结论；主席可查看完整记录。"""
        with self.store.connect() as conn:
            user = self.store._user(conn, user_id)
            paper = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
            if not paper:
                raise BusinessError("论文不存在", 404, "not_found")
            row = conn.execute("SELECT * FROM decisions WHERE paper_id=?", (paper_id,)).fetchone()
            if user["role"] == "author":
                if paper["author_id"] != user["id"]:
                    raise BusinessError("作者只能查看自己的论文", 403, "forbidden")
                if not row:
                    raise BusinessError("尚未作出决定", 409, "decision_pending")
                # 仅最终结论：不含均分、建议、覆盖理由与评审信息。
                return {"paper_id": paper_id, "decision": row["decision"], "decided_at": row["created_at"]}
            self.store._require(user, "chair")
            if not row:
                raise BusinessError("尚未作出决定", 409, "decision_pending")
            return self._decision_dict(row)

    @staticmethod
    def _decision_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "paper_id": row["paper_id"],
            "decision": row["decision"],
            "note": row["note"],
            "average_score": row["average_score"],
            "recommendation": row["recommendation"],
            "override_reason": row["override_reason"],
            "decided_by": row["decided_by"],
            "decided_at": row["created_at"],
        }
