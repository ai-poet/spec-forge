---
doc: iteration_log
version: 0.3.0
status: draft
created: 2026-05-26
owner: user
supersedes: docs/development_plan.md@0.1.0
---

# SpecForge 开发计划

## 已完成目标

1. 初始化 Git 仓库。
2. 建立 FastAPI + React 原型。
3. 用 LangGraph `StateGraph` 替换手写状态机。
4. 接入 SQLite checkpointer，并以 `iteration_id` 作为 `thread_id`。
5. 将设计审批和验证审批实现为 LangGraph interrupt/resume。
6. 将 README 和核心设计文档改为中文。
7. 增加项目级管理：左侧项目栏、项目创建、项目内 iteration 列表。
8. 前端重构为 `pages/`、`components/`、`hooks/` 分层。
9. 在前端展示 LangGraph 实时状态：当前业务状态、下一 graph 节点、节点进度条和事件流。
10. 将 LangGraph 执行移入本地后台 worker 队列，创建 iteration 不再阻塞 HTTP。
11. 接入 Planner/Tester JSON artifact schema，由后端校验并写入文档和测试。
12. 将 protected tests checksum gate 接入主流程。
13. 增加 Coder/Tester retry、Coder clarification、Planner verify reject 计数。
14. WebSocket 改为连接首包 snapshot + 后续事件驱动更新。
15. 增加项目级默认 mode、测试命令、模型名和 retry 上限配置。

## 下一步

1. 给 real-cli 增加 fixture 级真实 smoke test。
2. 引入容器或只读挂载，替代仅 checksum gate 的本地保护。
3. 接入 Cua MCP 或 Playwright 作为 UI 验证节点。
4. 增加 wall-clock circuit breaker。
5. 将迭代归档和 ADR 文档纳入前端控制台。
