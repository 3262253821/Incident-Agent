# Incident Agent MVP 设计文档

> 文档版本：v0.1
>
> 编写日期：2026-09-04
>
> 项目目录：`E:\IncidentAgent`
>
> 依赖项目：`E:\RagKnowledgeSystem`（DevAtlas）

## 0. 文档目的

本文档用于在正式编码前冻结 Incident Agent 第一版 MVP 的目标、边界、模块职责、数据契约、状态流转、错误策略、接口和验收标准。

本文档中的设计优先级为：

```text
正确性 > 可解释性 > 可测试性 > 可维护性 > 功能数量
```

当前先做一个能稳定演示、能解释调用链、能展示成功和失败路径的垂直闭环。没有在本文档中明确实现的能力，不应在 MVP 阶段临时扩展。

---

## 1. 项目定位

### 1.1 一句话定位

Incident Agent 是一个面向研发和运维人员的微服务故障初步分析助手。它根据用户提供的故障标题、日志和知识库 ID，动态选择日志分析、知识库检索和服务状态工具，收集多源证据，记录执行轨迹，并生成带引用的结构化排查报告。

### 1.2 解决的问题

遇到如下故障时，工程师通常需要手动完成多步工作：

```text
阅读日志
→ 判断异常信号
→ 搜索故障手册
→ 查询服务状态
→ 对照多个结果
→ 编写初步排查结论
```

Incident Agent 将这些“信息收集和初步归纳”编排成一个可追踪流程，但不替代人工进行生产修复。

### 1.3 目标用户

- 值班运维工程师：快速完成故障初筛；
- 后端研发工程师：根据日志和内部文档定位排查方向；
- 面试演示者：展示 Agent 的工具决策、图编排、证据引用和失败处理。

### 1.4 非目标

MVP 不做以下事情：

- 自动重启服务、执行 Shell、修改配置或操作生产环境；
- 自动判断根因并声称百分之百确定；
- 自动创建 Jira、钉钉、飞书或 PagerDuty 工单；
- 监控系统实时告警接入；
- 多 Agent 协作；
- MCP、Skill、PlanAct；
- 自己重新实现文档解析、Embedding、向量入库和 Chroma；
- 复制 DevAtlas 已有的直接故障分析接口；
- 以模型生成的文字冒充真实文档引用。

---

## 2. 两个项目的职责边界

### 2.1 DevAtlas 的职责

`E:\RagKnowledgeSystem` 是通用研发知识库平台，当前已经具备：

- 用户注册、登录和 JWT 鉴权；
- 知识库 CRUD 和 owner 权限隔离；
- Markdown/TXT/PDF 上传；
- 文档解析、切分、逻辑文档和版本管理；
- BGE Embedding 和 Chroma 向量入库；
- 只检索 `indexed` 版本；
- 版本化文档来源 metadata；
- 纯检索接口 `/search`；
- 普通问答和故障分析 SSE；
- 故障分析记录和 citation 持久化。

DevAtlas 负责“知识如何被存储和检索”。

### 2.2 Incident Agent 的职责

Incident Agent 负责：

- 读取故障输入；
- 让模型决定调用哪些工具；
- 编排多个工具和多轮模型请求；
- 维护 LangGraph State；
- 记录 `messages`、`observations`、`steps`；
- 处理工具异常、超时、非法参数和循环上限；
- 判断何时结束并生成报告；
- 使用 Pydantic 校验最终报告；
- 保存 Agent 自己的运行记录；
- 向用户展示过程、证据、报告和失败原因。

Incident Agent 负责“知识何时被调用、如何与其他证据组合以及流程如何结束”。

### 2.3 集成原则

```text
Incident Agent
    ↓ HTTP 适配器
DevAtlas /api/v1/knowledge-bases/{id}/search
    ↓
返回 context + sources
```

Incident Agent 不调用 DevAtlas 的：

```text
/api/v1/knowledge-bases/{id}/incidents/stream
```

原因是该接口已经包含“检索 → LLM → SSE → incident 保存”。如果 Agent 调用它，会出现：

```text
Agent 模型
→ DevAtlas 故障分析接口
→ DevAtlas 内部再次调用模型
```

这会造成职责重复、两层报告生成和难以解释的调用链。

### 2.4 两个项目是否独立

两个项目保持独立进程和独立代码目录：

```text
DevAtlas：即使没有 Incident Agent，也可以单独作为知识库平台运行
Incident Agent：通过检索接口使用 DevAtlas，不复制其内部 RAG 实现
```

本地开发默认：

```text
DevAtlas API：127.0.0.1:8000
Incident Agent API：127.0.0.1:8001
```

---

## 3. MVP 范围和优先级

### 3.1 P0：必须完成

1. 一个 Web UI，可提交故障标题、内容和知识库 ID；
2. 一个可运行的 LangGraph；
3. 三个工具：日志分析、知识库检索、服务状态查询；
4. 至少一条正常路径和一条失败降级路径；
5. 最大模型请求次数保护；
6. `messages`、`observations`、`steps`、`report` 轨迹；
7. 结构化 `IncidentReport` 和 Pydantic 校验；
8. `search_knowledge` 通过适配器调用 DevAtlas `/search`；
9. Agent 使用独立 MySQL 保存运行记录；
10. Web 入口具备登录态或可验证的 Bearer JWT，并进行知识库权限传递；
11. 工具层、报告层、图路由层和 API 层离线测试；
12. 不把 API Key、JWT、完整敏感日志写入日志或运行记录。

### 3.2 P1：MVP 稳定后补充

- Web UI 的完整会话列表和历史详情；
- SSE 流式展示节点、工具和报告事件；
- 工具启用/禁用、最大循环次数和模型参数设置；
- 更完整的参数摘要、耗时指标和错误详情；
- DevAtlas 不可用时的专门提示页；
- 导出报告和引用。

### 3.3 P2：项目后续增强

- Prometheus、Kubernetes、Redis、Kafka、链路追踪工具；
- 工具去重和调用预算；
- 证据冲突检测；
- LLM-as-judge 和人工评测；
- 人工确认后执行的修复建议；
- 多租户服务身份认证；
- 部署、Docker 和 CI。

---

## 4. 用户流程

### 4.1 正常流程

```text
用户输入 title、content、knowledge_base_id
→ 校验输入
→ 创建 run_id
→ 初始化 AgentState
→ agent 节点请求模型
→ 模型返回一个或多个 tool_calls
→ tools 节点执行工具
→ observe 节点整理工具结果
→ 成功则回 agent
→ 模型判断证据已足够，不再调用工具
→ report 节点生成 JSON
→ Pydantic 校验报告
→ 保存 completed 运行记录
→ 返回报告、引用和轨迹
```

