# 导学-IncidentAgent

## 项目技术定位

交叉型 AI 应用项目：后端以 Python/FastAPI 为入口，使用 LangGraph 编排工具调用和状态流转，通过 DevAtlas RAG 获取证据，最终由 DeepSeek 生成结构化故障报告；Vue 负责登录、分析表单、执行轨迹和历史展示。

## 前置知识

| 知识点 | 为何需要 | 在项目中的位置 | 高频度 |
|---|---|---|---|
| FastAPI 依赖注入与 Bearer JWT | 保护分析和历史接口 | `app/incident_agent/dependencies.py`、`routers/` | 高 |
| Pydantic v2 | 约束请求、工具结果和报告 | `schemas/` | 高 |
| LangGraph 状态图 | 理解 Agent 的循环、路由和终止 | `graph/state.py`、`graph/workflow.py` | 很高 |
| Tool calling | 模型选择日志、检索、状态工具 | `graph/nodes.py`、`services/tools.py` | 很高 |
| RAG HTTP 适配 | 连接 DevAtlas 的纯检索接口 | `services/rag_client.py` | 高 |
| SQLAlchemy/Alembic | 保存运行记录与步骤轨迹 | `models/`、`services/storage.py`、`migrations/` | 高 |
| Vue/Pinia/Axios | 复现登录到分析的用户链路 | `web/src/` | 中 |

## 重点亮点与学习顺序

| 亮点标题 | 为什么重要 | 通用技术关键词 | 先看哪些文件 | 建议顺序 |
|---|---|---|---|---|
| 状态图编排 | 解释模型为何能多轮调用工具并安全结束 | 状态机、条件路由、预算 | `graph/state.py`、`graph/workflow.py`、`graph/nodes.py` | 1 |
| 证据驱动报告 | 把观察事实与推测分开 | 结构化输出、Pydantic、引用 | `nodes.py`、`schemas/incident.py` | 2 |
| 跨服务 RAG 边界 | Agent 复用 DevAtlas 而不复制其向量链路 | Gateway、超时、错误归一化 | `rag_client.py`、`tools.py` | 3 |
| 可追溯执行记录 | 让一次分析可回看、排错和评估 | ORM、owner isolation、审计轨迹 | `storage.py`、`models/agent_run.py`、`routers/runs.py` | 4 |
| 受限故障工具 | 只读分析，不执行生产操作 | 工具白名单、降级 | `services/tools.py`、`incident.py` | 5 |

## 必备知识点

- [ ] 能画出“登录 → JWT → 分析入口 → Graph → 工具 → 观察 → 报告 → 持久化”的链路。
- [ ] 能解释 `AgentState` 中每个字段的输入、更新者和最终用途。
- [ ] 能说明为何 `search_knowledge` 必须把 Bearer Token 转发给 DevAtlas。
- [ ] 能区分 `agent`、`tools`、`observe`、`report`、`degrade`、`limit` 节点。
- [ ] 能解释 `ToolResult`、`IncidentReport` 为什么要在服务端再次校验。
- [ ] 能指出当前 P0 缺口：知识库入口授权、敏感日志脱敏、报告证据核验。

## 推荐阅读

| 主题 | 通用技术点 | 建议阅读位置 | 预计时间 | 读完能回答什么 |
|---|---|---|---|---|
| 入口与鉴权 | FastAPI、依赖注入、代理鉴权 | `app/main.py`、`app/incident_agent/dependencies.py`、`routers/auth.py` | 30 分钟 | Token 从哪里来，如何验证和转发？ |
| 一次分析 | 服务编排、持久化边界 | `routers/incidents.py`、`services/incident.py` | 35 分钟 | 一次请求何时创建 run，失败如何落库？ |
| Graph 循环 | 状态图、条件边、终止条件 | `graph/state.py`、`graph/workflow.py`、`graph/nodes.py` | 60 分钟 | 模型何时调用工具，何时报告或降级？ |
| 工具与 RAG | Gateway、错误归一化、依赖注入 | `services/tools.py`、`services/rag_client.py` | 45 分钟 | DevAtlas 不可用时系统怎么表现？ |
| 数据与历史 | ORM、级联、owner 隔离 | `models/agent_run.py`、`services/storage.py`、`routers/runs.py` | 35 分钟 | 如何保证用户只能看自己的运行记录？ |
| Web 调用链 | Axios、Pinia、路由守卫 | `web/src/api/`、`web/src/stores/`、`web/src/views/` | 30 分钟 | 页面如何登录、提交分析和打开历史？ |

## 核心原理解析

1. **模型不会直接执行生产操作** → 模型只能选择白名单工具 → 工具返回统一 `ToolResult`，系统再决定继续、降级或生成报告。
2. **Agent 需要跨轮共享事实** → `AgentState` 保存消息、观察、步骤和迭代次数 → LangGraph 按条件边循环，达到上限就进入 `limit`。
3. **RAG 不属于 Agent 自己的数据库** → `HttpRagGateway` 调用 DevAtlas `/search` → 转换为严格的 `RagSearchResponse`，并把错误归一化成业务错误码。
4. **模型输出不等于可信报告** → `parse_report()` 用 JSON 和 Pydantic 校验结构 → 后续还必须把 evidence 与真实 observations 做服务端交叉核验。
5. **历史记录既是产品能力也是风险面** → `AgentRun/AgentStep` 保存可追溯轨迹 → 必须做 owner 过滤、脱敏、分页和保留策略。

## 关键设计决策

| 备选 | 取舍 | 风险 | 验证 |
|---|---|---|---|
| 复用 DevAtlas `/search` / 复制 RAG | 复用可避免两套向量链路和重复 LLM | 上游不可用、契约漂移 | Mock + HTTP 契约测试 |
| LangGraph / 手写 while 循环 | 图结构清晰、便于轨迹和路由 | 依赖升级和状态理解成本 | Graph 正常、失败、上限测试 |
| 同步 FastAPI / 全异步 | MVP 简单；全异步吞吐更好 | 模型和 HTTP 阻塞线程 | 超时、并发压测 |
| 严格失败降级 / 尽量继续 | 失败时不编造结论 | 一项工具失败会放弃部分证据 | 失败工具回归测试 |

## 量化与验证（待测）

- 待测：单次分析端到端耗时、模型调用次数、DevAtlas 检索耗时和报告校验失败率。
- 待测：固定故障样例上的工具选择正确率、引用准确率和建议可执行性。
- 待测：并发请求下线程占用、数据库写入冲突和历史接口响应大小。
- 验证命令：`py -m pytest tests -q`、`py -m compileall -q app migrations tests`、`alembic check`、`ruff check app migrations tests`、`npm run build`。

## 自学提醒

第一轮不需要逐行背诵所有代码，先能说清模块职责、输入输出、调用链和失败路径；遇到某个 Python、FastAPI、SQLAlchemy、LangGraph 或 RAG 原理看不懂，继续追问 AI，再回到真实源码验证。
