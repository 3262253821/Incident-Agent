# Agent 学习整理

> 当前阶段：已完成 LLM 基础、Prompt、Function Calling、多工具、结构化输出、ReAct、LangChain、LangGraph、异常处理和测试基础
>
> 项目：Incident Agent

## 一、当前学习目标

目前已经完成 Agent 基础闭环学习：

1. 理解 LLM 如何处理文本、上下文和输出；
2. 能把 System Prompt 写成清晰、可验证的行为契约；
3. 能理解模型选择工具、Python 执行工具、结果回传的闭环；
4. 能用 Pydantic 校验工具参数和最终故障报告；
5. 能解释 ReAct 的 Reason、Act、Observation；
6. 能使用 LangChain 和 LangGraph 编排工具调用流程；
7. 能处理工具失败、循环上限和报告格式错误；
8. 能为工具层和图流程设计离线测试。

下一步进入 Incident Agent MVP 设计和实现。现有 `stages` 目录保留为学习练习，正式项目代码应放在独立的项目目录中。

---

## 二、LLM 基础认知

### 1. Token

Token 是模型处理文本时使用的基本单位，不完全等于一个字或一个单词。

一次请求的 Token 通常包括：

```text
System Prompt
+ 用户输入
+ 历史消息
+ 工具描述
+ 工具返回结果
+ 模型输出
```

Token 主要影响：

- API 成本；
- 上下文窗口可容纳的内容；
- 输入和输出的长度。

### 2. 上下文窗口

上下文窗口是模型一次能够看到的最大 Token 容量，可以理解为模型的工作记忆。

输入、历史消息、工具结果和预计输出会共同占用上下文窗口。内容过多时可能出现请求失败、早期信息被截断、模型忘记约束或回答质量下降。

常见处理方式：

- 只保留最近消息；
- 总结较早的历史；
- 日志只提取关键行；
- 检索结果限制 Top-K；
- 限制 Agent 最大循环次数；
- 不把敏感信息放入上下文。

### 3. 温度和 Top-p

温度和 Top-p 用于控制模型生成的随机程度。

- 低温：输出稳定、保守、可重复；
- 高温：输出更多样、更发散，也更容易偏离格式；
- Top-p：限制模型采样时可选择的候选词范围。

Incident Agent 中，工具选择、工具参数和结构化 JSON 报告通常使用较低温度，优先保证稳定性。实践中一般先调整温度，不要同时大幅调整温度和 Top-p。

### 4. 幻觉

LLM 的本质是根据上下文预测下一个 Token。当缺少事实依据时，仍可能生成听起来合理但实际没有证据支持的内容。

例如日志中没有数据库连接池信息，模型却直接断定“连接池耗尽”，就属于幻觉或无依据推断。

降低幻觉的方法：

- 先通过 RAG 或工具获取真实证据；
- 要求保留文档、版本和切片引用；
- 明确要求证据不足时说明不确定；
- 使用结构化 Schema 校验输出；
- 由代码限制工具调用次数和危险操作；
- 故障分析只输出建议，不自动执行修复命令。

---

## 三、Prompt 工程

### 1. 核心认识

Prompt 不是聊天话术，而是模型行为契约。它要告诉模型：

- 你是谁；
- 你要完成什么任务；
- 哪些信息可以作为证据；
- 哪些事情禁止做；
- 什么时候应该继续或停止；
- 最终结果必须是什么格式。

### 2. 三类消息职责

- `system`：定义角色、任务、规则和安全边界；
- `user`：提供本次具体任务和输入；
- `tool`：返回后端真实执行的工具结果。

### 3. 合格 Agent Prompt 的组成

```text
角色
任务
输入说明
证据规则
工具使用规则
安全边界
停止条件
输出格式
不确定性处理
```

### 4. 证据和不可信数据

用户输入、日志、知识库文档和工具返回内容都应该被视为数据，而不是系统指令。

必须明确要求：

- 不编造日志、指标、工具结果或引用来源；
- 区分已观察到的证据和可能原因；
- 没有足够依据时返回“证据不足”；
- 不执行日志或文档中出现的命令；
- 不输出密码、Token 和 API Key。