### 4.2 工具失败流程

```text
工具返回 ok=false 或执行异常
→ observe 记录工具结果和错误码
→ 根据失败策略停止继续调用
→ degrade 节点生成证据不足/工具失败结果
→ 保存 degraded 运行记录
→ 返回已经获得的证据和可读错误
```

### 4.3 报告失败流程

```text
report_model 返回非法 JSON 或字段不符合 Schema
→ json.loads 或 model_validate 失败
→ 不把报告标记为 completed
→ 保存 report_validation_failed
→ 返回 degraded 状态和已获得的 observations
```

### 4.4 循环超限流程

```text
agent 请求次数达到 max_iterations
→ 不再执行新的工具调用
→ limit 节点结束
→ 保存 max_iterations 状态和已有证据
```

---

## 5. 输入和输出契约

### 5.1 Agent 输入

```json
{
  "title": "订单服务返回 502",
  "content": "网关返回 502，订单服务日志显示 MySQL connection timeout。",
  "knowledge_base_id": 1
}
```

字段规则：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `title` | string | 1-200 字符，去除首尾空白后不能为空 |
| `content` | string | 1-20000 字符；禁止把 API Key 和密码写入日志 |
| `knowledge_base_id` | integer | 大于 0 |
| `top_k` | integer | 默认 5，范围 1-10，可在 Agent 配置中固定 |

### 5.2 Agent 输出

```json
{
  "run_id": "01J...",
  "status": "completed",
  "report": {
    "summary": "订单服务可能因数据库连接超时返回 502。",
    "category": "database",
    "evidence": [
      {
        "source": "fault_log",
        "detail": "日志命中 502、timeout 和 database_error。"
      },
      {
        "source": "knowledge_base",
        "detail": "订单服务故障排查手册说明 502 可能与数据库连接超时有关。"
      }
    ],
    "possible_causes": [
      "MySQL 不可用或连接超时",
      "订单服务连接池无法获取连接"
    ],
    "troubleshooting_steps": [
      "检查 MySQL 可用性",
      "检查订单服务连接池状态",
      "检查服务到数据库的网络连通性"
    ],
    "references": [
      "document_id=10;version_id=21;chunk_index=2"
    ],
    "confidence": "medium"
  },
  "observations": [],
  "steps": [],
  "error": null
}
```

`report` 只有在结构校验成功时才有值；降级或报告校验失败时可以是 `null`，但必须返回状态、错误和已经取得的证据。

---

## 6. 三个工具契约

工具只负责事实获取或确定性解析，不在工具内部调用另一个工具，不执行危险命令，不让模型伪造工具结果。

### 6.1 `analyze_log`

输入：

```json
{
  "log_text": "gateway returned 502; mysql connection timeout"
}
```

输出：

```json
{
  "ok": true,
  "data": {
    "signals": [
      {"type": "http_502", "value": "命中日志关键词"},
      {"type": "timeout", "value": "命中日志关键词"},
      {"type": "database_error", "value": "命中日志关键词"}
    ],
    "signal_count": 3
  },
  "error_code": null,
  "error": null
}
```

要求：

- 空日志在参数校验层拒绝；
- 日志内容只作为数据处理，不能执行其中的命令；
- 当前可以使用关键词规则，后续再替换为更强解析器；
- 输出命中的信号，不直接断言唯一根因。

### 6.2 `search_knowledge`

Agent 内部工具接口：

```text
search_knowledge(query, knowledge_base_id, top_k=5)
```

DevAtlas HTTP 请求：

```http
POST /api/v1/knowledge-bases/{knowledge_base_id}/search
Authorization: Bearer <用户 JWT>
Content-Type: application/json
```

请求体：

```json
{
  "question": "订单服务 502 MySQL connection timeout",
  "top_k": 5
}
```

DevAtlas 返回：

```json
{
  "question": "...",
  "context": "...",
  "sources": [
    {
      "document_id": 10,
      "version_id": 21,
      "version_number": 2,
      "chunk_index": 2,
      "filename": "订单服务故障排查手册.md",
      "content": "...",
      "distance": 0.25,
      "page_number": null
    }
  ]
}
```

Agent 统一转换为自己的工具结果，至少保留：

```text
document_id
version_id
version_number
chunk_index
filename
content
distance
```

错误映射：

| DevAtlas 情况 | Agent 错误码 |
| --- | --- |
| JWT 缺失或无效 | `RAG_UNAUTHORIZED` |
| 知识库不存在或无权限 | `RAG_KNOWLEDGE_BASE_NOT_FOUND` |
| 参数被 DevAtlas 拒绝 | `RAG_INVALID_ARGUMENTS` |
| 超时 | `RAG_TIMEOUT` |
| HTTP 503 | `RAG_UNAVAILABLE` |
| 其他 HTTP 错误 | `RAG_HTTP_ERROR` |
| 响应 JSON 不符合契约 | `RAG_INVALID_RESPONSE` |
| `sources=[]` | 工具成功，但事实状态为 `NO_EVIDENCE` |

无结果不是网络异常。它应该让 Agent 生成“知识库暂无相关证据”的低置信度结果，而不是伪造引用。

### 6.3 `get_service_status`

输入：

```json
{
  "service_name": "order-service"
}
```

输出：

```json
{
  "ok": true,
  "data": {
    "service_name": "order-service",
    "status": "degraded",
    "deploy_version": "2026.08.31",
    "error_count": 27,
    "checked_at": "2026-09-04T00:00:00Z"
  },
  "error_code": null,
  "error": null
}
```

MVP 先使用模拟服务状态表。允许的服务名必须在工具数据中明确列出，不能因为日志提到 `mysql` 就默认它一定可查询。未知服务返回：

```json
{
  "ok": false,
  "error_code": "UNKNOWN_SERVICE",
  "error": "未知服务：mysql"
}
```

后续接真实监控 API 时，保留同样的统一结果协议。

---

## 7. 统一工具结果协议

所有工具都返回同一类结构：

```python
class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error: str | None = None
```

成功约束：

```text
ok=true
error_code=null
error=null
```

失败约束：

```text
ok=false
error_code 非空
error 非空
```

失败时 `data` 默认为空字典；如果需要保存 Pydantic 详细错误，可以放在 `data.details`，但不能把密钥、完整敏感日志或第三方响应原文直接写入记录。

---

## 8. AgentState 设计

### 8.1 最小字段

```python
class AgentState(TypedDict):
    run_id: str
    owner_user_id: int
    title: str
    input_content: str
    knowledge_base_id: int
    top_k: int
    messages: Annotated[list[BaseMessage], add_messages]
    observations: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    iteration: int
    max_iterations: int
    status: str
    error: str | None
    report: dict[str, Any] | None
```

### 8.2 字段职责

