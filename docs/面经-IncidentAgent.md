# 面经-IncidentAgent

## 项目简介

Incident Agent 是面向研发和运维人员的故障初步分析助手。用户提交故障标题、日志和知识库 ID，Agent 通过 LangGraph 让模型在受限工具集合中收集日志信号、知识库证据和服务状态，再生成经过 Pydantic 校验、可回看执行轨迹的结构化报告。

## 简历 bullet

- **Agent 编排与安全终止：** 将模型决策、工具执行、观察整理、报告生成和降级结束拆成 LangGraph 节点，通过最大模型请求次数和工具白名单限制循环边界，形成可测试的正常、失败和超限路径。
- **跨服务 RAG 适配：** 以 Gateway 适配 DevAtlas 纯检索接口，统一处理鉴权转发、超时、网络错误和非法响应，同时保留上游知识库的文档、版本和切片来源信息。
- **结构化输出校验：** 使用 Pydantic 约束故障报告的分类、证据、可能原因、排查步骤和置信度；模型输出不符合 JSON 或业务枚举时进入受控降级，而不是把自由文本当成可信报告。
- **可追溯执行记录：** 使用独立 MySQL 保存一次运行及其步骤轨迹，并在查询时按 owner_user_id 隔离历史记录，为后续故障复盘、人工评测和问题定位保留结构化证据。
- **前后端联调与边界：** Vue/Pinia/Axios 复用 DevAtlas JWT 登录态，前端展示分析状态、工具轨迹、报告和历史；系统明确只读分析，不执行重启、Shell 或生产配置修改。

## 面试问题（主问题）

### 1. 项目定位与链路

**问：请介绍一下 Incident Agent 的完整流程。**

**口播：** 我把它定位成一个只读的故障初步分析助手，而不是自动修复系统。用户先通过 DevAtlas 账号登录，前端把故障标题、日志内容、知识库 ID 和 Top-K 提交给 Agent API。API 先验证 Bearer Token，然后创建一条运行记录并初始化 AgentState。Graph 的 agent 节点让模型决定是否需要调用日志分析、知识库检索或服务状态工具；工具结果进入 observe 节点，整理成 observations 后再回到 agent。模型认为证据足够时进入 report 节点，由模型输出 JSON 并用 Pydantic 校验，最后把报告、步骤和状态保存到 MySQL。工具失败、报告非法或达到最大迭代次数时走受控降级，前端仍能看到失败原因和已有轨迹。

**追问：为什么不直接调用 DevAtlas 的故障分析接口？**

**口播：** DevAtlas 已经包含知识库检索和故障分析能力，但 Incident Agent 的目标是展示 Agent 编排能力。如果直接调用它的故障分析接口，就会把检索、提示词和模型流程重复执行，既失去工具选择的演示价值，也可能产生两次模型调用。现在 Agent 只调用 DevAtlas 的纯检索接口，把权限、版本过滤和向量查询留在知识库项目内；Agent 自己负责选择工具、收集观察、控制循环和生成最终报告。这样两个项目边界清晰，也方便用 MockRagGateway 做离线测试。

### 2. LangGraph 与工具调用

**问：LangGraph 在项目中解决了什么问题？**

**口播：** 如果只用一个 while 循环，模型请求、工具调用、结果整理、失败处理和循环上限容易揉在一起，测试时也难以定位某一步。LangGraph 把这些行为建模成状态图：agent 负责决策，tools 执行模型请求的工具调用，observe 把 ToolMessage 转成业务观察，report 负责结构化输出，degrade 和 limit 负责安全结束。AgentState 是节点之间共享的契约，里面有 messages、observations、steps、iteration 和 status。条件路由根据最后一条 AIMessage 是否包含 tool_calls、当前迭代次数和工具结果状态决定下一节点，所以流程可视化、可回归，也便于以后增加人工确认或更多只读工具。

**追问：如何防止 Agent 无限循环或重复调用？**

