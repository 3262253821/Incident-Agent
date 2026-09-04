# Agent 学习路线详细拆解（v3 秋招冲刺版）

> 目标：在 2026-09-15 前完成 Agent 基础闭环，并交付一个能在面试中讲清楚、能现场演示、能用数据说明效果的 Incident Agent。
> 工作目录：`E:\IncidentAgent`
> 已有项目：`E:\RagKnowledgeSystem`（DevAtlas，RAG MVP 已完成 T01-T14，当前重点是 T15 测试和交付）

## 先说结论

原 v2 的知识点顺序基本正确，但总工期不适合当前日期：基础 9 天 + 项目 14 天 = 23 天，超过 9 月 15 日前的 17 天。v3 做三个调整：

1. **基础只学到能独立实现 Agent 闭环**：LLM 调用、Prompt、Tool Calling、结构化输出、ReAct、LangGraph、异常和测试；MCP、Skill、多 Agent、PlanAct 延后。
2. **不复制 RAG 项目已有能力**：复用 DevAtlas 的检索接口/服务契约，Agent 项目把增量放在决策、编排、轨迹和评测。
3. **先做后端可验证 MVP，再做界面和包装**：没有稳定的工具调用轨迹和测试结果，前端页面不能算项目完成。

## 两个项目如何分工

| 项目 | 面试定位 | 必须讲出的核心能力 | 不再重复建设 |
|---|---|---|---|
| DevAtlas / RAG | 可靠知识库基础设施 | 文档解析、版本化、Embedding、Chroma 检索、权限、SSE、持久化 | 不在 Agent 项目重写上传、认证、向量入库 |
| Incident Agent | 可控的研发故障分析 Agent | 工具选择、ReAct/LangGraph 状态机、结构化报告、失败降级、轨迹记录、离线评测 | 不做泛聊天、多 Agent、复杂自主规划 |

推荐的组合叙事：**DevAtlas 提供有权限的证据，Incident Agent 决定何时调用哪些工具、如何根据结果继续或停止，并输出可追溯报告。**

## 截止 9 月 15 日的交付标准

### 必做（达到这些才算完成）

- 至少 3 个工具：`search_knowledge`、`analyze_log`、`get_service_status`。
- 一个明确的 LangGraph：`START → classify/plan → tool loop → validate → report → END`，有最大步数。
- 工具参数使用 Pydantic 校验；最终报告使用 Pydantic/JSON Schema 校验。
- 每一步记录 `run_id`、节点、工具名、参数摘要、耗时、结果状态和错误码；不得记录 API Key 和完整敏感日志。
- 至少 10 条离线测试样例，覆盖正常、缺参、无检索结果、工具异常、超时、未知服务、模型输出格式错误和循环上限。
- 至少一个可演示接口（CLI 或 FastAPI）；前端只做最小结果页，优先展示过程轨迹、引用和最终报告。
- README、架构图、一次成功演示和一次失败降级演示。

### 先不做

MCP Server、Skill 注册体系、PlanAct、多 Agent、Redis/Celery、Docker/K8s、复杂记忆、自动修复线上服务。这些内容可在 9 月 15 日后根据岗位补强，不能挤占 MVP 验收时间。

## 17 天日程（8 月 30 日 - 9 月 15 日）

每天建议 4-6 小时：2 小时学习/复述，2-3 小时编码，30 分钟记录结果。每天必须留下一个可运行或可检查的产物。

| 日期 | 主题 | 当日验收物 |
|---|---|---|
| 08-30 | LLM 最小底座：token、上下文、温度、幻觉、消息结构 | `docs/第一层-LLM基础认知.md`，能口述 4 个概念 |
| 08-31 | Prompt 契约：职责、边界、证据、不确定性、停止条件 | 改进后的 Incident System Prompt + 3 组输出对比 |
| 09-01 | 原生 Function Calling | 不用框架跑通一次“模型请求工具→执行→回传→回答” |
| 09-02 | 多工具注册与参数校验 | `stages/L3-tools/tools.py`、工具统一返回协议和异常协议 |
| 09-03 | 结构化输出 | `IncidentReport`、`ToolCallRecord` Pydantic 模型，拒绝非法报告 |
| 09-04 | 手写 ReAct | `stages/L4-react/react_loop.py`，最大循环次数、空结果和工具错误可结束 |
| 09-05 | LangGraph 基础 | `stages/L4-langgraph/graph.py`，State/Node/Edge/条件边与流程图一致 |
| 09-06 | 失败处理和可观测性 | 超时、异常、格式错误、循环上限；输出脱敏轨迹 JSONL |
| 09-07 | 冻结 Agent MVP 设计 | `docs/agent-mvp设计.md`：输入、State、工具契约、结束条件、错误码 |
| 09-08 | 接入 DevAtlas 检索 | 通过稳定函数或 HTTP 适配器调用 RAG；保留来源 `document/version/chunk` |
| 09-09 | Agent 核心编排 | 正常故障可完成：日志分析 → 知识检索 → 服务状态 → 报告 |
| 09-10 | 报告和引用 | 报告含摘要、分类、证据、原因、步骤、引用、置信度；引用可回溯 |
| 09-11 | API/CLI 和轨迹 | `/agent/runs` 或 CLI 可运行；支持 run_id、状态、步骤列表 |
| 09-12 | 自动化评测 | 10-20 条固定样例，统计工具选择准确率、报告通过率、失败类型 |
| 09-13 | 异常回归和性能基线 | 记录 P50/P95（若可测）、超时策略、最大步数、模型失败降级 |
| 09-14 | 演示和交付材料 | README、架构图、流程图、成功/失败截图或录屏、简历 bullet |
| 09-15 | 总验收和面试复述 | 从输入到报告完整演示；能回答设计取舍和 8 个失败场景 |