| 字段 | 作用 |
| --- | --- |
| `run_id` | 一次分析的全局标识，用于日志和查询 |
| `owner_user_id` | DevAtlas 验证后的用户 ID，用于运行记录权限隔离 |
| `title` | 故障标题 |
| `input_content` | 用户输入的故障内容 |
| `knowledge_base_id` | DevAtlas 知识库 ID |
| `top_k` | 传给检索工具的召回数量 |
| `messages` | 模型协议上下文，保存 System、Human、AI、Tool 消息 |
| `observations` | 业务层事实，保存工具名、调用 ID、结果和来源 |
| `steps` | 可审计执行轨迹，保存节点、动作、耗时和状态 |
| `iteration` | Agent 决策模型请求轮数，不是工具数量 |
| `max_iterations` | 本次运行允许的最大模型请求轮数 |
| `status` | 当前生命周期状态 |
| `error` | 当前主要错误摘要 |
| `report` | 校验通过的最终报告；未生成时为 `None` |

### 8.3 消息和事实的区别

```text
messages：为了让模型继续对话，遵循 LLM 消息协议
observations：为了业务判断、报告和持久化，整理出的工具事实
steps：为了调试、审计和面试展示，记录执行过程
```

三者不能互相替代：

- 只保存 `messages` 不方便查询结构化事实；
- 只保存 `observations` 无法把上下文完整传回模型；
- 只保存 `steps` 无法还原工具返回内容。

### 8.4 状态值

统一使用（常量定义在 `core/statuses.py`，前端映射在 `web/src/constants/status.ts`）：

```text
running                     运行记录已创建，Graph 未结束
completed                   报告通过校验，且至少有一条成功的工具观察
insufficient_evidence       报告通过校验，但没有任何成功的工具观察
degraded                    工具失败，或模型/外部依赖不可用
report_validation_failed    报告节点无法产出合法报告
max_iterations              达到模型请求轮数上限
```

内部临时状态可以使用：

```text
tool_failed
```

对外返回时统一映射成 `degraded`，避免把内部节点状态暴露给 API 使用方。

#### `insufficient_evidence` 的判定规则

结构合法不等于结论可信。报告节点在通过 Pydantic 校验后，还要检查本次运行是否真的取得过工具证据：

```text
成功工具观察数 = observations 中 result.ok == True 的数量
成功工具观察数 == 0
→ 强制把报告 confidence 改为 low（只降不升，模型要求 high 也不放行）
→ status = insufficient_evidence
→ 追加一条 step：action=check_evidence_support, error_code=NO_TOOL_EVIDENCE
→ 前端不显示 COMPLETED 徽章，改为 NO TOOL EVIDENCE 并提示"报告仅依据用户描述生成"
```

只有 `ok=True` 的观察才算证据：全部工具都失败的报告，与完全没有工具的报告一样不可信。混合场景（既有成功也有失败）仍算 `completed`。

不允许的做法：保持 `completed` 只把 `confidence` 调成 `low`。用户看到的仍然是一个绿色完成徽章，问题等于没解决。

---

## 9. LangGraph 图设计

### 9.1 节点

| 节点 | 责任 |
| --- | --- |
| `agent` | 调用绑定工具的模型，决定继续调用工具还是生成普通文本 |
| `tools` | `ToolNode` 执行模型返回的一个或多个工具调用，产生 `ToolMessage` |
| `observe` | 解析新增 ToolMessage，写入 `observations` 和 `steps` |
| `report` | 使用已有消息和事实生成 JSON，并校验 `IncidentReport` |
| `degrade` | 工具或报告失败时结束并保留错误和已有证据 |
| `limit` | 达到最大模型请求次数时保护性结束 |
| `END` | 图运行结束 |

### 9.2 正常路径

```text
START → agent → tools → observe → agent → report → END
```

### 9.3 工具失败路径

```text
START → agent → tools → observe → degrade → END
```

当前 MVP 采用严格失败策略：同一轮中任意一个工具失败，就停止继续调用并降级。这样容易解释、风险更低。后续可新增“部分成功继续报告”的策略，但必须单独测试。

### 9.4 报告路径

```text
agent 返回 AIMessage 且 tool_calls 为空
→ route_after_agent 返回 report
→ report_model 生成报告
→ JSON 解析和 Pydantic 校验
→ report → END
```

### 9.5 循环保护

`MAX_ITERATIONS` 只限制 Agent 模型决策请求轮数：

```text
一次模型请求返回 4 个 tool_calls
→ ToolNode 执行 4 个工具
→ 仍然只算 1 次 iteration
```

达到上限后不能继续请求模型，也不能执行下一轮工具。

### 9.6 工具调用数量

`tool_calls` 列表中的数量由模型决定，不由 `MAX_ITERATIONS` 决定。代码应支持：

```text
0 个：进入 report
1 个：执行一个工具
多个：ToolNode 执行多个工具
```

不能假设每轮固定调用三个工具。

---

## 10. 报告设计

### 10.1 报告 Schema

```python
class EvidenceItem(BaseModel):
    source: str
    detail: str | None = None


class IncidentReport(BaseModel):
    summary: str
    category: Literal[
        "database",
        "network",
        "application",
        "dependency",
        "unknown",
    ]
    evidence: list[EvidenceItem]
    possible_causes: list[str]
    troubleshooting_steps: list[str]
    references: list[str]
    confidence: Literal["low", "medium", "high"]
```

### 10.2 报告生成原则

- 只使用用户输入和工具事实；
- 不把可能原因写成已经证实的根因；
- `evidence` 必须能追溯到日志或工具来源；
- `references` 优先保存 `document_id/version_id/chunk_index`；
- 无检索结果时不能伪造文档名；
- 工具失败时在报告或降级结果中说明失败项；
- 报告模型不绑定工具，避免报告阶段继续自由调用工具；
- 模型返回 Markdown 或额外解释时，按非法 JSON 处理，或在明确设计的清洗层处理；
- `json.loads()` 和 `IncidentReport.model_validate()` 都通过后才算报告成功。

### 10.3 证据来源规范

建议使用以下来源标识：

```text
fault_log
knowledge_base
service_status
tool_error
```

知识库引用必须保留：

```text
document_id
version_id
version_number
chunk_index
filename
distance
```

模型填写的普通 `references` 字符串不能替代后端保存的真实来源 metadata。

### 10.4 证据核验（已实现，P0-3-2）

结构合法不等于来源真实。报告通过 Pydantic 校验后，还要用**本次运行自己的 observations** 做一次来源核验，实现在 `graph/evidence.py`：

