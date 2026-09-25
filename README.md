# 学术会议同行评审系统

一个仅使用 Python 3.11+ 标准库的独立示例项目。SQLite 保存数据，`http.server` 提供 JSON API 和演示页面。

## 运行

```bash
python app.py --init --seed
python app.py
```

访问 <http://127.0.0.1:8101>，主席决定页面在 <http://127.0.0.1:8101/chair>。默认数据库为 `review.db`，端口为 `8101`。测试：

```bash
python -m unittest -v
```

## 模块划分

建议计算、决定事务与主席页面分开维护：

- `recommendation.py`：决定建议计算（纯函数，按评分给出建议结论）。
- `decisions.py`：决定事务（覆盖理由校验，均分、建议、覆盖理由随决定一起留存）。
- `web/chair.html`：主席页面（查看评审与建议、录入决定与覆盖理由）。
- `app.py`：存储、HTTP 路由与其余领域逻辑；`common.py` 存放共享基础（错误、时间戳、合法决定值）。

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
- `GET /api/papers/{id}/reviews`：主席查看已完成评审、平均分与系统建议。
- `POST /api/papers/{id}/decision`：主席作决定；决定与建议不一致时必须填写 `override_reason`，否则返回 422 且决定不保存。
- `GET /api/papers/{id}/decision`：主席查看完整决定记录；作者只能在决定后看到最终结论。
- `GET /api/papers/{id}/history`：审计历史（作者视图隐藏评审身份与逐条意见）。

## 决定建议规则

评定完成（至少两份已完成评审）后按平均分给出建议：

- 平均分不低于 4：建议接收（accept）；
- 平均分不高于 2：建议拒稿（reject）；
- 其余按较低分：较低分不低于 3 建议小修（minor_revision），否则建议大修（major_revision）。

主席可以选择不同结论，但必须填写覆盖理由；作决定时平均分、建议与覆盖理由随决定一起存入 `decisions` 表。

## 业务不变量

评审人不能查看未分配论文的作者身份；利益冲突禁止投标和分配；邀请和完成状态不能跳步；每位评审人的未完成分配受 `load_limit` 限制；每篇论文只能提交一次 Rebuttal；决定必须至少基于两份已完成评审；作者只能在决定后看到最终结论，看不到评审身份与逐条意见。
