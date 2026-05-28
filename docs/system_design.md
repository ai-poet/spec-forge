---
doc: system_design
version: 0.4.0
status: draft
created: 2026-05-28
owner: user
supersedes: docs/system_design.md@0.3.0
---

# SpecForge 系统设计

SpecForge 是一个本地 spec-first agent pipeline 和 Developer Workbench。它使用 LangGraph 负责编排，用 SQLite 保存业务状态和 LangGraph checkpoint，用 React 工作台展示 Project、Epic、Iteration、实时事件和人工审批动作。

## 目标

把自然语言业务目标转换为一个可追踪、可回环、可验证的本地工程过程：

1. Project 保存项目级配置和默认执行策略。
2. Epic 表示一个大需求，记录需求描述、验收标准和整体状态。
3. Iteration 表示一次可执行的工程回合。
4. Planner 产出 `system_design.md`、`modification_plan.md`、`testing_plan.md` 和测试骨架。
5. 人类审批设计后，Coder 实现代码。
6. Tester 验证实现并产出 `verify_report.md`。
7. 失败进入受限 retry 回环；阻断交给人类处理。
8. 人类最终审批后，iteration delivered，Epic 汇总进度同步更新。

## 数据层级

```text
Project
  -> Epic
      -> Iteration
          -> Documents / Runs / Events / LangGraph checkpoint
```

Epic 状态由关联 iteration 汇总：

- 无 iteration：`draft`
- 存在 active iteration：`active`
- 存在 blocked iteration：`blocked`
- 全部 delivered：`delivered`

## 与原始四节点拓扑的对应关系

当前实现没有偏离原始 Node 1/2/3/4 权责，但在 LangGraph 里加入了两个工程保护节点：

- `integrity_check`：位于 Coder 和 Tester 之间，对应“测试不可变性”约束。
- `planner_verify`：位于 Tester 和最终人工确认之间，对应“Node 3 -> Node 1 verify_report.md，Node 1 机械复核”。

边语义对应如下：

| 原始边 | 当前实现 |
|---|---|
| User ↔ Node 1 | Epic/Iteration 创建 + 设计审批 interrupt/resume |
| User ← Node 1 | `design_approval` 和 `verify_approval` 两个固定检查点 |
| Node 1 → Node 2 | Planner artifact 落盘后，设计审批通过进入 `coder` |
| Node 2 → Node 1 | `planner_clarification` 保留为受限澄清回路 |
| Node 2 ↔ Node 3 | `coder -> integrity_check -> tester -> coder` 的失败重试回路 |
| Node 3 → Node 4 | 尚未接入 Cua；v0.4 保留 UI 验收入口但未实现独立 UI Driver |
| Node 3 → Node 1 | `tester -> planner_verify`，验证报告由规划侧机械复核 |
| Node 1 → Node 2 | `planner_verify` 驳回后回到 `coder`，受 retry 上限控制 |

## 后端架构

- FastAPI 提供 HTTP API 和事件驱动 WebSocket。
- SQLite 保存 projects、epics、iterations、documents、events、runs。
- projects 表提供项目级配置；每个 iteration 继承项目默认 mode、测试命令、模型名和 retry 上限。
- epics 表提供大需求入口；iterations 通过 nullable `epic_id` 归属到 Epic。
- LangGraph `StateGraph` 保存真实流程状态。
- SQLite checkpointer 使用 `thread_id = iteration_id` 支持审批后 resume。
- 本地单 worker 队列执行 LangGraph，避免 real-cli 阻塞 HTTP 请求。
- EventBroker 在 `db.add_event(...)` 后向订阅者推送 snapshot/event。

图结构固定为：

```text
START
  -> planner
  -> design_approval interrupt
  -> coder
  -> integrity_check
  -> tester
  -> planner_verify
  -> verify_approval interrupt
  -> done
  -> END
```

Tester 失败会回到 Coder，受 `max_coder_tester_retries` 限制。Coder 可以请求 clarification，超出 `max_clarifications` 后进入 `blocked_user`。Planner 验证 verify report 失败可回到 Coder，受 `max_verify_rejects` 限制。

## API

Project API：

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{id}`
- `PATCH /api/projects/{id}`

Epic API：

- `GET /api/epics?project_id=...`
- `POST /api/epics`
- `GET /api/epics/{id}`
- `PATCH /api/epics/{id}`

Iteration API：

- `GET /api/iterations?project_id=...&epic_id=...`
- `POST /api/iterations`
- `GET /api/iterations/{id}`
- `POST /api/iterations/{id}/approve-design`
- `POST /api/iterations/{id}/approve-verify`
- `POST /api/iterations/{id}/stop`
- `GET /api/iterations/{id}/documents/{name}`
- `GET /api/iterations/{id}/runs/{run_id}/logs`

实时 API：

- `WS /ws/iterations/{id}`

## Artifact 和测试完整性

- Planner/Tester 在 `real-cli` 模式输出 JSON artifact。
- 后端校验 artifact schema 和路径白名单后写入 docs/tests/report。
- Planner 完成后生成 protected tests checksum baseline。
- Coder 后、Tester 后都会执行 checksum gate。
- `tests/adversarial/**` 允许 Tester 新增；unit/integration/ui 测试被改动会进入 `blocked`。
- Tester 不只输出 pass/fail，也作为独立交付评审者输出 `delivery_advice.md`，包括用户体验观察和后续交付建议。

## 前端架构

前端是一个面向开发者的工作台：

- 左侧栏分为 Projects 和 Epics。
- 主区域顶部展示当前 Epic 的标题、状态、进度、blocked 数和 delivered 数。
- 中间左列展示当前 Epic 的 iteration queue。
- 中间右侧展示当前 iteration 的工作区。
- Action Required 面板把技术状态翻译成开发者动作：审批设计、确认验证结果、处理阻断、系统处理中或已交付。
- Summary / Docs / Tests / Logs tabs 提供先摘要、后原文的查看方式。
- PipelineBoard 保留 LangGraph 技术态，作为辅助诊断视图。
- Timeline 支持 All、Decisions、Failures、Tests、Runs 过滤。
- WebSocket hook 展示 connecting、connected、reconnecting、disconnected 和最后消息时间。
- 项目配置移入 `Iterations | Config` 的 Config 页，不挤占主流程。

## 运行模式

`dry-run` 是默认模式，生成确定性产物，不调用外部 agent。

`real-cli` 模式调用：

- `claude -p` 作为 Planner / Coder
- `codex exec` 作为 Tester

v0.4 保证大需求工作台、结构化 artifact 消费、checksum gate、失败重试和事件驱动实时体验；不承诺容器级强隔离，也不自动拆分 Epic。