**口播：** 当前 MVP 采用两层保护。第一层是在 Graph 路由中比较 iteration 和 max_iterations，模型请求次数达到上限就进入 limit 节点并持久化 `max_iterations` 状态；第二层是工具失败后 observe 设置失败状态，route_after_observe 直接进入 degrade，不再把错误工具结果反复交给模型。当前还没有按工具参数去重、Token 预算和费用预算，这些被列为后续 P2 优化。真实接入时我会对工具名和规范化参数做去重，并增加总耗时、调用次数和模型 Token 的预算，避免仅靠模型自觉停止。

### 3. RAG 与跨服务边界

**问：Agent 如何调用 DevAtlas 检索？**

**口播：** 工具层不直接依赖具体 HTTP 细节，而是依赖 `RagGateway` 协议。生产实现 `HttpRagGateway` 使用 httpx 调用 DevAtlas 的 `/api/v1/knowledge-bases/{id}/search`，把用户 Bearer Token 放在请求头中，并提交 question 和 top_k。响应先解析 JSON，再由 `RagSearchResponse` 校验 question、context 和 sources，以及文档、版本、切片和距离字段。超时、网络错误、401、404、422 和 503 被转换成统一的 `RagGatewayError`，工具层再包装成 `ToolResult`。测试使用 `MockRagGateway` 模拟成功、无结果、超时和不可用，不依赖真实模型或外部服务。

**追问：知识库权限是否已经完全安全？**

**口播：** 当前代码能在 DevAtlas 检索接口被调用时转发 Token，由 DevAtlas 做知识库权限判断；但我审计后发现分析入口只校验 knowledge_base_id 是正整数，并没有在创建 AgentRun 前强制验证知识库归属。如果模型选择只分析日志和服务状态，就可能绕过这一步并保存一个未授权的知识库 ID。这个属于 P0 缺口，修复方案是在创建运行记录前调用 DevAtlas 的知识库详情或授权接口，失败直接返回 403/404 且不落库，同时增加日志-only 路径的越权测试。

### 4. 报告可信度与失败处理

**问：模型报告如何保证结构正确？**

**口播：** 报告节点使用单独的系统提示词，要求模型只返回 JSON，并规定 category、confidence 和 evidence.source 的允许值。`parse_report` 先把非字符串响应转成 JSON 字符串，再执行 json.loads，最后用 `IncidentReport.model_validate` 校验必填字段、列表非空、枚举和值域。如果模型把工具函数名写进 source，代码只对已知别名做白名单映射，未知值仍然交给 Pydantic 拒绝。非法 JSON 或字段校验失败会记录 report 步骤失败，并返回 report_validation_failed，最终由服务层持久化为失败结果。当前还需要补服务端证据白名单，避免格式合法但来源虚构。

**追问：工具失败为什么不继续调用其他工具？**

**口播：** MVP 采用严格失败策略，是为了避免模型在关键依赖不可用时继续补猜结论。例如 DevAtlas 检索超时后，模型可能只剩日志关键词，却仍然生成看似确定的根因。observe 节点会把每个 ToolMessage 解析成统一 ToolResult，只要一轮中出现 ok=false，就把状态设为 tool_failed；条件路由随后进入 degrade，保留已经收集的 observations 和错误信息，不再请求更多工具。这个取舍牺牲了部分可用证据，但边界更容易解释。后续可以针对不同错误码区分：鉴权或权限错误立即降级，偶发超时允许一次重试，已经成功的观察继续用于低置信度报告。

### 5. 数据库、隐私和工程化

**问：为什么要把 AgentRun 和 AgentStep 分成两张表？**