```text
从 observations 里 result.ok == True 的结果构建白名单：
  search_knowledge → 每条 sources 的 document_id / version_id /
                     version_number / chunk_index / filename / content
  analyze_log      → 只有 signals 非空才算命中（调用了但没信号不算）
  get_service_status → 只有解析出 service_name 才算命中

对报告里每条 evidence：
  source=knowledge_base → 必须能追溯到真实来源，判定顺序为
      ① 模型给出的 document_id（若给）命中真实来源且 version_id 不冲突 → 采用该来源
      ② 否则按 detail 与真实来源 content 的重叠度判定，
         重叠率 ≥ 0.6 视为可追溯（中文先做字符包含判断，英文退化为词重合）
      ③ 都失败 → 剔除
  source=fault_log / service_status → 对应工具必须真的产出过数据
  其他 source → 一律视为未核实（新增来源必须显式实现校验，不能默认放行）

命中后由服务端回填引用标识：document_id / version_id / version_number /
chunk_index / filename 一律以真实来源为准，模型自己写的值会被覆盖。
```

处理策略（在两种方案中选择了"A. 只剔除伪造项"）：

```text
剔除无法追溯的证据，保留可追溯的部分
→ confidence 强制降为 low（只降不升）
→ 追加 step：action=verify_evidence_sources, error_code=UNVERIFIED_EVIDENCE
→ 被剔除的内容写入 report.unverified_evidence（detail 截断 200 字符）
   供前端/排查查看，而不是静默丢弃
→ 若剔除后一条证据都不剩，则 report=None + status=insufficient_evidence
   （IncidentReport.evidence 要求至少 1 条，而"有结论、零证据"本身就不该交付）

不采用"整个报告判 report_validation_failed"：模型偶尔编造一条来源很常见，
那样会让绝大多数包含真实证据的运行一起报废。
```

---

## 11. DevAtlas 接入设计

### 11.1 适配器接口

Agent 业务层不直接依赖 HTTP 客户端细节，使用适配器：

```python
class RagGateway(Protocol):
    def search_knowledge(
        self,
        query: str,
        knowledge_base_id: int,
        top_k: int,
        access_token: str | None = None,
    ) -> RagSearchResult:
        ...
```

实现至少包括：

```text
HttpRagGateway：联调模式，调用 DevAtlas API
MockRagGateway：测试模式，返回固定来源或固定错误
```

如果两个项目未来部署在同一进程中，可以增加 `LocalRagGateway` 直接调用 DevAtlas 的检索 service，但不能把 DevAtlas 的模型问答逻辑复制到 Agent。

### 11.2 鉴权传递

跨进程联调时：

```text
用户请求携带 Bearer JWT
→ Agent 不解析或持久化 Token
→ Agent 调用 DevAtlas /search 时短暂转发 Authorization
→ DevAtlas 负责 JWT 验证和 knowledge_base owner 校验
```

本地 mock 工具测试可以不需要 Token，但 Web MVP 的真实分析请求必须具备登录态或 Bearer JWT。缺少 Token 时必须明确返回未授权，不偷偷绕过 DevAtlas 权限。

### 11.3 Agent Web 鉴权方案

第一版采用“DevAtlas 用户身份复用 + JWT 传递”方案：

```text
用户在 DevAtlas 登录
→ Web UI 保存短期登录态
→ Web UI 请求 Incident Agent 时携带 Bearer JWT
→ Agent API 校验 Token 是否存在
→ Agent 使用该 Token 请求 DevAtlas /auth/me，得到当前用户 ID
→ Agent 只保存用户 ID，不保存 Token
→ Agent 调用 DevAtlas /search 时转发 Authorization
→ DevAtlas 再验证 JWT 和 knowledge_base owner
```

MVP 阶段 Agent 可以不重复实现注册、密码哈希和用户表，但必须做到：

- 不接受客户端传入的 `owner_id` 作为权限依据；
- 不从请求体中接收或信任任意用户身份；
- 通过 DevAtlas 验证后的当前用户 ID 绑定 `agent_runs.owner_user_id`；
- 查询和删除运行记录必须使用 `run_id + owner_user_id` 过滤；
- 不把 JWT 写入 State、数据库或日志；
- DevAtlas 返回 `401/404` 时，Agent 不把结果伪装成检索成功；
- Web UI 的路由守卫只负责体验，最终权限由后端和 DevAtlas 校验。

如果未来需要 Agent 完全脱离 DevAtlas 独立部署，再增加 Agent 自己的认证服务和服务间凭证，不在当前 MVP 重复建设。

### 11.4 超时和重试

默认建议：

```text
连接超时：3 秒
读取超时：15 秒
总请求超时：20 秒
自动重试：默认 0 次
```

检索是有副作用为零的读请求，未来可以增加一次带退避的重试，但 MVP 不自动重试，避免延长故障分析和重复记录。

### 11.5 响应校验

Agent 必须用自己的 Pydantic 模型校验 DevAtlas 的响应：

```text
HTTP 状态码正确 ≠ 响应业务结构正确
```

缺少 `sources`、`version_id` 或字段类型错误时返回 `RAG_INVALID_RESPONSE`，不能把不完整来源传给报告节点。

---

## 12. 持久化设计

### 12.1 MVP 记录内容

每次运行至少记录：

```text
run_id
owner_user_id
title
input_content（必要时脱敏）
knowledge_base_id
status
started_at
completed_at
model_name
iteration
max_iterations
observations
steps
report
error
```

### 12.2 敏感数据规则

禁止持久化：

- API Key；
- JWT 原文；
- 数据库密码；
- Cookie；
- 完整生产敏感日志；
- 未脱敏的个人信息。

日志和运行记录只保存参数摘要、工具名、错误码和必要的截断内容。

### 12.2.1 脱敏落地位置（已实现）

脱敏必须在**进入模型之前**和**落库之前**同时生效，否则模型上下文、数据库和接口响应会各自出现不同的版本。当前实现（`core/redaction.py`）：

```text
用户提交的 title / content
→ execute_incident() 在 create_run() 之前统一脱敏并截断
→ 脱敏后的文本才是 AgentState、模型上下文、MySQL 和接口响应的唯一版本
→ 原始日志不进入 State、不落库、不返回

工具结果
→ tools 节点执行后立刻对 ToolMessage.content 脱敏再交回模型
→ observe 节点写入 observations 前再对结果做递归脱敏
→ 模型把凭据回显进 tool_calls.args 时，agent 节点同样递归脱敏
   （否则 _message_summary 会把凭据带进报告节点上下文）

最终报告
→ 报告通过 Pydantic 校验后，对 summary / evidence / possible_causes /
  troubleshooting_steps / references 再脱敏一次才写入 report
```

识别规则与取舍：

