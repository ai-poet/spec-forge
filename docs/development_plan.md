---
doc: iteration_log
version: 0.6.0
status: draft
created: 2026-05-28
owner: user
supersedes: docs/development_plan.md@0.4.0
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
16. 新增 Epic 大需求层：Project -> Epic -> Iteration。
17. 后端提供 Epic CRUD API，并让 iteration 可归属到 Epic。
18. Epic 状态按关联 iteration 自动汇总 draft、active、blocked、delivered。
19. 前端改造为 Developer Workbench：左侧 Projects + Epics，主区域展示当前 Epic。
20. 新增 Action Required 面板，把 LangGraph 技术状态翻译成人类动作。
21. 新增 Summary-first iteration 工作区：Summary、Docs、Tests、Logs。
22. Timeline 增加 Decisions、Failures、Tests、Runs 过滤。
23. WebSocket hook 增加连接状态、最后消息时间和指数退避重连。
24. 项目配置迁移到 Config tab，避免挤占 iteration 主流程。
25. Tester artifact 扩展为验证报告、用户体验观察和交付建议。
26. 前端主要用户可见文案改为中文，并保留必要的运行模式原值。
27. 接入 Cua UI Driver：Tester 扫描 `docs/tests/ui/*.json`，通过 `cua-driver` CLI 执行 Web / Native UI trajectory。
28. Cua 不可用时 Web UI 由 Playwright 回退执行（`ui_driver.fallback`）；native UI 或未安装 Playwright 时记为 `ui_driver.warning`；UI assertion 失败时记为非阻断 warning，交付门槛以 Tester 代码审查无 P0/P1 缺陷为准。
29. 新增 `ui_results.json`、`ui_report.md`、UI artifact 只读 API 和前端 UI 验证面板。
30. 调整测试完整性：`tests/ui/recordings/**` 不纳入 protected checksum baseline。

## 当前验收范围

- 创建 Project。
- 在 Project 下创建 Epic。
- 在 Epic 下创建 dry-run iteration。
- 审批设计后自动进入 Coder/Tester。
- 验证审批后 iteration delivered。
- Epic 进度同步变为 delivered / 100%。
- Summary、Docs、Tests、Logs 和 Timeline 都能读取当前 iteration 的状态。
- Tester 通过后生成 `delivery_advice.md`，摘要面板显示用户体验观察和后续建议。
- Planner 定义 UI trajectory 时，Tester 能调用 Cua Driver 或生成 warning，并把 UI 结果展示在 Tests tab。

## 下一步

1. 自动把 Epic 拆成多个 iteration，并允许用户编辑拆分计划后批量启动。
2. 给 real-cli 增加 fixture 级真实 smoke test。
3. 引入容器或只读挂载，替代仅 checksum gate 的本地保护。
4. 为 UI Driver 增加 MCP transport，并补充更强的视觉断言能力。
5. 增加 wall-clock circuit breaker。
6. 将迭代归档和 ADR 文档纳入前端控制台。
