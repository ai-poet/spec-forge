# SpecForge

SpecForge 是一个本地优先、文档驱动、测试优先的 agent 工程流水线。它把一句业务目标转换成可追踪的设计文档、修改计划、测试计划、代码实现和验证报告。

核心流程：

```text
目标 -> Planner 产出文档和测试 -> 人类审批设计 -> Coder 实现 -> Tester 验证 -> 人类审批验证 -> 交付
```

## 现在做到什么程度

- 后端：FastAPI + SQLite
- 编排：LangGraph `StateGraph` + SQLite checkpointer
- 前端：React + Vite 控制台
- 项目管理：侧边栏添加项目，每个项目有独立流水线列表
- 后台执行：本地单 worker 队列执行 LangGraph，创建 iteration 不阻塞 HTTP 请求
- 实时状态：WebSocket 连接后先发 snapshot，之后按事件推送更新
- 模式：`dry-run` 可本地稳定演示，`real-cli` 接入结构化 artifact 协议
- 人类检查点：设计审批和验证审批通过 LangGraph interrupt/resume 推进
- 治理：Planner/Tester artifact 由后端校验后写入；Coder 后会做 protected tests checksum gate

## 为什么不是普通 coding agent

SpecForge 不把“聊天上下文”当作事实源。每轮迭代都落到本地文件系统和 SQLite：

- 文档是事实源
- 测试先于实现
- Planner、Coder、Tester 分离
- 每个节点可以 fresh session 运行
- 人类只在固定检查点审批，不需要每一步盯着

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

- 默认运行模式和默认测试命令
- Planner / Coder / Tester 模型名
- Coder/Tester retry 上限
- Coder clarification 上限
- Planner verify reject 上限

创建 iteration 时会继承项目配置；创建请求里的显式字段优先生效。

## 项目结构

```text
spec-forge/
├── backend/          # FastAPI + LangGraph
├── frontend/         # React 控制台
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
- `real-cli` 已有结构化输出协议，但还没有强文件系统隔离。
- UI Driver / Cua MCP 尚未接入。
- 生产部署、成本控制、量化成功标准留到后续版本。
