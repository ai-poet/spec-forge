---
doc: system_design
version: 0.3.0
status: draft
created: 2026-05-26
owner: user
supersedes: docs/system_design.md@0.1.0
---

# SpecForge 系统设计

SpecForge 是一个本地 spec-first agent pipeline。它使用 LangGraph 负责编排，用 SQLite 保存业务状态和 LangGraph checkpoint，用 React 控制台展示项目、迭代、实时事件和审批状态。

## 目标

把自然语言业务目标转换为：

1. Planner 产出的 `system_design.md`、`modification_plan.md`、`testing_plan.md` 和测试骨架
2. 人类审批后的 Coder 实现
3. Tester 产出的 `verify_report.md`
4. 人类最终审批后的 delivered 状态

## 后端架构

- FastAPI 提供 HTTP API 和事件驱动 WebSocket。
- SQLite 保存 projects、iterations、documents、events、runs。
- projects 表提供项目级配置；每个 iteration 继承项目默认 mode、测试命令、模型名和 retry 上限。
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

## Artifact 和测试完整性

- Planner/Tester 在 `real-cli` 模式输出 JSON artifact。
- 后端校验 artifact schema 和路径白名单后写入 docs/tests/report。
- Planner 完成后生成 protected tests checksum baseline。
- Coder 后、Tester 后都会执行 checksum gate。
- `tests/adversarial/**` 允许 Tester 新增；unit/integration/ui 测试被改动会进入 `blocked`。

## 前端架构

前端是一个本地操作控制台：

- 左侧创建和选择 project
- 项目配置面板编辑 mode、测试命令、模型名和 retry 上限
- 项目下创建和选择 iteration
- 中间显示 pipeline 状态
- 文档面板展示 Planner/Tester 产物
- Timeline 展示事件流和失败原因
- 审批按钮调用后端 resume LangGraph

## 运行模式

`dry-run` 是默认模式，生成确定性产物，不调用外部 agent。

`real-cli` 模式调用：

- `claude -p` 作为 Planner / Coder
- `codex exec` 作为 Tester

v0.3 保证结构化 artifact 消费、checksum gate 和失败重试；不承诺容器级强隔离。