| 规则 | 处理方式 |
| --- | --- |
| `Bearer <credential>` | 无论凭据形状，一律掩码 |
| 三段式 JWT（`eyJ...`） | 无论出现在哪里都掩码 |
| `password` / `passwd` / `pwd` / `secret` / `token` / `api_key` / `access_key` / `auth_key` / `client_secret` / `jwt_secret_key` 等键名 | 键名出现即可信，值一律掩码（`password=dev` 也是泄露） |
| 连接串 `mysql://user:password@host/db` | 只掩码 `user:password`，**保留 host 和 database**，因为排查要用 |
| `手机号` / `联系电话` / `phone` 等标签后的 11 位号码 | 掩码 |
| `身份证号` / `id_card` 等标签后的 18 位号码 | 掩码 |
| 裸 11 位数字（如订单号） | **不掩码**，避免把 `order_id=150204567` 之类的证据误删 |

已知边界：`138-0013-8000` 这类带分隔符的手机号不会被命中；需要覆盖时应扩展标签规则而不是放宽裸数字匹配。

### 12.3 存储选择：独立 MySQL

Agent MVP 使用独立 MySQL 数据库，不与 DevAtlas 的业务表混用：

```text
DevAtlas：MySQL 数据库 dev_atlas
Incident Agent：MySQL 数据库 incident_agent
```

本地开发账号使用：

```text
用户名：root
密码：只从本机环境变量读取，不写入本文档、代码、日志或 Git
```

`root` 仅用于本机开发和学习环境。若部署到服务器或提交可复现部署配置，必须改用只拥有 `incident_agent` 数据库权限的专用账号，不使用 root。

Agent 数据库只保存 Agent 自己的运行数据，不保存 DevAtlas 的文档、Embedding、Chroma 向量或用户密码。

第一版至少设计以下表：

```text
agent_runs：一次故障分析的用户归属、输入、状态、报告、错误和时间
agent_steps：每个节点/工具步骤的轨迹、参数摘要、结果状态和耗时
```

`observations` 可以先作为 `agent_runs` 的 JSON 字段保存；如果后续要按工具、错误码或引用统计，再拆为独立表。数据库结构变更必须使用 Alembic，不直接手动修改表结构。

数据库连接池、事务提交、回滚、关闭和迁移配置独立于 DevAtlas，不能导入 DevAtlas 的数据库 Session。

---

## 13. API 设计

### 13.1 MVP 第一版 API

Web UI 作为第一版入口，FastAPI 负责鉴权、输入校验、调用 Graph 和返回运行结果。CLI 只作为开发调试和离线测试入口，不能替代 Web MVP。

```text
POST /api/v1/auth/login
GET  /api/v1/auth/me
POST /api/v1/incidents/analyze
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs
GET  /health
```

### 13.2 分析请求

请求必须携带：

```http
Authorization: Bearer <DevAtlas access token>
```

Agent 不从请求体接收 `owner_id`。`knowledge_base_id` 的访问权限由 DevAtlas 根据 JWT 所属用户再次校验。

强制预校验（已实现，不依赖模型行为）：

```text
Bearer 鉴权通过
→ Agent 用同一 Token 调 DevAtlas GET /api/v1/knowledge-bases/{knowledge_base_id}
→ DevAtlas 按 knowledge_base.id + owner_id 过滤，非本人或不存在统一返回 404
→ 404 时 Agent 直接返回 404，且不创建任何 agent_runs 记录
→ 401/403 返回 401；DevAtlas 不可达返回 503
→ 校验通过后才 create_run 并进入 Graph
```

原因：此前授权依赖模型主动调用 `search_knowledge`。如果模型只调用日志分析或服务状态工具，Agent 全程不会向 DevAtlas 校验该知识库，未授权或不存在的 ID 仍会落库并完成分析。授权必须是请求入口的固定步骤，不能交给模型决策。

请求：

```json
{
  "title": "订单服务返回 502",
  "content": "订单服务日志显示 MySQL connection timeout",
  "knowledge_base_id": 1
}
```

成功响应：

```text
200 OK
```

```json
{
  "run_id": "...",
  "status": "completed",
  "report": {},
  "observations": [],
  "steps": [],
  "error": null
}
```

降级不是 HTTP 服务器崩溃，建议仍返回 `200` 搭配业务状态 `degraded`，因为 Agent 已经完成了可解释的失败处理。输入校验错误返回 `422`，服务完全不可用返回 `503`。

### 13.3 API 状态码

| 状态码 | 场景 |
| --- | --- |
| `200` | 分析完成或可解释降级 |
| `404` | run_id 不存在 |
| `422` | title、content、knowledge_base_id 不合法 |
| `502` | 外部模型或 DevAtlas 返回不可用，若没有被 Agent 吸收为降级 |
| `503` | Agent 服务自身依赖未启动 |

### 13.3.1 运行记录权限

```text
GET /api/v1/runs
GET /api/v1/runs/{run_id}
```

这两个接口都必须先得到 DevAtlas 当前用户 ID，再按以下条件查询：

```text
agent_runs.id = run_id
AND agent_runs.owner_user_id = current_user_id
```

即使用户猜中其他人的 `run_id`，也只能得到 `404`，不能返回记录是否存在。

### 13.4 Web UI 与 SSE

第一版 Web UI 使用同步 JSON 也可以先跑通，但 Web Harness 的目标接口为：

```text
POST /api/v1/incidents/analyze/stream
```

事件可以使用：

```text
event: step
event: observation
event: report
event: done
event: error
```

前端第一版只需要实现：登录态、故障输入、运行中状态、工具步骤列表、引用和报告展示。复杂工作区、插件管理、桌面端打包不属于当前 MVP。

### 13.5 Web 技术选择

Web UI 优先使用 Vue 3、TypeScript、Vite 和 Axios，与 DevAtlas 现有前端技术栈保持一致，便于复用 HTTP、JWT 和 SSE 的理解。Incident Agent 前端代码放在：

```text
E:\IncidentAgent\web
```

第一版不做桌面端。桌面端只是后续将 Web UI 使用 Electron 或 Tauri 打包的交付形态，不影响 Agent、Graph、数据库和 API 的核心设计。

### 13.6 本地端口和跨域

本地开发端口约定：

```text
DevAtlas 后端：127.0.0.1:8000
DevAtlas 前端：127.0.0.1:5173（已有项目）
Incident Agent API：127.0.0.1:8001
Incident Agent Web：127.0.0.1:5174
```

浏览器只直接访问 Incident Agent API；Incident Agent 服务端再访问 DevAtlas。这样 DevAtlas 的 `/search` 不暴露给 Agent Web，也不会把 DevAtlas 的数据库连接放到浏览器。

Agent API 必须配置 CORS，仅允许 `http://127.0.0.1:5174` 和开发阶段明确的本地来源，不使用 `*` 搭配凭证请求。Agent Web 的登录请求通过 Agent API 的认证代理完成：

