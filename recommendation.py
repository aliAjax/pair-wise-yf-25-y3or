"""决定建议计算：纯函数模块，与存储事务、主席页面分开维护。

规则（基于已完成评审的 1-5 分评分）：
- 平均分不低于 4：建议接收 accept
- 平均分不高于 2：建议拒稿 reject
- 其余（2 < 平均分 < 4）按较低分区分：
  - 较低分不低于 3：小修 minor_revision
  - 较低分不高于 2：大修 major_revision
"""
from __future__ import annotations

ACCEPT = "accept"
REJECT = "reject"
MINOR_REVISION = "minor_revision"
MAJOR_REVISION = "major_revision"

ACCEPT_THRESHOLD = 4.0
REJECT_THRESHOLD = 2.0
MINOR_MIN_SCORE = 3


def _validated(scores) -> list[int]:
    items = list(scores)
    if not items:
        raise ValueError("至少需要一份已完成评审的评分")
    for s in items:
        if isinstance(s, bool) or not isinstance(s, int) or not 1 <= s <= 5:
            raise ValueError("评分必须是 1 到 5 的整数")
    return items


def average_score(scores) -> float:
    items = _validated(scores)
    return sum(items) / len(items)


def recommend_decision(scores) -> dict:
    """返回 {"count", "average_score", "min_score", "suggested_decision"}。"""
    items = _validated(scores)
    avg = sum(items) / len(items)
    low = min(items)
    if avg >= ACCEPT_THRESHOLD:
        suggestion = ACCEPT
    elif avg <= REJECT_THRESHOLD:
        suggestion = REJECT
    elif low >= MINOR_MIN_SCORE:
        suggestion = MINOR_REVISION
    else:
        suggestion = MAJOR_REVISION
    return {
        "count": len(items),
        "average_score": avg,
        "min_score": low,
        "suggested_decision": suggestion,
    }
