# Incident Agent

Incident Agent 是一个面向研发和运维人员的故障初步分析助手。它接收故障标题、日志/现象和 DevAtlas 知识库 ID，由模型选择工具收集证据，再通过 LangGraph 编排流程并生成带来源的结构化报告。

## 项目边界

```text
DevAtlas（E:\RagKnowledgeSystem）
  文档、版本、切分、Embedding、Chroma、知识库权限和纯检索

Incident Agent（本项目）
  模型决策、工具编排、状态、轨迹、报告、降级和 Web Harness
```

Agent 只调用 DevAtlas 的纯检索接口，不调用 DevAtlas 已经包含 LLM 的故障分析接口，避免重复模型流程。

## 架构

```text
Vue Web 5174
    │ Bearer JWT
    ▼
FastAPI Agent API 8001
    ├── auth proxy ───────────────► DevAtlas /auth/me（8000）
    ├── LangGraph
    │     ├── agent → tools → observe → agent
    │     ├── report → END
    │     ├── degrade → END
    │     └── limit → END
    ├── DeepSeek
    ├── HttpRagGateway ───────────► DevAtlas /search（8000）
    └── Agent MySQL（incident_agent）
```

三个工具：

- `analyze_log`：提取 HTTP 502、超时、数据库错误等信号；
- `search_knowledge`：通过 DevAtlas 检索并保留 document/version/chunk 来源；
- `get_service_status`：查询 MVP 里的明确模拟服务状态。

## 目录

```text
app/
├── main.py
└── incident_agent/
    ├── core/          # 配置
    ├── db/            # SQLAlchemy Session 和 Base
    ├── models/        # AgentRun、AgentStep
    ├── schemas/       # API、工具、报告、RAG 契约
    ├── services/      # Agent 执行、LLM、存储、工具、RAG、鉴权
    ├── graph/         # State、节点和工作流
    └── routers/       # auth、incidents、runs
web/src/
├── api/ components/ layouts/ views/
├── router/ stores/ types/
└── App.vue
```

`stages/` 是学习和回归示例，保留但不作为正式模块导入。

## 环境准备

后端依赖安装：

```powershell
cd E:\IncidentAgent
py -m pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，填写本机数据库密码和 DeepSeek Key。不要把 `.env`、JWT 或密码提交到 Git。

前端依赖安装：

```powershell
cd E:\IncidentAgent\web
npm install
```

## 一键启动

双击：

```text
E:\IncidentAgent\One-click launch.bat
```

它会分别打开三个 PowerShell：

```text
DevAtlas 后端：8000
Incident Agent 后端：8001
Incident Agent Web：5174
```

也可以手动启动：

```powershell
cd E:\RagKnowledgeSystem
py -m uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
cd E:\IncidentAgent
$env:PYTHONPATH="E:\IncidentAgent"
py -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

```powershell
cd E:\IncidentAgent\web
npm run dev -- --host 127.0.0.1 --port 5174
```

## API

```text
GET  /health
GET  /health/db
POST /api/v1/auth/login
GET  /api/v1/auth/me
POST /api/v1/incidents/analyze
GET  /api/v1/runs
GET  /api/v1/runs/{run_id}
```

分析请求示例：

```json
{
  "title": "订单服务返回 502",
  "content": "order-service 日志显示 MySQL connection timeout",
  "knowledge_base_id": 3,
  "top_k": 5
}
```

`/api/v1/incidents/analyze` 必须携带 DevAtlas Bearer JWT。Agent 只在当前请求中转发 Token，不保存 Token。

## 验证

```powershell
cd E:\IncidentAgent
$env:PYTHONPATH="E:\IncidentAgent"
py -m pytest tests -q
py -m compileall -q app migrations tests
alembic check
ruff check app
```

前端构建：

```powershell
cd E:\IncidentAgent\web
npm run build
```

更完整的人工验收、演示步骤和限制见：

- `docs/阶段6验收清单.md`
- `docs/架构与演示.md`
- `docs/简历项目描述.md`
- `docs/agent-mvp设计.md`

## 当前状态

MVP 已完成：后端分层、独立 MySQL、DevAtlas 检索适配、LangGraph、工具失败降级、结构化报告、FastAPI 鉴权、Vue Web Harness 和一键启动。后续可继续增强 SSE、真实监控工具、评测和部署能力。