若某天延期，优先级依次为：**核心编排 > 结构化输出 > 评测 > 轨迹 > 前端美化 > 进阶协议**。

## 开工前环境检查（08-30 上午，30-45 分钟）

- 在独立虚拟环境中补齐并锁定实际依赖：`openai`、`python-dotenv`、`pydantic`、`langgraph`、`pytest`；使用 `pip freeze` 保存可复现版本。
- 创建 `.env.example`，只放变量名和占位符；`.env` 加入 `.gitignore`，不上传仓库、不放截图、不写入轨迹。
- 当前 `.env` 中已有疑似真实 API Key。应立即在服务商后台撤销并重新生成，之后只在本机环境变量中使用新 Key；文档、日志和演示全部脱敏。
- 先用一个最小脚本验证模型连通性和结构化输出，再开始工具编排；模型或网络不可用时，工具层必须支持 mock 数据，保证离线测试能运行。

## 推荐的 Agent MVP 边界

### 输入

```json
{
  "title": "订单服务返回 502",
  "content": "网关返回 502，订单服务无法连接数据库...",
  "knowledge_base_id": 1
}
```

### 工具契约

```text
search_knowledge(query, knowledge_base_id, top_k=5)
  -> {ok, sources: [{content, filename, version_id, chunk_index, distance}], error}

analyze_log(log_text)
  -> {ok, signals: [{type, value, line}], error}

get_service_status(service_name)
  -> {ok, service, status, deploy_version, error_count, checked_at, error}
```

工具只负责事实获取或解析，不能让工具内部调用另一个工具，也不能让 LLM 伪造工具结果。

### State 最小字段

```text
run_id, title, input_content, knowledge_base_id,
messages, plan_or_intent, tool_results, evidence,
steps, report, errors, iteration, max_iterations
```

### 结束条件

- 已获得足够证据并通过 `IncidentReport` 校验；
- 无检索结果或工具失败时，明确降级并说明缺少什么；
- 达到 `max_iterations` 时输出当前证据，不继续调用；
- 任何工具参数不合法都回到校验/修正分支，不能直接执行危险操作。

## 与 DevAtlas 的集成建议

第一版用适配器隔离依赖：

```text
Incident Agent
  └── RagGateway.search_knowledge()
        ├── 本地模式：直接复用 DevAtlas retrieval service
        └── 联调模式：调用 DevAtlas /api/v1/knowledge-bases/{id}/search
```

优先复用 DevAtlas 已有的 `retrieve_context()` 和 `RetrievedChunk` 语义；如果跨进程调用，则使用 HTTP 并在 Agent 侧转换成自己的工具返回协议。不要复制认证、文档解析、Embedding 和 Chroma 代码。

## 评测最小方案

建立 `stages/L5-test/test_cases.jsonl`，每条包含：输入、期望工具集合、是否必须引用、报告关键字段、允许的降级结果。至少覆盖：

1. 502 + 数据库连接失败；
2. timeout + 无数据库关键词；
3. 未知服务名；
4. 空日志/缺少标题；
5. 知识库无相关内容；
6. 检索工具抛异常；
7. 服务状态工具超时；
8. 模型返回非法 JSON；
9. 模型重复请求同一工具；
10. 达到最大循环次数。

先做规则化断言，不要一开始追求“模型回答像不像人”：工具是否选对、是否引用真实证据、Schema 是否通过、失败是否可控，才是 Agent 项目的硬指标。

## 秋招展示和简历证据

准备两段 3 分钟演示：

- 成功路径：输入故障日志 → 日志信号 → 检索来源 → 服务状态 → 结构化报告；
- 失败路径：模拟检索/服务状态超时 → 记录错误 → 停止循环 → 输出“证据不足”的降级报告。

简历只写真实测量值，格式可以是：

```text
Incident Agent｜研发故障分析智能体
- 基于 LangGraph 编排日志分析、知识检索和服务状态 3 类工具，使用最大步数、超时和错误分支控制 ReAct 循环。
- 复用 DevAtlas 的版本化 RAG 检索，报告保留 document/version/chunk 引用，避免无证据生成。
- 使用 Pydantic 约束工具输入和最终报告，记录脱敏工具轨迹，并用 N 条离线用例评测工具选择与失败降级。
```

不要把“支持 MCP、多 Agent、准确率 95%”写进简历，除非已经实现并完成可复现测试。

## 9 月 15 日之后的补强顺序

1. 评测集扩展、LLM-as-judge 与人工抽检；
2. LangGraph checkpoint/会话恢复和成本、延迟监控；
3. 将 3 个工具包装成 MCP Server；
4. 对比 ReAct 与 PlanAct；
5. 只有在真实场景需要时再引入多 Agent。

## 每日复盘模板

```text
今天实现了什么：
我能否不用看代码解释调用链：
一次失败是什么、根因是什么：
新增了哪条测试：
明天必须交付的文件/接口：
```
