# Incident Agent

面向研发与运维的**故障初步分析 Agent**：输入故障标题和日志，由模型自主选择工具收集证据，再用 LangGraph 编排「分析 → 报告」流程，产出一份**带来源、可回溯**的结构化报告，并保留完整的执行轨迹。

> **项目状态**：MVP 已完成并在本地跑通。三个服务（DevAtlas 8000、Agent 8001、Web 5174）可一键启动，
> 后端 **381** 条测试、前端 **137** 条测试全部通过。
> 本文所有描述以当前代码为准，未实现的能力统一放在[当前限制与规划](#当前限制与规划)，不会被描述成已具备。

## 这是什么，解决什么问题

线上出故障时，排查的第一步往往最耗时：日志要人肉看，历史工单和知识库要翻好几个地方，最后拼出来的结论还没有出处可查。

Incident Agent 把这一步交给模型，但**不把判断权完全交给模型**：

- 模型只能通过**三个受控工具**获取信息，不能凭空编造；
- 报告里的每条证据都要能在本次运行的**工具观察结果**里找到对应，对不上的会被挑出来放进 `unverified_evidence`；
- 工具失败时不是直接报错，而是**降级**成一份基于真实已得事实的摘要，并给出错误码和下一步建议；
- 整条轨迹（每轮模型请求、每次工具调用、每个错误）都落库，事后可以回答「这条结论是怎么来的」。

## 与 DevAtlas 的职责边界

本项目是 [`DevAtlas`](https://github.com/3262253821/DevAtlas) 的上层应用，两者**必须配合运行**。边界是刻意划清的：

| | DevAtlas | Incident Agent（本项目） |
| --- | --- | --- |
| 定位 | 版本化 RAG 知识协同平台 | 故障初步分析 Agent |
| 负责 | 文档解析切分、Embedding、Chroma 向量、版本管理、owner 权限、**纯检索** | 模型决策、工具编排、状态机、轨迹、报告、降级、Web Harness |
| 存储 | MySQL(业务事实) + Chroma(向量) | 独立 MySQL(`incident_agent`) |

**Agent 只调用 DevAtlas 的纯检索接口 `/search`，不调用它已经内含 LLM 的故障分析接口**，避免一次请求里跑两套模型流程。反过来，DevAtlas 不知道 Agent 的存在，可以独立使用。

## 架构

```text
Vue Web 5174
    │ Bearer JWT
    ▼
FastAPI Agent API 8001
    ├── auth proxy ───────────────► DevAtlas /auth/me（8000）
    ├── LangGraph
    │     ├── agent → tools → observe → agent
    │     ├── report  → END
    │     ├── degrade → END
    │     └── limit   → END
    ├── DeepSeek（OpenAI 兼容接口）
    ├── HttpRagGateway ───────────► DevAtlas /search（8000）
    └── Agent MySQL（incident_agent）
```

各层职责：

| 组件 | 职责 |
| --- | --- |
| Vue 3 Web | 登录、分析表单、知识库下拉、报告与轨迹展示、运行历史抽屉 |
| FastAPI | HTTP 接口、JWT 鉴权、参数校验、业务编排、统一错误响应 |
| LangGraph | Agent 状态机：模型轮次、工具调用、条件边与循环保护 |
| DeepSeek | 决定调用哪些工具、生成最终报告 JSON |
| HttpRagGateway | 用同一个 Token 转发检索请求到 DevAtlas，校验响应形状 |
| Agent MySQL | `agent_runs` / `agent_steps` 两张表，保存运行与轨迹 |

## 三个工具

模型可以调用的全部能力，只有这三个，契约统一（`schemas/tool.py`）：

| 工具 | 作用 | 说明 |
| --- | --- | --- |
| `analyze_log` | 从日志里提取 HTTP 502、超时、数据库错误等信号 | 纯本地正则提取，带 `matched_text` 与 `line_number` |
| `search_knowledge` | 通过 DevAtlas 检索知识库 | 只调 `/search`，保留 document / version / chunk 来源 |
| `get_service_status` | 查询服务状态 | MVP 中是**明确标注的模拟数据**，不接真实监控 |

## LangGraph 工作流

```text
agent（请求模型，可返回多个 tool_calls）
  │
  ├── 有 tool_calls ──► tools（ToolNode 执行）──► observe（整理 ToolMessage 为业务事实）
  │                                                    │
  │                          ┌─────────────────────────┘
  │                          ├── 有工具失败 ──► degrade ──► END
  │                          └── 全部成功 ──► 回到 agent
  │
  ├── 无 tool_calls ──► report ──► END
  └── 超过 max_iterations ──► limit ──► END
```

条件边集中在 `graph/workflow.py`，节点实现集中在 `graph/nodes.py`。`report` 节点会解析 JSON → 用 `IncidentReport` 校验 → 做证据核验，任一步失败都转到 `report_validation_failed` 状态而不是抛异常。

### State 中的三类数据

这三者被有意分开，混在一起是这类项目最常见的设计错误：

| 字段 | 用途 | 面向 |
| --- | --- | --- |
| `messages` | LangChain 消息协议，给模型继续推理用 | 模型 |
| `observations` | 工具结果整理后的**业务事实** | 报告与降级摘要 |
| `steps` | 节点、工具、错误的审计轨迹 | 人和前端 |

`iteration` 只统计**模型请求轮数**：一轮返回三个 `tool_calls` 仍然只算一次。

### 运行状态

状态常量只有一份（`core/statuses.py`），前后端和数据库共用，避免各写一套字符串：

```text
running                     run 记录已创建，图还没跑完
completed                   报告校验通过，且有成功的工具观察结果支撑
insufficient_evidence       报告校验通过，但没有任何成功的工具观察结果
degraded                    工具失败，或模型/外部依赖不可用
report_validation_failed    报告节点没能产出合法报告
max_iterations              模型请求预算耗尽
tool_failed                 仅内部使用，对外统一映射为 degraded
```

## 降级与错误处理

这是本项目最值得讲的部分。**Agent 不允许把 SDK 异常直接抛给用户**——那些消息里可能有请求 URL、key 前缀或 traceback。

模型与依赖异常统一映射成一个小词表（`core/errors.py`），并配一句固定文案：

```text
MODEL_TIMEOUT / MODEL_RATE_LIMITED / MODEL_UNAVAILABLE / MODEL_AUTH_ERROR
MODEL_INVALID_REQUEST / MODEL_ERROR / REQUEST_TIMEOUT / AGENT_INTERNAL_ERROR
```

降级时不是只剩一个错误字符串，而是由 `DegradedSummary` 拼出一份**不含模型**的确定性摘要，告诉用户「已经确定了什么」：

- 真实命中的日志信号（含匹配文本与行号）；
- 真实检索到的知识库来源（document / version / chunk / filename）；
- 错误码 + 可执行的下一步建议。

## 证据核验与防幻觉

报告不是模型说什么就信什么：

- `IncidentReport` 用 `extra="forbid"` 严格校验，字段和枚举值都在 `schemas/incident.py` 里写死；
- 报告里每条 evidence 必须在本次运行的 observations 里找到对应，对不上的移到 `unverified_evidence`（该字段**只由服务端填**，模型无法伪造）；
- 没有成功观察结果时，状态是 `insufficient_evidence`，不会假装有结论；
- 外部内容（日志、检索到的文档片段）经过**定界与注入中和**后才进 Prompt，降低 Prompt Injection 风险。

## 技术栈

| 层次 | 选型 |
| --- | --- |
| 后端 | Python 3.13、FastAPI、Uvicorn、Pydantic v2 |
| Agent 编排 | LangGraph、LangChain Core / OpenAI |
| 模型 | DeepSeek（OpenAI 兼容接口，`langchain-openai`） |
| 数据库 | MySQL 8、SQLAlchemy 2、PyMySQL、Alembic |
| HTTP 客户端 | httpx |
| 前端 | Vue 3、TypeScript、Vite 6、Pinia、Vue Router、Axios、lucide-vue-next |
| 前端测试 | Vitest 3 + @vue/test-utils + jsdom |
| 后端测试 | pytest（**全部使用 SQLite 内存库，离线可跑**） |
| 代码质量 | ruff（lint + format） |
| CI | GitHub Actions，后端 + 前端两个 job |

## 项目结构

```text
IncidentAgent
├── app/
│   ├── main.py                      # FastAPI 入口、CORS、健康检查、启动期回收
│   └── incident_agent/
│       ├── core/                    # 配置、错误码词表、状态常量、日志、分页、脱敏
│       ├── db/                      # SQLAlchemy Base / Engine / Session
│       ├── models/                  # agent_runs、agent_steps
│       ├── schemas/                 # API、工具、报告、RAG 契约
│       ├── services/                # 编排、LLM、存储、工具、RAG 网关、鉴权、授权
│       ├── graph/                   # state、nodes、workflow、报告 JSON、证据、截止时间
│       └── routers/                 # auth、incidents、knowledge-bases、runs
├── migrations/versions/             # Alembic 迁移
├── stages/                          # L2~L5 学习与回归示例（保留，不作为正式模块导入）
├── scripts/                         # start-devatlas / start-agent / start-web / check-services
├── tests/                           # 31 个后端测试文件
├── web/
│   ├── src/{api,components,layouts,router,stores,types,views}
│   └── tests/                       # 12 个 Vitest 测试文件
├── docs/                            # 设计文档、交接文档、验收清单等
├── One-click launch.bat             # 一键启动三个服务
└── pyproject.toml                   # ruff + pytest 配置
```

## 快速开始

### 前置条件

| 依赖 | 版本 | 用途 |
| --- | --- | --- |
| Python | 3.13 | 后端 |
| Node.js | 20+ | 前端 |
| MySQL | 8.x | Agent 独立库（DevAtlas 另有一个库） |
| DevAtlas | 已跑在 `8000` | **必需**，提供登录与检索 |
| DeepSeek API Key | — | 生成分析与报告 |

### 1. 启动 DevAtlas（另一个仓库）

```powershell
cd <DevAtlas 目录>
py -m uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8000
```

确认 `http://127.0.0.1:8000/health` 返回正常，且账号下有 **`indexed` 状态**的文档，否则检索会没结果。

### 2. 配置并启动 Agent 后端

```powershell
cd <IncidentAgent 目录>
Copy-Item .env.example .env      # 填写本机 MySQL 密码与 DeepSeek Key
py -m pip install -r requirements.txt

# 创建 Agent 独立数据库
mysql -u root -p -e "CREATE DATABASE incident_agent DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
alembic upgrade head

py -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### 3. 启动前端

```powershell
cd web
npm install
npm run dev -- --host 127.0.0.1 --port 5174
```

### 4. 一键启动（Windows）

双击 `One-click launch.bat`，它会各开一个 PowerShell 启动三个服务，并**跳过已占用端口**（`netstat` 检测到 `LISTENING` 就不重复启动）。

> ⚠️ 该脚本里的 `INCIDENT_ROOT` / `DEVATLAS_ROOT` 是绝对路径常量，换机器需要按实际目录修改
> `One-click launch.bat` 与 `scripts/*.ps1`。

### 服务地址

| 服务 | 地址 |
| --- | --- |
| Agent Web | http://127.0.0.1:5174 |
| Agent API 健康检查 | http://127.0.0.1:8001/health 、`/health/db` |
| Agent Swagger | http://127.0.0.1:8001/docs |
| DevAtlas（依赖） | http://127.0.0.1:8000 |

登录使用 **DevAtlas 的账号**（Agent 不做独立用户体系）。DevAtlas 的演示账号可用
`backend/scripts/seed_dev_data.py` 生成。

## 配置说明

全部配置都在 `.env`（模板见 `.env.example`，**永远不要提交真实密钥**）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `INCIDENT_AGENT_HOST` / `_PORT` | `127.0.0.1` / `8001` | Agent 监听地址 |
| `INCIDENT_DB_HOST` / `_PORT` / `_NAME` / `_USER` / `_PASSWORD` | `127.0.0.1` / `3306` / `incident_agent` / `root` / — | Agent 独立 MySQL |
| `INCIDENT_DATABASE_URL` | 空 | 给了就直接用，覆盖上面的分项拼装（CI 用 `sqlite+pysqlite:///:memory:`） |
| `DEVATLAS_BASE_URL` | `http://127.0.0.1:8000` | 上游知识库服务 |
| `DEVATLAS_TIMEOUT_SECONDS` | `20` | 检索请求超时 |
| `DEEPSEEK_API_KEY` | — | **必填**，只放本地 |
| `INCIDENT_AGENT_MODEL` | `deepseek-chat` | 主模型 |
| `INCIDENT_AGENT_REPORT_MODEL` | 同主模型 | 报告节点可单独指定模型 |
| `INCIDENT_AGENT_TEMPERATURE` | `0.1` | 低温度，减少自由发挥 |
| `INCIDENT_AGENT_MAX_TOKENS` | 空 | 空表示不限制 |
| `INCIDENT_MODEL_TIMEOUT_SECONDS` | `30` | 单次模型调用超时，**不沿用 SDK 默认的 600 秒** |
| `INCIDENT_MODEL_MAX_RETRIES` | `0` | 默认不重试，失败立即归一化为 `MODEL_*` 错误码 |
| `INCIDENT_REQUEST_TIMEOUT_SECONDS` | `90` | 整次分析的时间预算，需小于前端 axios 的 120 秒 |
| `INCIDENT_MAX_ITERATIONS` | `4` | 模型请求轮数上限 |
| `INCIDENT_DEFAULT_TOP_K` | `5` | 请求未传 `top_k` 时的默认检索条数 |
| `INCIDENT_RUN_RETENTION_DAYS` | `0` | `0` = 永不删除（保护演示数据） |
| `INCIDENT_WEB_ORIGINS` | `http://127.0.0.1:5174` | CORS 白名单，逗号分隔 |
| `INCIDENT_LOG_LEVEL` / `_FORMAT` | `INFO` / `json` | 结构化日志，`text` 更适合本地阅读 |

**超时是刻意收紧的**：一次请求的时间预算 `90s` < 前端 axios `120s` < 单次模型调用 `30s` × 轮数，
这样最坏情况下后端先返回一个可读错误，而不是让前端先超时、用户看到一个没有解释的失败。

## API

除健康检查外都需要 `Authorization: Bearer <DevAtlas access_token>`。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/health` | 存活检查，**不依赖 MySQL 和 DevAtlas** |
| GET | `/health/db` | Agent 自己的 MySQL 连通性，失败返回 `503` |
| POST | `/api/v1/auth/login` | 转发登录到 DevAtlas，返回 JWT |
| GET | `/api/v1/auth/me` | 转发查询当前用户 |
| GET | `/api/v1/knowledge-bases` | 知识库下拉的**只读代理** |
| POST | `/api/v1/incidents/analyze` | 执行一次故障分析 |
| GET | `/api/v1/runs` | 运行历史列表（游标分页） |
| GET | `/api/v1/runs/{run_id}` | 单次运行详情（含完整轨迹与报告） |

### 分析请求

```json
{
  "title": "订单服务返回 502",
  "content": "order-service 日志显示 MySQL connection timeout",
  "knowledge_base_id": 4,
  "top_k": 5
}
```

入参边界（超限或为空一律 `422`，**不会进入模型与工具**）：`title` 1–200 字、`content` 1–20 000 字、
`knowledge_base_id > 0`、`top_k` 1–10（可省略）。首尾空白会先被去掉，因此**纯空格**的标题或内容按空值拒绝。

### 为什么要有 `/api/v1/knowledge-bases`

浏览器（5174）直连 DevAtlas（8000）会踩跨域，所以由 Agent 用同一个 Token 转发一次：

- DevAtlas 依旧按 Token 的 owner 过滤，Agent **不缓存、不落库、不重新签发 Token**；
- 只下发 `id` / `name` / `description`，`owner_id` 与时间戳留在上游；
- 上游拒绝 → `401`（带 `WWW-Authenticate`），上游错误/不可达/响应形状不符 → `502` / `503`，账号下没有知识库返回 `200 []`。

因此前端登录后自动加载并默认选中第一项，**用户不需要知道自己的知识库 ID**。

### 历史接口的职责划分

| 接口 | 返回 | 说明 |
| --- | --- | --- |
| `GET /runs` | 一页 `RunSummary` | 只有身份（`title`/`run_id`）、状态、计数、时间字段与**截断到 240 字**的错误摘要；一次查询，不带 `observations`/`steps`/`report` |
| `GET /runs/{run_id}` | `RunResponse` | 同一套时间字段 + 完整轨迹（`observations`、`steps`、`report`、`degraded_summary`） |

`steps` 与 `POST /incidents/analyze` 的响应**同形状**（11 个字段，含 `step_index`），只有一份公开字段定义。

**时间一律是带 `+00:00` 的 ISO 8601**：存储是 naive UTC（MySQL `DATETIME` 不保存时区），偏移量在 API 边界补上，
否则前端会把 UTC 墙上时间当本地时间解析。`duration_ms` 由服务端派生，**被中断回收的运行是 `null`**——
那些记录的 `completed_at` 是下一次启动发现它的时刻，拿它算耗时等于把进程宕机时长当成分析耗时。

列表查询参数（都作用在 `owner_user_id` 之内）：

```text
limit           1..100，默认 20
status          可重复：?status=degraded&status=max_iterations（未知状态返回 422）
started_after   包含边界（>=），ISO 8601；naive 输入按 UTC 解释
started_before  不含边界（<），ISO 8601
cursor          上一页返回的 next_cursor（不透明 token）
```

分页用**游标**而不是 offset：历史是不断新增的列表，用 offset 时「翻页期间新增一条记录」会让后续页重复或漏行。
游标编码上一页最后一行的 `(started_at, id)`，响应形如 `{"items": [...], "next_cursor": "..."}`，
`next_cursor` 为 `null` 表示到底；游标损坏返回 `400`，不会 `500`。

## 鉴权与权限隔离

- Agent **不做独立用户体系**，登录直接转发给 DevAtlas，用它的 JWT；
- Agent **只在当前请求内转发 Token，不保存 Token、不落库**；
- `owner_user_id` 一律由服务端从当前用户推导，**不信任客户端传入的值**；
- 运行记录的查询与删除都叠加 owner 条件，猜中别人的 `run_id` 只会得到 `404`，不泄露记录是否存在；
- 统一错误响应包含安全文案 + `error_code` + `request_id`，服务端日志带同一个 `request_id`，可端到端排查。

## 前端页面

| 路由 | 说明 |
| --- | --- |
| `/login` | 登录（`guestOnly`：已登录会跳回工作台） |
| `/` | 重定向到 `/workspace` |
| `/workspace` | 分析工作台（`requiresAuth`） |

路由守卫**只判断本地有没有令牌，不判断令牌是否有效**：令牌真失效时，任意一个接口都会返回 `401`，
由响应拦截器统一清掉令牌并跳转到带 `redirect` 的登录页。这样避免每次导航都多打一次接口。

工作台包含：故障表单、知识库下拉、执行轨迹（`ExecutionTrace`）、报告面板（`ReportPanel`）、
降级面板（`DegradedPanel`）、历史抽屉（`HistoryDrawer`，含筛选与重跑）以及无障碍播报（`StatusAnnouncer`）。

## 验证与测试

```powershell
# 后端
py -m pytest tests -q                 # 不需要设置 PYTHONPATH：pyproject.toml 已配 pythonpath
py -m ruff check .
py -m compileall -q app migrations tests
alembic heads                         # CI 跑这个；真正的 alembic check 需要 MySQL，放本机

# 前端
cd web
npm run build                         # 等价于 vue-tsc -b && vite build（含类型检查）
npm run test                          # 等价于 vitest run（jsdom，不需要浏览器）
```

本机实测结果：

| 命令 | 结果 |
| --- | --- |
| `py -m pytest tests -q` | **381 passed**（约 11 秒） |
| `npm run test` | **137 passed / 12 files** |
| `npm run build` | 成功，1669 modules transformed，JS 产物 195.29 kB（gzip 72.39 kB） |
| `py -m ruff check .` | All checks passed! |
| `py -m compileall -q app migrations tests` | 通过，退出码 0 |

**后端测试全部使用 SQLite 内存库，因此离线即可运行，不需要 MySQL。**

覆盖范围包括：图工作流与条件边、工具失败与降级摘要、报告证据核验与修复、输入边界、鉴权与
跨用户 404、历史游标分页与时间字段、中断记录回收、步骤持久化幂等、脱敏、不可信内容中和、
模型超时与错误码映射、前后端契约类型一致性，以及后端与 CI 工作流本身的守门测试。

### 依赖安装与环境复现

```powershell
py -m pip install -r requirements.txt        # 运行时依赖（版本下限）
py -m pip install -r requirements-lock.txt   # 精确锁定版本，CI 用这一份
py -m pip install -r requirements-dev.txt    # ruff、pytest
```

`requirements.txt` 只写下限，方便 GitHub 的依赖安全告警对着它工作；**可复现安装用 `requirements-lock.txt`**。

### CI

`.github/workflows/ci.yml` 在 push 到 `main` 与 PR 时执行两个 job：

```text
backend  ：ruff check . / pytest -q / compileall / alembic heads
frontend ：npm ci / npm run build（含 vue-tsc 类型检查）/ npm run test
```

CI 里显式设置了 `INCIDENT_DATABASE_URL: "sqlite+pysqlite:///:memory:"`。原因是检出目录里**没有 `.env`**，
而 `core/config.py` 在缺少数据库配置时会强制要求 `INCIDENT_DB_USER/_PASSWORD/_NAME` 并抛 `RuntimeError`，
导致全部测试在**收集阶段**就失败。`tests/test_ci_workflow.py` 守住这一条。

## 演示流程

**正常演示**：登录 → 等知识库下拉自动加载 → 输入「订单服务返回 502」+ MySQL 超时日志 → 开始分析。
预期：`completed`，有报告、来源引用、`observations` 和 `steps`。

**降级演示**：把日志改成要求查询不存在的 `gateway` 服务。预期：

```text
get_service_status → UNKNOWN_SERVICE
status      → degraded
report      → null
observations 保留已获得的工具结果 + 确定性降级摘要
```

也可以中途停掉 DevAtlas，验证检索工具返回 `RAG_NETWORK_ERROR` / `RAG_UNAVAILABLE` 后安全降级、不泄露 traceback。

## 常见问题

**Q：启动 Agent 直接报缺少配置或数据库连不上？**
`core/config.py` 在没有任何数据库配置时是**强制要求** `INCIDENT_DB_USER/_PASSWORD/_NAME` 的。
确认 `.env` 已从 `.env.example` 复制并填写，且 `incident_agent` 库已创建、`alembic upgrade head` 已执行。

**Q：接口返回 `401`？**
Agent 用的是 DevAtlas 的 Token。确认 DevAtlas 在跑、账号密码正确、Token 没过期。前端会自动清 Token 并跳登录页。

**Q：分析结果里没有知识库来源？**
去 DevAtlas 确认该知识库的文档版本是 `indexed`（不是 `pending` / `failed`）。没有召回内容时 Agent 不会编造引用。

**Q：状态是 `insufficient_evidence` 或 `degraded`？**
前者表示报告合法但**没有成功的工具观察结果**支撑；后者表示工具失败或模型/上游不可用。
两者都用 `error_code` 说明原因，展开轨迹能看到具体是哪一步失败。

**Q：`duration_ms` 是 `null`？**
该运行还没结束，或它是被下次启动回收的中断记录——回收记录算不出真实耗时，所以**故意**返回 `null` 而不是一个误导性的数字。

**Q：前端请求被浏览器拦截？**
CORS 白名单见 `INCIDENT_WEB_ORIGINS`，默认只允许 `http://127.0.0.1:5174`，换端口要同步修改。

## 安全注意事项

- `.env` 保存 MySQL 密码、DeepSeek Key 与上游地址，已被 `.gitignore` 忽略，**永远不要提交**；仓库只保留占位符 `.env.example`；
- Agent **不持久化 Token 和完整生产日志**，落库的是归一化后的结构化字段；
- 敏感字段（密钥、Token 等）经 `core/redaction.py` 脱敏后才进入日志与轨迹；
- 模型与依赖异常统一映射为固定文案，**不把 traceback 或 SDK 原文返回给客户端**；
- 日志、检索片段等外部内容在进 Prompt 前做定界与注入中和；
- 报告用 `extra="forbid"` 严格校验，`unverified_evidence` 只由服务端填写。

## 当前限制与规划

当前限制（均为真实状态）：

- 定位是**本地 MVP**，没有生产部署、容器化和上线记录；
- `get_service_status` 是**显式模拟数据**，未接真实监控、Kubernetes、Prometheus 或日志平台；
- Web 是**同步 JSON**，不是 SSE 流式（DevAtlas 那边已经有 SSE，Agent 侧尚未做）；
- 只提供分析建议，**不执行** Shell、重启服务、改配置等任何生产修复动作；
- 没有 Redis 缓存、没有评测集、没有真实用户量与准确率数据，也不会虚构这类指标；
- 强依赖 DevAtlas，不能单独使用；
- 一键启动脚本内含绝对路径常量，换机器需手工改；
- Pydantic 只保证结构正确，**不能证明模型陈述的事实为真**——证据核验只能挡掉无法回溯的部分。

后续规划（**均为未完成规划，不是已实现能力**）：

- Agent 侧 SSE 流式输出，与 DevAtlas 体验对齐；
- 接入真实可观测性数据源替换模拟的服务状态工具；
- 建立故障分析评测集，量化报告可用率与引用准确率；
- 排查动作的人工确认闭环（Agent 提议、人批准后执行），仍不做自动修复；
- 把启动脚本改为自动探测目录，去掉绝对路径。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [docs/agent-mvp设计.md](docs/agent-mvp设计.md) | 完整设计：需求、边界、工具契约、State、图、报告、异常、验收标准 |
| [docs/架构与演示.md](docs/架构与演示.md) | 运行时序、State 三类数据、正常/失败演示步骤、面试讲法 |
| [docs/阶段6验收清单.md](docs/阶段6验收清单.md) | 自动化与手工验收清单、交付前检查、已知限制 |
| [docs/测试对照-设计文档章节.md](docs/测试对照-设计文档章节.md) | 测试用例与设计文档章节的对照关系 |
| [docs/项目交接文档.md](docs/项目交接文档.md) | 上下文恢复入口、恢复顺序、工作方式约定 |
| [docs/简历项目描述.md](docs/简历项目描述.md) | 面向简历的项目描述 |
| [docs/导学-IncidentAgent.md](docs/导学-IncidentAgent.md) | 项目导学 |
| [docs/Agent学习整理.md](docs/Agent学习整理.md) | Agent 相关知识整理 |

## 许可证

[MIT](LICENSE)