### 5. Prompt 和代码的分工

Prompt 适合描述模型应该如何分析和表达，但不能承担关键安全逻辑。

以下内容必须由代码保证：

- 用户权限校验；
- 工具参数校验；
- 最大循环次数；
- 超时和异常处理；
- 危险操作拦截；
- 最终 JSON/Pydantic Schema 校验；
- API Key 和敏感日志脱敏。

### 6. 停止条件

Incident Agent 至少要在 Prompt 或代码中明确：

- 证据足够时生成报告并停止；
- 工具失败时记录错误并降级结束；
- 没有检索结果时说明缺少依据；
- 达到最大循环次数时停止；
- 不得无限调用工具。

### 7. 结构化输出

不能只要求模型“输出规范一点”。应明确字段、类型和枚举值，并在代码中再次校验。

Incident Agent 报告的基础字段：

```text
summary
category
evidence
possible_causes
troubleshooting_steps
references
confidence
```

推荐的枚举值：

```text
category: database | network | application | dependency | unknown
confidence: low | medium | high
```

---

## 四、必须掌握和记忆

### 必须能够用自己的话解释

1. Token 为什么会影响成本和上下文长度；
2. 上下文窗口为什么会爆，以及如何压缩内容；
3. 为什么工具调用和 JSON 输出通常使用低温度；
4. 幻觉为什么产生，以及 RAG、工具和引用如何缓解；
5. System Prompt 为什么是行为契约；
6. `system`、`user`、`tool` 三类消息的职责；
7. 为什么日志和文档必须被当作不可信数据；
8. 哪些逻辑必须放在代码而不是 Prompt 中；
9. Agent 为什么必须有停止条件；
10. 为什么最终报告要使用 Pydantic 或 JSON Schema 校验。

### 面试级总结

> 我把 System Prompt 当作 Agent 的行为契约，规定角色、证据使用、安全边界、停止条件和输出结构；但权限控制、循环上限、工具执行、异常处理和结果校验仍然放在代码层，避免把关键业务逻辑完全交给模型。

---

## 五、需要看懂、会改，但不用死记

- 具体 Prompt 文案；
- tokenizer 的内部实现；
- 不同模型的最佳措辞；
- JSON Schema 的全部语法；
- 温度和 Top-p 的所有参数组合；
- 各种 Prompt 技巧的名称；
- 第三方框架对 Prompt 的封装方式。

真正重要的是能根据业务目标补充职责、证据、边界、停止条件和输出格式。

---

## 六、当前练习文件

Prompt 练习文件：

```text
E:\IncidentAgent\stages\L2-prompt\prompt_lab.py
```

该练习对比基础版、改进版和生产契约版 Prompt，并检查生产版是否包含关键契约章节。

---

## 七、Function Calling 当前理解补充

### 1. 两种“次数”必须分开

外层循环：

```python
for step in range(1, MAX_STEPS + 1):
```

控制最多向模型发起几轮请求，也就是“模型请求轮数”。

内层循环：

```python
for call in tool_calls:
```

遍历模型本轮响应中的所有工具调用项，也就是“工具调用数量”。

两者关系：

```text
外层：第几轮请求模型
  → 模型返回一个 tool_calls 列表
  → 内层：逐个执行列表中的工具调用
```

### 2. 三个工具调用从哪里来

代码没有写死“三个工具调用”。模型看到用户问题和 `TOOL_DEFINITIONS` 后，会自行决定返回多少个调用。

本次第一次模型请求只发生了 1 次，但模型返回了包含 3 个元素的 `tool_calls` 列表：

```text
search_knowledge（订单服务 502、MySQL 超时）
search_knowledge（MySQL 连接超时、数据库排查）
search_knowledge（502 网关、上游服务）
```

因此 Python 才通过内层 `for call in tool_calls` 执行了 3 次工具。

准确说法是：

```text
模型请求 1 次
模型返回 3 个工具调用项
Python 执行工具 3 次
```

不能把这 3 个工具调用项说成 3 次模型请求。

### 3. `tool` 消息的作用