**口播：** AgentRun 表示一次完整的用户分析请求，保存 owner、输入摘要、知识库 ID、运行状态、迭代次数、最终报告和完成时间；AgentStep 表示这次运行中的每个模型节点或工具观察，保存节点、动作、工具名、调用 ID、状态和错误码。拆开后可以一对多记录完整轨迹，运行列表只查主表，详情再加载步骤；删除运行时通过外键级联清理步骤。查询接口同时把 owner_user_id 作为条件，所以用户只能看到自己的 run。当前还需要为输入和观察增加脱敏、列表分页和保留策略，否则完整日志可能泄露凭据并使历史响应过大。

**追问：项目遇到过什么真实问题？**

**口播：** 当前审计发现的真实问题不是 Graph 主链路无法运行，而是“功能跑通”和“边界可靠”之间的差距。第一，分析入口没有在模型调用前强制校验 knowledge_base_id，日志-only 路径可能绕过知识库授权；第二，input_content 和 observations 目前可能把完整故障日志写入 MySQL，和设计文档要求的敏感日志边界不一致；第三，报告只校验 JSON 结构，没有核对引用是否来自真实检索结果。我的处理顺序会把三项列为 P0，先补授权、脱敏和证据白名单测试，再补 LLM 超时重试、历史分页和 Ruff/CI，而不是继续堆叠 MCP 或多 Agent。

## 源码证据索引

| 主题 | 关键路径与内部符号 | 对应正文位置 |
|---|---|---|
| 入口与鉴权 | `app/main.py`、`dependencies.get_access_token`、`get_current_user` | 链路、RAG 边界 |
| 分析服务 | `routers/incidents.py`、`services/incident.execute_incident`、`_initial_state` | 完整流程、权限缺口 |
| Graph | `graph/state.AgentState`、`workflow.build_graph`、`nodes.route_after_agent`、`route_after_observe` | LangGraph、循环保护 |
| 工具 | `services/tools.build_tools`、`analyze_log`、`get_service_status` | 工具调用、mock 边界 |
| RAG | `services/rag_client.HttpRagGateway`、`RagGatewayError`、`MockRagGateway` | 跨服务适配 |
| 报告 | `nodes.parse_report`、`make_report_node`、`schemas/incident.IncidentReport` | 结构化输出、证据可信度 |
| 持久化 | `models/agent_run.AgentRun/AgentStep`、`services/storage.*` | 数据库、隐私和历史 |
| 前端 | `web/src/stores/auth.ts`、`stores/incident.ts`、`views/IncidentWorkspaceView.vue` | Web 联调 |

## 交给 /great-resume 的项目事实摘要

- 项目名称：Incident Agent；目标岗位：大模型应用开发、Python 后端、RAG/Agent 应用开发实习。
- 个人职责边界：需求梳理、模块分层、接口和 Graph 方案、DevAtlas 联调、测试、故障定位和优化规划；代码有 AI 辅助生成，不宣称生产上线或真实用户指标。
- 可核验证据：18 条自动化测试通过；覆盖 Graph 正常/失败/最大迭代、工具适配、Mock RAG 和 API 鉴权基础路径；启动脚本、独立 MySQL、Vue Web Harness 已存在。
- 可写表述：LangGraph 工具编排、DevAtlas RAG Gateway、Pydantic 结构化报告、MySQL 运行轨迹、JWT 复用和受控降级。
- 待补事实：P0 权限校验、敏感日志脱敏、报告引用核验尚未实现；无真实准确率、用户量、吞吐和上线数据。

## 交给 /interview 的高风险 Claim 清单

- **Ownership Claim：** “设计并负责 Agent 分层、Graph 主链路、DevAtlas 联调和测试”；面试时说明 AI 辅助边界和自己完成的决策、调试、验证工作。
- **Architecture Claim：** “使用 LangGraph 编排工具、观察、报告和降级节点”；必须能画出状态流和最大迭代保护。
- **Security Claim：** 只能说“复用 DevAtlas JWT 并转发知识库权限”；在 P0 修复前不能声称分析入口已完全实现知识库授权隔离。
- **Result Claim：** 只能说测试覆盖和当前可运行能力；不要编造准确率、性能、用户数、生产稳定性或上线结果。
