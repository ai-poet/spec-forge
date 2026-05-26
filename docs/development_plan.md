---
doc: iteration_log
version: 0.2.0
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

## 下一步

1. 强化 `real-cli` 模式的 prompt 和文件边界。
2. 引入测试文件 checksum 完整性校验。
3. 接入 Cua MCP 或 Playwright 作为 UI 验证节点。
4. 增加 retry counter 和 wall-clock circuit breaker。
5. 将迭代归档和 ADR 文档纳入前端控制台。