每次工具执行完成后，程序把结果追加到 `messages`：

```python
messages.append(
    {
        "role": "tool",
        "tool_call_id": call.id,
        "content": json.dumps(result, ensure_ascii=False),
    }
)
```

这一步不是再次请求模型，而是把真实工具结果记录进对话历史，供下一轮模型请求读取。

- `role="tool"`：表示这是工具返回的消息；
- `tool_call_id`：把结果对应到模型刚才的某一次调用；
- `content`：Python 工具真正返回的 JSON 数据。

### 4. 本次运行的准确流程

```text
外层第 1 轮
├─ 请求模型 1 次
├─ 模型返回 3 个 tool_calls
├─ Python 执行工具 1
├─ 保存 tool 结果 1
├─ Python 执行工具 2
├─ 保存 tool 结果 2
├─ Python 执行工具 3
└─ 保存 tool 结果 3

外层第 2 轮
├─ 请求模型 1 次
├─ 模型读取 3 个 tool 结果
├─ 模型不再请求工具
├─ 生成最终回答
└─ 程序结束
```

本次最终统计：

```text
外层循环执行 2 轮
模型请求 2 次
工具调用 3 次
```

### 5. 必须记住的最简版本

```text
模型决定调用什么工具
→ Python 根据工具名和参数执行函数
→ Python 把结果放回 messages
→ 模型读取结果并生成回答
```

外层 `for` 表示“模型来回几轮”，内层 `for` 表示“这一轮要执行几个工具”。

---

## 八、结构化输出

### 1. 什么是结构化输出

结构化输出不是让模型“看起来像 JSON”，而是给模型输出定义一个明确的数据契约，并由程序再次校验。

当前实现的流程是：

```text
模型返回 JSON 文本
→ json.loads() 转成 Python 字典
→ IncidentReport.model_validate(data)
→ 合法：得到 IncidentReport 对象
→ 非法：抛出校验错误，不进入后续流程
```

当前学习代码使用的是“模型输出 JSON + Pydantic 校验”，还不是模型 API 原生的严格 JSON Schema 输出模式。后续可以再学习原生结构化输出能力。

### 2. IncidentReport 是最终报告契约

文件：

```text
E:\IncidentAgent\stages\L3-tools\report_models.py
```

`IncidentReport` 规定故障分析报告必须包含：

```text
summary
category
evidence
possible_causes
troubleshooting_steps
references
confidence
```

字段约束包括：

- `summary`：非空字符串；
- `category`：只能是 `database`、`network`、`application`、`dependency`、`unknown`；
- `evidence`：至少一项证据；
- `possible_causes`：至少一个可能原因；
- `troubleshooting_steps`：至少一个排查步骤；
- `references`：字符串列表，可以为空；
- `confidence`：只能是 `low`、`medium`、`high`。

### 3. EvidenceItem 是嵌套数据结构

证据不只是普通字符串，还可以保留来源和详情：

```json
{
  "source": "fault_log",
  "detail": "日志出现 502 和 MySQL connection timeout"
}
```

因此报告模型使用：

```python
evidence: list[EvidenceItem] = Field(min_length=1)
```

含义是：`evidence` 必须是至少包含一项 `EvidenceItem` 的列表。

### 4. 这次遇到的真实契约不一致

第一次模型返回的是对象列表：

```json
"evidence": [
  {"source": "fault_log", "detail": "..."}
]
```

后来模型返回了字符串列表：

```json
"evidence": [
  "故障日志命中 502 和 timeout"
]
```

当模型返回对象、模型定义要求字符串时，会报“应为字符串”；当模型返回字符串、模型定义要求 `EvidenceItem` 时，会报“应为字典或 EvidenceItem”。

当前代码在 `EvidenceItem` 上增加了预处理兼容逻辑：字符串证据会被转换为：

```json
{
  "source": "model_summary",
  "detail": "原始证据字符串"
}
```

这解决了学习阶段的格式波动，但 `model_summary` 只是兼容标记，不是原始工具来源。正式项目应尽量通过 Prompt、结构化输出和后端映射固定一种证据格式，并保留真实的文档、版本和切片 ID。

