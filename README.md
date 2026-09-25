# 学术会议同行评审系统

一个仅使用 Python 3.11+ 标准库的独立示例项目。SQLite 保存数据，`http.server` 提供 JSON API 和演示页面。

## 运行

```bash
python app.py --init --seed
python app.py
```

访问 <http://127.0.0.1:8101>。默认数据库为 `review.db`，端口为 `8101`。主席决定工作台在 <http://127.0.0.1:8101/chair>。测试：

```bash
python -m unittest -v
```

## 角色和主要接口

演示用户：`alice`、`bob`（作者），`r1`、`r2`、`r3`（评审人），`chair`（主席）。所有 API 请求应带 `X-User-Id` 请求头。

- `POST /api/papers`：提交论文。
- `GET /api/papers` / `GET /api/papers/{id}`：按角色隔离查看；评审人看到双盲视图。
- `POST /api/papers/{id}/bids`：评审意向。
- `POST /api/papers/{id}/conflicts`：主席登记利益冲突。
- `POST /api/papers/{id}/assignments`：主席邀请评审人，执行负载上限与冲突检查。
- `POST /api/assignments/{id}/respond`：接受或拒绝邀请。
- `POST /api/assignments/{id}/review`：提交 1-5 分评审。
- `POST /api/papers/{id}/rebuttal`：作者提交一次 Rebuttal。
- `GET /api/papers/{id}/decision`：主席查看评审明细、均分与建议；作者在决定作出后（409 `decision_not_ready`）只看最终结论；评审人 403。
- `POST /api/papers/{id}/decision`：收到至少两份评审后作决定；请求体可带 `note` 与 `override_reason`。
- `GET /api/papers/{id}/history`：审计历史；作者侧隐藏评审身份与逐条评分。

## 决定建议与覆盖规则

建议计算独立放在 `recommendation.py`（纯函数），决定事务在 `ReviewStore.decide`，主席页面独立为 `web/chair.html`，三者分开维护。基于已完成评审的 1-5 分：

- 平均分不低于 4：建议 `accept`
- 平均分不高于 2：建议 `reject`
- 其余按较低分：较低分不低于 3 为 `minor_revision`，否则 `major_revision`

主席提交的决定与建议不一致时必须填写非空 `override_reason`，否则返回 422 `override_reason_required` 且决定不保存（事务回滚）。决定落库时一并留存 `average_score`、`suggested_decision`、`override_reason`。作者只能在决定作出后看到最终结论（决定与说明），看不到评审人身份、逐条评审意见、均分、建议与覆盖理由。

## 业务不变量

评审人不能查看未分配论文的作者身份；利益冲突禁止投标和分配；邀请和完成状态不能跳步；每位评审人的未完成分配受 `load_limit` 限制；每篇论文只能提交一次 Rebuttal；决定必须至少基于两份已完成评审；覆盖系统建议必须给出书面理由。
