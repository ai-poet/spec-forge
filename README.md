# SpecForge

SpecForge 是一个本地优先、文档驱动、测试优先的 agent 工程工作台。它面向真实开发者的使用方式：先输入一个大需求，再把需求拆成一个或多个可验证的 iteration，让系统自动执行 Planner、Coder、Tester 回环，直到实现通过测试并由人类确认交付。

核心层级：

```text
Project -> Epic -> Iteration -> Planner/Coder/Tester run
```

核心流程：

```text
大需求 -> 创建 Epic -> 创建 iteration -> Planner 产出文档和测试
-> 人类审批设计 -> Coder 实现 -> Tester 验证
-> 失败自动重试 / 阻断交给人类 -> 人类审批验证 -> 交付
```

## 现在做到什么程度

- 后端：FastAPI + SQLite。
- 编排：LangGraph `StateGraph` + SQLite checkpointer。
- 前端：React + Vite Developer Workbench。
- 项目管理：左侧 Projects + Epics，主区域展示当前大需求进度。
- Epic 层：一个大需求可以包含多个 iteration，并自动汇总 active、blocked、delivered 状态。
- 后台执行：本地单 worker 队列执行 LangGraph，创建 iteration 不阻塞 HTTP 请求。
- 实时状态：WebSocket 首包 snapshot，之后按事件推送，并在前端显示连接状态与自动重连。
- 运行模式：`dry-run` 稳定演示，`real-cli` 接入结构化 artifact 协议。
- 人类检查点：设计审批和验证审批通过 LangGraph interrupt/resume 推进。
- 治理：Planner/Tester artifact 由后端校验后写入；Coder 后执行 protected tests checksum gate。
- 开发者工作台：需要处理、摘要、文档、测试、日志、事件过滤、项目配置面板。
- 独立交付评审：Tester 除了验证测试，也会生成用户体验观察和后续交付建议。

## 为什么不是普通 coding agent

SpecForge 不把“聊天上下文”当作事实源。每轮迭代都落到本地文件系统和 SQLite：

- 文档是事实源。
- 测试先于实现。
- Planner、Coder、Tester 分离。
- 每个节点可以 fresh session 运行。
- 人类只在固定检查点审批，不需要每一步盯着。
- 大需求通过 Epic 聚合，避免多个小 iteration 散落在聊天记录里。

## 快速启动

推荐 Python 3.12。你可以用 conda 环境：

```bash
conda activate computer-use-py312
```

安装并启动：

```bash
./scripts/dev.sh
```

或者分别启动：

```bash
cd backend
python -m pip install -e ".[dev]"
uvicorn specforge.main:app --reload --port 8787
```

```bash
cd frontend
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:5178
```

## 基本使用方式

1. 在左侧创建或选择 Project。
2. 在 Project 下创建 Epic，填写大需求、验收标准和约束。
3. 在 Epic 下创建第一个 iteration，默认 goal 会带入 Epic 摘要。
4. 等待 Planner 生成设计、修改计划、测试计划和测试文件。
5. 在 Action Required 面板审批设计。
6. 等待 Coder/Tester 自动执行；失败时系统会按 retry 上限回环。
7. 在摘要、文档、测试、日志中查看结果。
8. 验证通过后审批交付，Epic 进度会自动更新。

## 当前工作流与原始边语义

当前实现仍保持四节点权责：

- Node 1：规划、测试计划、设计审批、验证报告机械复核。
- Node 2：只负责实现。
- Node 3：独立验证、失败反馈、交付建议。
- Node 4：UI Driver 尚未接入，保留为后续扩展。

实现上额外加入了 `integrity_check` 和 `planner_verify` 两个保护节点。前者保护 Planner 写出的测试不被 Coder 改掉，后者实现 Node 3 到 Node 1 的 verify report 复核边。

## 运行模式

### dry-run

默认模式。不会调用外部大模型 CLI，会生成确定性的设计文档、测试计划、示例代码和验证报告，适合开发控制台和验证 LangGraph 流程。

### real-cli

设置环境变量：

```bash
SPECFORGE_MODE=real-cli ./scripts/dev.sh
```

该模式会调用：

- `claude -p`：Planner / Coder
- `codex exec`：Tester

Planner/Tester 必须输出 JSON artifact，后端校验 schema 和路径白名单后落盘。Coder 可以编辑 iteration 工作区里的 `src/**`；如果 protected tests 被修改，流程会进入 `blocked`。

当前隔离仍是本地 MVP 级别，只用于可信工作区；容器、只读挂载和更强权限策略留到后续版本。

## 项目配置

每个项目可以配置：

- 默认运行模式和默认测试命令。
- Planner / Coder / Tester 模型名。
- Coder/Tester retry 上限。
- Coder clarification 上限。
- Planner verify reject 上限。

创建 iteration 时会继承项目配置；创建请求里的显式字段优先生效。

## 项目结构

```text
spec-forge/
├── backend/          # FastAPI + LangGraph
├── frontend/         # React Developer Workbench
├── docs/             # 系统设计和开发计划
├── scripts/dev.sh    # 本地启动脚本
└── .specforge/       # 本地运行数据，不进入 Git
```

前端源码按职责拆分：

```text
frontend/src/
├── pages/       # 页面级组合
├── components/  # 可复用 UI 面板
└── hooks/       # 数据加载和实时订阅
```

## 当前限制

- 单用户本地原型，无登录和多租户。
- v0.4 只支持手动创建 Epic；自动拆分大需求留到后续版本。
- `real-cli` 已有结构化输出协议，但还没有强文件系统隔离。
- UI Driver / Cua MCP 尚未接入。
- 生产部署、成本控制、量化成功标准留到后续版本。