### 5. `model_validate()` 如何完成校验

```python
return IncidentReport.model_validate(data)
```

`IncidentReport` 继承自 Pydantic 的 `BaseModel`，因此 `model_validate()` 是 Pydantic 提供的类方法。

它会读取 `IncidentReport` 类中声明的字段规则，自动检查：

```text
字段是否存在
类型是否正确
字符串是否为空
列表是否至少有一项
枚举值是否合法
嵌套 evidence 是否符合 EvidenceItem
是否出现禁止的额外字段
```

校验成功时返回一个 `IncidentReport` 对象，不是普通字典；校验失败时抛出 `ValidationError`。

它不负责生成 `summary`、`category` 或 `confidence` 的值。报告值来自模型，Pydantic 只负责检查这些值是否符合契约。

### 6. 关键 Pydantic 语法

```python
summary: str = Field(min_length=1)
```

表示 `summary` 必须是至少一个字符的字符串。

```python
category: Literal["database", "network", "application", "dependency", "unknown"]
```

表示 `category` 只能取列出的值。

```python
model_config = ConfigDict(extra="forbid")
```

表示报告中不能出现模型没有声明的额外字段。

```python
references: list[str] = Field(default_factory=list)
```

表示 `references` 是字符串列表，默认值为空列表。使用 `default_factory` 可以为每个对象创建独立列表。

```python
@model_validator(mode="before")
```

表示在常规字段校验前先做一次输入预处理。当前用它把字符串证据归一化为 `EvidenceItem`。

### 7. `parse_report()` 的完整链路

文件：

```text
E:\IncidentAgent\stages\L3-tools\main.py
```

执行顺序：

```text
assistant.content
→ strip() 去除首尾空白
→ 如果有 ``` 代码块则去除代码块标记
→ json.loads() 转成 Python 字典
→ IncidentReport.model_validate(data)
→ 返回 IncidentReport 对象
```

随后：

```python
report.model_dump()
```

会把已经校验通过的 `IncidentReport` 对象转换回普通字典，便于 `json.dumps()` 打印或返回 API。

### 8. 报告字段到底来自哪里

在当前真实模型版本中，Python 不直接计算最终报告字段。流程是：

```text
用户输入
+ analyze_log 工具结果
+ search_knowledge 工具结果
+ get_service_status 工具结果
→ 这些内容写入 messages
→ 模型读取上下文并生成 JSON 报告
→ Pydantic 校验报告
```

例如模型根据日志出现 `502`、`timeout`，知识库提到数据库连接超时，服务状态为 `degraded`，生成：

```text
category = database
confidence = medium
possible_causes = [...]
```

这些值是模型的分析结果；`model_validate()` 只确认它们类型正确、取值合法、结构完整。

### 9. 工具参数契约和报告契约是两层校验

```text
模型工具调用参数
→ run_tool()
→ 工具参数 Pydantic 模型校验
→ 执行工具