```text
Agent Web → Agent API /auth/login
Agent API → DevAtlas /api/v1/auth/login
DevAtlas 返回 access_token
Agent API → Web（只返回登录所需结果）
```

后续每次 Agent API 请求携带 Bearer JWT。Agent API 调用 DevAtlas `/auth/me` 得到用户 ID，并在调用 `/search` 时转发 Token。Token 不进入 AgentState、MySQL、运行记录或普通日志。

---

## 14. 配置设计

配置通过环境变量读取，示例文件只放变量名和占位符：

```text
INCIDENT_AGENT_HOST=127.0.0.1
INCIDENT_AGENT_PORT=8001
INCIDENT_AGENT_MODEL=deepseek-chat
INCIDENT_AGENT_BASE_URL=https://api.deepseek.com
DEVATLAS_BASE_URL=http://127.0.0.1:8000
DEVATLAS_TIMEOUT_SECONDS=20
INCIDENT_MAX_ITERATIONS=4
INCIDENT_DEFAULT_TOP_K=5
INCIDENT_DB_HOST=127.0.0.1
INCIDENT_DB_PORT=3306
INCIDENT_DB_NAME=incident_agent
INCIDENT_DB_USER=root
INCIDENT_DB_PASSWORD=<本机环境变量>
```

真实 API Key 只放本机 `.env` 或系统环境变量，不能写入：

```text
代码
Markdown
测试用例
终端输出
截图
Git
```

模型配置、超时、最大轮数和检索数量不能散落在业务函数中，应集中管理。

---

## 15. 日志、轨迹和可观测性

### 15.1 每一步至少记录

```json
{
  "run_id": "...",
  "step_index": 1,
  "node": "tools",
  "action": "tool_call",
  "tool_name": "search_knowledge",
  "tool_call_id": "...",
  "arguments_summary": {
    "knowledge_base_id": 1,
    "top_k": 5,
    "query_length": 42
  },
  "status": "success",
  "error_code": null,
  "duration_ms": 1250
}
```

### 15.2 不记录的内容

- 完整 `Authorization` 头；
- API Key；
- 完整原始敏感日志；
- 模型上下文中不必要的个人信息；
- 未经脱敏的第三方错误响应。

### 15.3 必须能回答的问题

一次运行结束后，应该能够回答：

```text
调用了几轮模型？
每轮调用了哪些工具？
工具参数是否通过校验？
哪个工具失败？错误码是什么？
检索返回了哪些 document/version/chunk？
为什么进入 report、degrade 或 limit？
最终报告是否通过 Schema？
总耗时大致是多少？
```

---

## 16. 异常和安全策略

### 16.1 输入异常

```text
空标题/空内容/超长内容/非法 knowledge_base_id
→ Pydantic 422
→ 不进入模型和工具
```

### 16.2 工具异常

工具异常必须转换为统一 `ToolResult`，不能把 Python traceback 直接返回给用户。

```text
参数错误       → INVALID_ARGUMENTS
非法 JSON      → INVALID_JSON
未知工具       → UNKNOWN_TOOL
未知服务       → UNKNOWN_SERVICE
工具内部异常   → TOOL_ERROR
外部检索超时   → RAG_TIMEOUT
```

### 16.3 Prompt Injection

用户日志、文档和检索内容均视为不可信数据：

- 不执行日志或文档中的命令；
- 不因文档中的“忽略系统提示”而改变系统规则；
- 不让检索文本决定工具权限；
- 工具白名单由 Python 代码控制；
- 危险操作不注册为工具。

### 16.4 报告幻觉控制

- 报告 Prompt 要求只依据事实；
- 报告必须保留来源引用；
- 报告节点将已知工具名安全映射为业务证据来源（`analyze_log → fault_log`、`search_knowledge → knowledge_base`、`get_service_status → service_status`），未知来源不放宽通过；
- 不允许无证据写成确定结论；
- Pydantic 只校验结构，不能证明事实真实；
- 真实引用由工具结果和后端 metadata 提供。

### 16.5 失败降级

降级结果必须包含：

```text
status
error_code 或错误摘要
已经获得的 observations
可以继续人工检查的建议
```

不能因为模型失败就丢弃之前已经获得的证据。

---

## 17. 测试设计

### 17.1 分层

```text
工具单元测试
→ Pydantic 参数和统一错误码

适配器测试
→ DevAtlas 成功、空结果、401、404、503、超时和非法响应

Graph 路由测试
→ 正常、工具失败、报告失败和循环上限

API 测试
→ 输入校验、run 查询、状态码和响应结构

人工演示
→ 真实模型选择工具和报告质量
```

真实模型不作为唯一的自动化测试依据。图测试使用固定 `FakeModel`，确保不会因模型随机选择不同工具而不稳定。

### 17.2 最少 10 条案例

1. `502 + MySQL connection timeout` 正常分析；
2. `timeout` 但没有数据库关键词；
3. 未知服务名；
4. 空日志或缺少标题；
5. 知识库无相关内容；
6. 检索工具抛异常；
7. 服务状态工具超时；
8. 报告模型返回非法 JSON；
9. 模型重复请求相同工具；
10. 达到最大循环次数。

### 17.3 硬断言

测试优先验证：

```text
工具集合是否合理
参数和错误码是否正确
observations 是否完整
步骤轨迹是否保留
报告是否通过 Schema
失败是否停止
是否不会无限循环
```

第一版不把“回答文案像不像人”作为唯一指标。

---

## 18. 正式目录设计

学习代码和正式项目不删除、不混用：

```text
E:\IncidentAgent
├── app\
│   └── incident_agent\
│       ├── __init__.py
│       ├── core/config.py        # 集中配置
│       ├── db/session.py         # 数据库会话和 ORM Base
│       ├── models/agent_run.py   # AgentRun、AgentStep ORM
│       ├── schemas/              # 输入、工具、报告和 RAG 契约
│       ├── services/             # 存储、RAG 适配器和工具
│       └── graph/state.py        # AgentState
├── migrations\                  # Agent MySQL Alembic 迁移
├── web\                         # Incident Agent Web UI
├── tests\                       # 正式项目测试
├── stages\                      # 学习练习代码，全部保留
├── docs\                        # 学习和设计文档
├── requirements.txt
├── .env
└── .env.example
```

`stages` 中的代码用于理解和回归，不直接作为正式项目的模块导入。正式代码应去除学习示例中的硬编码、打印式调试和跨目录 `sys.path` 修改。运行记录由独立 MySQL 保存，`runs` 目录不作为正式数据源。

---

## 19. 实现顺序

