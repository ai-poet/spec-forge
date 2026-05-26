---
doc: system_design
version: 0.2.0
status: draft
created: 2026-05-26
owner: user
supersedes: docs/system_design.md@0.1.0
---

# SpecForge 系统设计

SpecForge 是一个本地 spec-first agent pipeline。它使用 LangGraph 负责编排，用 SQLite 保存业务状态和 LangGraph checkpoint，用 React 控制台展示迭代状态。

## 目标

把自然语言业务目标转换为：

1. Planner 产出的 `system_design.md`、`modification_plan.md`、`testing_plan.md` 和测试骨架
2. 人类审批后的 Coder 实现
3. Tester 产出的 `verify_report.md`
4. 人类最终审批后的 delivered 状态

## 后端架构

- FastAPI 提供 HTTP API 和 WebSocket 快照。
- SQLite 保存 iterations、documents、events、runs。
- projects 表提供项目级管理；每个 iteration 归属一个 project。
- LangGraph `StateGraph` 保存真实流程状态。
- SQLite checkpointer 使用 `thread_id = iteration_id` 支持审批后 resume。

图结构固定为：

```text
START
  -> planner
  -> design_approval interrupt
  -> coder
  -> tester
  -> verify_approval interrupt
  -> done
  -> END
```

任何 CLI 节点失败都会进入 `blocked`，记录 run 日志和失败事件。

## 前端架构

前端是一个本地操作控制台：

- 左侧创建和选择 project
- 项目下创建和选择 iteration
- 中间显示 pipeline 状态
- 文档面板展示 Planner/Tester 产物
- Timeline 展示事件流
- 审批按钮调用后端 resume LangGraph

## 运行模式

`dry-run` 是默认模式，生成确定性产物，不调用外部 agent。

`real-cli` 模式调用：

- `claude -p` 作为 Planner / Coder
- `codex exec` 作为 Tester

v0.2 只保证命令适配和错误记录，不承诺强隔离。