模型最终报告 JSON
→ parse_report()
→ IncidentReport 校验
→ 输出可靠报告对象
```

工具调用成功，不代表最终报告一定合法；最终报告合法，也不代表工具结果一定真实。因此两层都需要校验。

### 10. 必须掌握

1. 结构化输出的核心是“定义契约并校验”，不是只要求模型输出 JSON；
2. `IncidentReport` 定义最终报告的字段、类型和允许值；
3. `EvidenceItem` 用于表达带来源的嵌套证据；
4. `json.loads()` 负责把 JSON 文本转成 Python 数据；
5. `model_validate()` 按 Pydantic 模型定义校验并创建对象；
6. `model_dump()` 把 Pydantic 对象转回字典；
7. 报告字段由模型根据用户输入和工具结果生成，Pydantic 不负责推理；
8. 工具参数校验和最终报告校验是两层独立契约；
9. 模型输出格式可能变化，边界层必须处理或拒绝不一致格式；
10. 正式项目应尽量保留真实工具来源，不能把模型总结当成真实引用。

### 11. 面试级总结

> 我使用 Pydantic 定义 IncidentReport 和嵌套 EvidenceItem，对模型返回的 JSON 做运行时校验，限制字段类型、必填列表和枚举值。模型负责根据用户输入和工具证据生成报告，Python 负责执行工具、解析 JSON 和拒绝非法结构；对于证据来源，则需要由后端保留真实的 document/version/chunk 关联，不能只相信模型填写的字符串。

### 12. 需要看懂、会改，但不用死记

- `BaseModel` 的内部实现；
- Pydantic 全部字段配置；
- `model_validator` 的所有模式；
- JSON Schema 全部语法；
- 每个校验错误链接的具体 URL；
- 模型每次生成的具体报告文案。

---

## 九、ReAct、LangChain 与 LangGraph

### 1. ReAct

ReAct 是 Agent 的基本工作模式：

```text
Reason：判断下一步需要什么信息
Act：选择并调用工具
Observation：读取工具返回结果
Reason：根据新结果决定继续还是结束
```

它不是某个特定框架，而是一种“思考、行动、观察”的循环模式。LangChain 和 LangGraph 都可以用来实现这种模式。

### 2. LangChain 的定位

LangChain 是模型、消息和工具的开发封装层，提供：

- `ChatOpenAI`：统一调用聊天模型；
- `@tool`：把 Python 函数声明成模型可调用的工具；
- `bind_tools()`：把工具的名称、参数类型和描述传给模型；
- `AIMessage`：模型返回的助手消息，可能包含 `tool_calls`；
- `ToolMessage`：工具执行后的结果消息。

LangChain 不会替模型思考，也不会自动保证业务逻辑正确。它主要减少手写消息协议和工具调用格式的工作。

### 3. `@tool` 和 `bind_tools()`

```python
@tool
def get_service_status(service_name: str) -> dict:
    """查询服务状态。"""
    ...
```

`@tool` 会把函数包装成 LangChain 工具对象。函数名、参数名、类型注解和 docstring 会用于生成工具描述。

```python
model_with_tools = model.bind_tools(tools)
```

这一步把工具描述发送给模型，使模型知道：

```text
有哪些工具、工具叫什么、需要哪些参数、工具是做什么的
```

模型决定调用工具，但真正执行 Python 函数的是 `ToolNode` 或程序代码。

### 4. LangGraph 的定位

LangGraph 是 Agent 流程编排框架，不是模型，也不是 RAG。它把 Agent 流程表示成一个有状态的图：

```text
State：节点之间共享的数据
Node：执行一段逻辑的函数
Edge：节点之间的连接
Conditional Edge：根据 State 决定下一条边
```

它适合表达循环、分支、失败降级和人工介入等流程。

### 5. `START`、`END` 和 `compile()`

```python
graph_builder.add_edge(START, "agent")
```

表示图从 `agent` 节点开始。

```python
graph_builder.add_edge("report", END)
```

表示报告节点执行完成后结束。

```python
graph = graph_builder.compile()
```

`compile()` 会检查并冻结节点、边和路由配置，生成可执行的图对象。它只是在组装流程，不会调用模型。

```python
final_state = graph.invoke(initial_state)
```

`invoke()` 才会真正从 `START` 开始运行图，并返回最终 State。

代码书写顺序不等于运行顺序。运行顺序由边决定：节点执行完，再沿着边进入下一个节点。

### 6. 当前 Incident Agent 图

正常路径：

```text
START
  → agent
  → tools
  → observe
  → agent
  → report
  → END
```

工具失败路径：

```text
START
  → agent
  → tools
  → observe
  → degrade
  → END
```

循环超限路径：

```text
agent
  → limit
  → END
```

### 7. 当前 `AgentState`

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    observations: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    iteration: int
    status: str
    error: str | None
    report: dict[str, Any] | None
```

各字段职责：

- `messages`：模型协议上下文，包含用户、模型和工具消息；
- `observations`：工具返回的事实，便于业务逻辑和报告节点使用；
- `steps`：执行轨迹，记录调用或观察了什么；
- `iteration`：模型决策请求轮数；
- `status`：当前运行状态；
- `error`：失败原因；
- `report`：最终结构化报告。

