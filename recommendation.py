"""决定建议计算：纯函数，独立于存储与 HTTP 层维护。"""
from __future__ import annotations

MIN_COMPLETED_REVIEWS = 2  # 评定完成所需的已完成评审份数。


def recommend(scores: list[int]) -> dict:
    """按已完成评审的评分给出建议结论。

    规则：平均分不低于 4 建议接收；不高于 2 建议拒稿；
    其余按较低分：不低于 3 建议小修，否则建议大修。
    """
    if not scores:
        raise ValueError("scores 不能为空")
    exact = sum(scores) / len(scores)
    if exact >= 4:
        suggestion = "accept"
    elif exact <= 2:
        suggestion = "reject"
    elif min(scores) >= 3:
        suggestion = "minor_revision"
    else:
        suggestion = "major_revision"
    return {"average": round(exact, 2), "recommendation": suggestion}