本项目按阶段推进。每个阶段都必须完成“编码 → 运行 → 测试 → 解释 → 验收”，用户明确确认后再进入下一阶段。不会一次生成所有模块。

### 阶段 0：项目骨架和契约冻结

目标：创建正式目录，固定配置、输入、输出、工具结果、报告和 State 契约。

交付：

```text
app/incident_agent/core/
app/incident_agent/db/
app/incident_agent/models/
app/incident_agent/schemas/
app/incident_agent/services/
app/incident_agent/graph/
web/
migrations/
tests/
.env.example
```

验收：目录职责清楚，敏感配置只来自环境变量，学习代码未被修改或删除。

### 阶段 1：独立 MySQL 和持久化

目标：准备独立的 `incident_agent` 数据库，使用 SQLAlchemy 2 和 Alembic 保存运行记录。

交付：

```text
agent_runs
agent_steps
```

验收：能创建、更新、查询一条运行记录；失败时事务回滚；不保存 API Key、JWT 和完整敏感日志。

### 阶段 2：工具层和 RAG 适配器

目标：先用 mock 验证三工具，再接入 DevAtlas `/search`。

顺序：

```text
MockRagGateway
→ HttpRagGateway
→ DevAtlas 鉴权传递
→ 响应 Schema 校验
```

验收：成功、空结果、401、404、503、超时和非法响应都有固定测试结果。

### 阶段 2.5：正式代码分层迁移

目标：在进入 LangGraph、API 和 Web 开发前，将阶段 0-2 的扁平模块迁移到职责清晰的包目录。

已完成：

```text
core/config.py
db/session.py
models/agent_run.py
schemas/incident.py、schemas/tool.py、schemas/rag.py
services/storage.py、services/rag_client.py、services/tools.py
graph/state.py
```

迁移只调整文件位置和导入路径，不改变工具协议、数据库表结构、Alembic 版本或业务行为。验收包括全量语法检查、阶段 2 测试和 `alembic check`。

### 阶段 3：LangGraph Agent 核心

目标：把学习阶段的图整理为正式模块，支持工具调用、观察、报告、降级和最大轮数。

流程：

```text
START → agent → tools → observe → agent → report → END
                              ├→ degrade
                              └→ limit
```

验收：mock 模型能稳定跑通正常、工具失败、报告失败和循环上限。

### 阶段 4：Agent Web API 和鉴权

目标：用 FastAPI 提供 Web UI 调用的接口，并要求 Bearer JWT。

接口：

```text
GET  /health
POST /api/v1/incidents/analyze
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs
```

验收：无 Token 被拒绝；合法 Token 能传递到 DevAtlas；输入错误返回 422；运行结果可查询。

### 阶段 5：Web Harness MVP

目标：实现一个只面向 Incident Agent 的 Web UI，先不做桌面端。

第一版页面：

```text
登录态检查
故障输入表单
知识库 ID/选择
运行状态
工具步骤和观察结果
引用来源
最终结构化报告
历史运行详情
```

先使用同步 JSON 跑通页面，再增加 SSE 事件：

```text
step → observation → report → done/error
```

验收：浏览器可完成一次成功分析和一次失败降级，并能看到运行轨迹。

### 阶段 6：联调、测试和交付

目标：接入真实 DevAtlas，完成成功/失败演示和测试材料。

交付：

- 真实 `/search` 联调记录；
- 10 条以上离线测试结果；
- 一次正常演示；
- 一次降级演示；
- README、架构图和工作流图；
- 项目简历描述。

### 阶段推进规则

每次只实施当前阶段，下一阶段开始前必须确认：

```text
代码已写入指定路径
命令运行成功
测试结果符合预期
关键流程已经解释
已知问题已记录
```

---

## 20. 验收标准

### 功能验收

- [ ] 正常输入能完成工具调用、观察、报告和结束；
- [ ] Web UI 能提交一次故障分析并展示结果；
- [ ] Web API 无 Bearer JWT 时拒绝请求；
- [ ] 合法 JWT 能在调用 DevAtlas `/search` 时传递；
- [ ] 一轮支持一个或多个工具调用；
- [ ] 失败工具不会被当成成功事实；
- [ ] 未知服务能安全降级；
- [ ] 报告模型非法 JSON 不会被标记为完成；
- [ ] 达到最大轮数后停止；
- [ ] 报告包含真实引用或明确说明没有引用；
- [ ] 可查询一次运行的状态和轨迹；
- [ ] 独立 MySQL 能保存并查询运行记录；
- [ ] DevAtlas 不可用时错误可读且不会泄露内部敏感信息。

### 代码验收

- [ ] 不从 `.env` 读取并打印密钥；
- [ ] 不把完整 JWT 写入日志；
- [ ] 不复制 DevAtlas 的文档解析、Embedding、Chroma 和认证实现；
- [ ] 工具、节点、适配器和存储职责清楚；
- [ ] 配置集中管理；
- [ ] 关键边界有 Pydantic 校验；
- [ ] 自动化测试不依赖真实模型随机输出；
- [ ] Agent 不复用或修改 DevAtlas 的业务数据库表；
- [ ] `stages` 学习代码未被删除。

### 演示验收

成功演示：

```text
输入订单服务 502 和 MySQL 超时
→ 展示日志信号
→ 展示 DevAtlas 文档来源
→ 展示 order-service 状态
→ 展示结构化报告和引用
```

失败演示：

```text
模拟未知服务或 RAG 超时
→ 展示错误码
→ 展示已保留的 observations
→ 展示停止循环和降级状态
```

---

## 21. 已确认决策和暂不决策项

### 已确认

1. Incident Agent 与 DevAtlas 保持项目和进程边界；
2. Agent 只调用 DevAtlas `/search`，不调用 DevAtlas `/incidents/stream`；
3. Agent 使用三个 P0 工具；
4. 工具结果统一使用 `ok/data/error_code/error`；
5. LangGraph 负责流程、状态、循环和分支；
6. 报告使用 JSON + Pydantic 校验；
7. 工具失败默认严格降级；
8. 未知服务不是模型成功猜测，而是工具返回可处理的失败；
9. `messages`、`observations`、`steps` 分别保存协议上下文、业务事实和执行轨迹；
10. Web UI 是第一版展示入口，CLI 仅作为调试和离线测试入口；
11. Agent 使用独立 MySQL 数据库，账号为本机 `root`，密码只通过环境变量提供；
12. Web MVP 采用 DevAtlas JWT 登录态复用和鉴权传递；
13. 按阶段实施，每阶段验收后再开始下一阶段。

### 暂不决策

- 是否引入 Redis；
- 是否使用服务间独立 OAuth2/client credentials；
- 是否将工具结果拆成独立关系表；
- 是否将 Agent 与 DevAtlas 合并部署；
- 是否增加 reranker、BM25、Prometheus 和 Kubernetes 工具；
- 是否允许部分工具失败后继续生成报告。

