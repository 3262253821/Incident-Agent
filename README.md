# Incident Agent

Incident Agent 是一个面向研发和运维人员的故障初步分析助手。它接收故障标题、日志/现象和（登录后从下拉里选择的）DevAtlas 知识库，由模型选择工具收集证据，再通过 LangGraph 编排流程并生成带来源的结构化报告。

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
GET  /api/v1/knowledge-bases
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

入参边界（超限或为空一律 `422`，**不会进入模型与工具**）：`title` 1–200 字、`content` 1–20 000 字、`knowledge_base_id > 0`、`top_k` 1–10；首尾空白先被去掉，所以纯空白的标题/内容同样按空值拒绝。

知识库下拉的数据来源：

```text
GET /api/v1/knowledge-bases
→ 200 [{"id": 4, "name": "DevAtlas 开发演示知识库", "description": "..."}]
```

这是 DevAtlas `GET /api/v1/knowledge-bases` 的**只读代理**：浏览器（5174）直连 DevAtlas（8000）会踩跨域，所以由 Agent 用同一个 Token 转发一次。DevAtlas 依旧按 Token 的 owner 过滤，Agent 不缓存、不落库、不重新签发 Token，也只下发 `id`/`name`/`description`（`owner_id` 与时间戳留在上游）。上游拒绝 → `401`（带 `WWW-Authenticate`），上游错误/不可达/响应形状不符 → `502`/`503`，账号下没有知识库则返回 `200 []`。前端登录后自动加载并默认选中第一项，因此不需要知道自己的知识库 ID。

历史接口的职责是分开的：

| 接口 | 返回 | 说明 |
| --- | --- | --- |
| `GET /api/v1/runs` | 一页 `RunSummary` | 只返回身份（`title`/`run_id`）、状态、计数、`started_at`/`completed_at`/`duration_ms` 与错误摘要；一次查询，不带 `observations` / `steps` / `report` |
| `GET /api/v1/runs/{run_id}` | `RunResponse` | 同一套时间字段 + 完整轨迹（`observations`、`steps`、`report`、`degraded_summary`），steps 用一次批量查询预加载 |

时间一律是带 `+00:00` 的 ISO 8601（存储是 naive UTC，偏移在 API 边界补上）；`duration_ms` 由服务端派生，**未结束或被中断回收的运行是 `null`**——被回收的记录里 `completed_at` 是下一次启动发现它的时刻，拿它算耗时等于把进程宕机时长当成分析耗时。前端据此显示"3 分钟前 · 耗时 8.4s"。

列表接口的查询参数（都作用在 `owner_user_id` 之内）：

```text
limit           1..100，默认 20
status          可重复：?status=degraded&status=max_iterations（未知状态返回 422）
started_after   包含边界（>=），ISO 8601；naive 输入按 UTC 解释
started_before  不含边界（<），ISO 8601
cursor          上一页返回的 next_cursor（不透明 token）
```

分页用**游标**而不是 offset：历史是不断新增的列表，用 offset 时"翻页期间新增一条记录"会让后续页重复或漏行；游标编码上一页最后一行的 `(started_at, id)`，下一页严格取更旧的那一段。响应形如 `{"items": [...], "next_cursor": "..."}`，`next_cursor` 为 `null` 表示到底。游标损坏返回 `400`，不会 500。

历史保留策略（默认关闭）：

```text
INCIDENT_RUN_RETENTION_DAYS=0    # 0 = 永不删除（默认，保护演示数据）
INCIDENT_RUN_RETENTION_DAYS=90   # 启动时删除 started_at 早于 90 天前的 run 及其 steps
```

判定依据是 `started_at`（而不是 `completed_at`），保留期是全局运维策略、不按用户区分；删除条数与保留天数会写进启动日志，作为删除操作的审计记录。

因此前端打开历史抽屉时先拉列表（点"加载更多"续拉下一页），点开某一条时再拉详情。两个接口都按 `owner_user_id` 过滤，猜中别人的 `run_id` 只会得到 404。

## 验证

```powershell
cd E:\IncidentAgent
py -m pytest tests -q                 # 不需要设置 PYTHONPATH：pyproject.toml 里已配 pythonpath
py -m compileall -q app migrations tests
alembic check                         # 需要本机 MySQL（CI 中跳过，见下）
ruff check .                          # 全仓检查
```

前端构建：

```powershell
cd E:\IncidentAgent\web
npm run build
```

### 依赖安装与环境复现

```powershell
py -m pip install -r requirements.txt        # 运行时依赖（版本下限）
py -m pip install -r requirements-lock.txt   # 精确锁定版本，CI 用这一份
py -m pip install -r requirements-dev.txt    # 测试与 lint（ruff、pytest）
```

`requirements.txt` 只写下限，方便 GitHub 的依赖安全告警对着它工作；**可复现安装用 `requirements-lock.txt`**——它是本机通过全部测试的精确版本组合，CI 也按它安装。后端测试全部使用 SQLite 内存库，因此**离线即可运行**，不需要 MySQL。

### CI

`.github/workflows/ci.yml` 在 push 与 PR 时执行：

```text
后端：pip install -r requirements-lock.txt -r requirements-dev.txt
      ruff check . / pytest -q / compileall / alembic heads
前端：npm ci / npm run build（含 vue-tsc 类型检查）
```

`alembic heads` 只校验迁移脚本可被解析且只有一个 head；真正比对数据库与模型的 `alembic check` 需要 MySQL，放在本机执行。

更完整的人工验收、演示步骤和限制见：

- `docs/阶段6验收清单.md`
- `docs/架构与演示.md`
- `docs/简历项目描述.md`
- `docs/agent-mvp设计.md`

## 当前状态

MVP 已完成：后端分层、独立 MySQL、DevAtlas 检索适配、LangGraph、工具失败降级、结构化报告、FastAPI 鉴权、Vue Web Harness 和一键启动。后续可继续增强 SSE、真实监控工具、评测和部署能力。