`messages` 使用 `add_messages`，节点返回新消息时会追加到历史，而不是覆盖原列表。其他字段默认按节点返回值更新。

### 8. `ToolNode`

```python
graph_builder.add_node("tools", ToolNode(tools))
```

`ToolNode` 读取最后一条 `AIMessage` 中的 `tool_calls`，根据工具名找到对应函数，传入参数并执行，然后产生一个或多个 `ToolMessage`。

它只负责执行工具和生成消息，不负责把结果整理进 `observations`。当前项目由 `observe_tools_node()` 完成这一步。

### 9. `observe_tools_node()`

该节点会：

1. 找出 `messages` 中的 `ToolMessage`；
2. 用 `json.loads()` 解析工具返回结果；
3. 把结果写入 `observations`；
4. 把动作写入 `steps`；
5. 发现任意 `ok=False` 时设置 `status="tool_failed"` 和 `error`。

```text
ToolMessage 是模型上下文中的协议消息
observations 是业务层整理后的事实
steps 是审计和调试用的轨迹
```

### 10. 条件路由

```python
def route_after_agent(state: AgentState) -> str:
    last_message = state["messages"][-1]

    if not last_message.tool_calls:
        return "report"

    if state["iteration"] >= MAX_ITERATIONS:
        return "limit"

    return "tools"
```

路由函数只负责“决定去哪”，不负责执行下一个节点。返回值会在映射表中找到目标节点：

```python
{
    "tools": "tools",
    "report": "report",
    "limit": "limit",
}
```

必须注意：模型不再调用工具时，当前版本进入 `report`，而不是直接结束。

### 11. 循环次数

```python
MAX_ITERATIONS = 4
```

`iteration` 统计 Agent 决策模型请求轮数，不是单个工具调用数量。一次模型响应可以包含多个 `tool_calls`，这些工具由 `ToolNode` 在同一轮执行。

```text
一次 agent 请求
→ 返回 3 个 tool_calls
→ ToolNode 执行 3 个工具
→ 仍然只算第 1 次模型请求
```

报告模型请求当前没有计入 `iteration`，它是独立的报告生成步骤。

---

## 十、结构化报告节点的完整链路

当前文件：

```text
E:\IncidentAgent\stages\L4-langgraph\graph_with_report.py
```

流程：

```text
messages + observations
→ report_node 组织报告 Prompt
→ report_model.invoke()
→ response.content（JSON 字符串）
→ json.loads()
→ IncidentReport.model_validate()
→ report.model_dump()
→ 写回 State["report"]
```

报告字段由模型根据用户输入和工具事实生成，Pydantic 不负责推理，只负责校验。

```python
data = json.loads(raw_report)
report = IncidentReport.model_validate(data)
```

两步职责不同：

```text
json.loads：文本是不是合法 JSON
model_validate：JSON 结构和业务字段是否合法
```

校验成功：

```python
return {
    "report": report.model_dump(),
    "status": "completed",
    "error": None,
}
```

校验失败：状态改成 `degraded`，记录具体错误，不把非法报告当成成功结果。

工具失败时当前是严格策略：本轮任何工具失败，直接进入 `degrade`，因此不会生成报告。这是当前示例的明确设计，不是报告节点出错。

---

## 十一、测试与复盘

测试目标不是只看程序有没有异常，而是验证：

```text
输入是否得到预期工具结果
错误码是否统一
State 是否正确更新
图是否走到正确分支
报告是否符合结构契约
是否存在无限循环
```

当前测试文件：

```text
E:\IncidentAgent\stages\L5-test\test_cases.md
E:\IncidentAgent\stages\L5-test\test_tools.py
E:\IncidentAgent\stages\L5-test\test_report_models.py
E:\IncidentAgent\stages\L5-test\test_graph_with_report.py
```

测试分层：

1. 工具层测试：成功、未知工具、未知服务、非法 JSON、参数错误和额外字段；
2. 报告模型测试：合法报告、非法枚举和字符串证据兼容；
3. 图流程测试：正常报告、工具失败降级、非法报告降级和循环上限。