这些问题在没有真实运行数据和明确需求前不提前复杂化。

---

## 22. 面试版说明

> DevAtlas 是底层的版本化研发知识库，负责文档解析、切分、向量化、权限和检索；Incident Agent 是上层故障分析应用，通过工具接口复用 DevAtlas 的检索能力。Agent 使用 LangGraph 编排模型、日志分析、知识检索和服务状态查询，维护 State 和执行轨迹，并通过条件边处理继续调用、报告生成、工具失败和最大循环。最终报告由独立节点生成 JSON，再使用 Pydantic 校验，引用保留 document、version 和 chunk 信息。这样两个项目不是重复的两个 RAG，而是“通用知识基础设施 + 面向故障场景的 Agent 应用”。

---

## 23. 当前实施状态

```text
已完成：
- Agent 基础、Prompt、Function Calling、ReAct；
- LangChain 和 LangGraph 学习示例；
- 三个模拟工具；
- 结构化报告节点；
- 异常降级和最大循环；
- 工具、报告和图流程测试基础。

当前任务：
- 按本文档创建正式 Incident Agent MVP；
- 先保留 stages 学习代码；
- 阶段 0 已完成：正式目录、配置模板、输入/工具/报告契约和 AgentState；
- 阶段 1 已完成：独立 MySQL、SQLAlchemy 模型、Alembic 迁移和持久化基础；
- 阶段 2 本地实现已完成：工具层、MockRagGateway、HttpRagGateway 和离线测试；
- 阶段 2.5 已完成：正式代码按 core、db、models、schemas、services、graph 分层，导入路径和迁移配置已更新；
- 阶段 2.6 已完成：FastAPI `app/main.py`、auth/incidents/runs routers、DevAtlas 鉴权代理、`/health` 和 `/health/db` 已实现，并在 8001 启动验证；
- 阶段 2 真实联调已完成：知识库 `3` 的三个文档均为 `indexed`，已通过授权 Swagger 验证 `/search` 返回真实 sources metadata，联调结束后关闭 DevAtlas `8000`；
- 阶段 3 已完成：正式 LangGraph 节点、条件路由、ToolNode、报告校验、工具失败降级和最大轮数保护已实现；固定 FakeModel 测试正常、多工具、工具失败、报告失败和循环上限；
- 阶段 3 报告校验修复已完成：处理真实运行中工具名与业务来源枚举不一致的问题，补充 Prompt 映射规则和白名单归一化测试；当前全量测试 `18 passed`；
- Graph 已接入 `incidents/analyze` API：请求经鉴权后创建运行记录，执行 Graph 并保存 observations、steps、report 和状态；基础双服务联调已通过，下一步用本机 JWT 进行一次真实 DeepSeek 分析演示；
- 阶段 5 Web Harness MVP 已完成：`web/` 使用 Vue 3 + TypeScript + Vite + Axios，提供登录、API 状态、故障输入、执行轨迹、观察结果、结构化报告和历史运行界面；已在 `5174` 构建并启动检查；
- Web 前端分层已完成：`api`、`components`、`layouts`、`views`、`router`、`stores`、`types` 已拆分，`App.vue` 仅保留 `RouterView`；已安装 `vue-router` 和 `pinia` 并通过构建；
- 本地启动辅助已完成：根目录 `One-click launch.bat` 通过 `scripts/start-devatlas.ps1`、`scripts/start-agent.ps1`、`scripts/start-web.ps1` 打开三个 PowerShell；端口已占用时跳过重复启动，约定端口仍为 `8000/8001/5174`；
- 阶段 6 已完成：README、架构与演示、验收清单、简历项目描述和服务检查脚本已补齐；前端构建、后端测试、语法和迁移检查通过；
- 后续按阶段逐步完成 Graph、API 和 Web UI；
- 最后完成真实联调、测试和交付。
```

### 阶段 0 实施记录

已创建：

```text
E:\IncidentAgent\app\__init__.py
E:\IncidentAgent\app\incident_agent\__init__.py
E:\IncidentAgent\app\incident_agent\config.py
E:\IncidentAgent\app\incident_agent\schemas.py
E:\IncidentAgent\app\incident_agent\state.py
E:\IncidentAgent\migrations\.gitkeep
E:\IncidentAgent\web\.gitkeep
E:\IncidentAgent\runs\.gitkeep
E:\IncidentAgent\tests\.gitkeep
E:\IncidentAgent\.env.example
E:\IncidentAgent\.gitignore
```

验证结果：

```text
Python compileall 通过
正式契约模块导入通过
未连接 MySQL
未调用模型
未读取或打印现有 .env 内容
```

### 阶段 1 实施记录

已创建或修改：

```text
E:\IncidentAgent\app\incident_agent\db.py
E:\IncidentAgent\app\incident_agent\models.py
E:\IncidentAgent\app\incident_agent\storage.py
E:\IncidentAgent\alembic.ini
E:\IncidentAgent\migrations\env.py
E:\IncidentAgent\migrations\script.py.mako
E:\IncidentAgent\migrations\versions\20260904_0001_create_agent_run_tables.py
E:\IncidentAgent\requirements.txt
E:\IncidentAgent\app\incident_agent\config.py
```

数据库结果：

```text
数据库：incident_agent
表：agent_runs、agent_steps、alembic_version
迁移版本：20260904_0001（head）
```

验证结果：

```text
SQLAlchemy 模型导入通过
Alembic upgrade head 通过
Alembic check 通过，无待生成迁移
创建、追加步骤、完成运行记录的冒烟测试通过
临时测试记录已删除
```

### 阶段 2 实施记录

本阶段拆为“本地实现”和“真实联调”两个验收点，真实联调未完成前不进入阶段 3。

本地实现已创建或修改：

```text
E:\IncidentAgent\app\incident_agent\rag_client.py
E:\IncidentAgent\app\incident_agent\tools.py
E:\IncidentAgent\app\incident_agent\schemas.py
E:\IncidentAgent\requirements.txt
E:\IncidentAgent\tests\test_tools_adapters.py
```

本地验证结果：

```text
工具名称和统一 ToolResult 结构验证通过
MockRagGateway 成功、空结果、超时和不可用模式验证通过
工具参数错误和未知服务验证通过
HTTP 错误码映射代码已实现
阶段 2 离线测试：6 passed
```

真实联调前置条件：

```text
DevAtlas 后端运行在 127.0.0.1:8000
存在可登录的测试用户
测试用户拥有目标 knowledge_base_id
知识库至少有一个 indexed 文档
JWT 只在本机运行时提供，不写入 Agent 数据库和日志
```