图测试使用 `FakeModel` 固定返回结果，不请求真实 API。真实模型适合人工演示，不适合作为稳定自动化测试的唯一依据。

运行命令：

```powershell
cd E:\IncidentAgent\stages\L5-test
py -m pytest -q
```

当前规划的测试场景至少包括：

```text
正常故障
无数据库关键词的超时
未知服务
空日志或缺参
知识库无结果
检索异常
服务状态超时
非法 JSON 报告
重复调用工具
达到最大循环次数
```

### 必须掌握

1. 测试应验证行为和结果，不只是验证代码运行；
2. 真实模型的工具选择具有不确定性，自动化测试应使用固定模拟模型；
3. 工具层、报告模型层和图路由层应该分层测试；
4. 失败案例需要记录现象、根因、当前行为和后续改进；
5. `UNKNOWN_SERVICE`、`INVALID_JSON`、`INVALID_ARGUMENTS` 等错误码应保持稳定。

---

## 十二、Incident Agent MVP 定位

Incident Agent 是一个面向微服务故障初筛的智能分析助手：

```text
用户提交故障现象和日志
→ Agent 决定需要哪些证据
→ 调用日志分析、知识库检索和服务状态工具
→ 记录消息、观察结果和执行轨迹
→ 处理工具失败和循环上限
→ 生成带引用的结构化故障报告
```

三个工具的职责：

```text
analyze_log：日志里发生了什么
search_knowledge：已有排障文档如何说明
get_service_status：相关服务当前是否健康
```

第一版暂不自动执行重启、改配置或服务器命令，只提供有证据的排查建议。

### 与 DevAtlas RAG 的边界

```text
DevAtlas RAG：文档解析、切分、向量化、知识库管理、检索服务
Incident Agent：工具选择、LangGraph 编排、状态管理、失败降级、轨迹和报告
```

Incident Agent 通过 `search_knowledge` 调用 DevAtlas，不复制 RAG 的切片和向量检索实现。这样是“基础平台 + 业务应用”的关系，而不是重复做两个 RAG。

### MVP 优先范围

```text
CLI 可运行
三工具闭环
正常和失败路径
最大循环保护
结构化报告
observations 和 steps 轨迹
保存一次运行结果
```

复杂前端、权限、自动修复、多 Agent、MCP 和深度 Redis 优化放到 MVP 之后。

### 正式项目目录原则

学习练习和正式项目分开保存，不删除已有内容：

```text
E:\IncidentAgent\stages\   学习练习代码
E:\IncidentAgent\docs\     笔记、规划和设计文档
E:\IncidentAgent\app\      正式 Incident Agent 代码
E:\IncidentAgent\tests\    正式项目测试
E:\IncidentAgent\runs\     运行记录和演示结果
```

---

## 十三、总调用链面试版

```text
用户输入故障
→ graph.invoke(initial_state)
→ START → agent
→ model_with_tools.invoke(messages)
→ AIMessage 可能包含 tool_calls
→ ToolNode 执行一个或多个工具
→ ToolMessage 写入 messages
→ observe 整理 observations 和 steps
→ 成功则回 agent，失败则 degrade
→ agent 不再请求工具时进入 report
→ report_model 生成 JSON
→ json.loads + IncidentReport.model_validate
→ 合法报告写入 State
→ report → END
```

面试级总结：

> 我使用 LangGraph 管理 Incident Agent 的有状态流程。模型负责根据故障上下文选择工具，ToolNode 负责执行工具，observe 节点把 ToolMessage 整理成 observations 和 steps；条件路由控制继续调用、报告生成、异常降级和最大循环。最终由独立报告节点生成 JSON，并通过 Pydantic 校验后返回结构化故障报告。知识库检索复用 DevAtlas RAG 服务，Agent 侧只负责决策和编排。

### 当前状态

```text
已完成：Agent 基础闭环学习、LangGraph 示例、结构化报告、异常分支和测试基础
当前任务：完成 Incident Agent MVP 第一版
后续任务：深入理解 DevAtlas RAG 和 Incident Agent 的正式代码、接口、数据库、Redis 与优化点
```
