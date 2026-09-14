# Incident Agent 项目优化清单（DeepSeek 审查版）

最后更新：2026-09-14

本文由 DeepSeek 对 `E:\IncidentAgent` 的完整源码审查后产出，用于记录 MVP 交付后**真实存在的设计漏洞、bug 和不完善之处**。原则与 DevAtlas 的补充优化一致：先修可靠性问题，再补测试和可观测性，最后才考虑框架和部署能力；不为了简历堆叠没有实际用途的技术。

**勾选规则（重要）**：只有「代码已经改完 + 有可复现的验证命令和结果」的条目才允许打勾 `[x]`。仅提出建议、仅讨论、仅写进设计文档但代码未实现的条目一律保持 `[ ]`。本文件首次生成时，所有条目均为 `[ ]`，因为本次交付只包含审查结论，不包含代码修改。

---

## 一、审查范围与验证基线

### 1.1 审查范围（逐文件读完，不是抽样）

| 层 | 文件 |
| --- | --- |
| 入口与配置 | `app/main.py`、`core/config.py`、`dependencies.py`、`db/session.py` |
| 持久化 | `models/agent_run.py`、`services/storage.py`、`migrations/versions/20260904_0001_*.py`、`migrations/env.py` |
| Graph | `graph/state.py`、`graph/nodes.py`、`graph/workflow.py` |
| 工具与服务 | `services/tools.py`、`services/rag_client.py`、`services/auth.py`、`services/llm.py`、`services/incident.py` |
| 契约 | `schemas/incident.py`、`schemas/tool.py`、`schemas/auth.py`、`schemas/rag.py` |
| 路由 | `routers/auth.py`、`routers/incidents.py`、`routers/runs.py` |
| 前端 | `web/src/**`（api / stores / router / components / views / types / styles） |
| 工程化 | `tests/**`、`requirements.txt`、`pyproject.toml`、`.gitignore`、`scripts/*.ps1`、`One-click launch.bat`、`README.md`、`docs/agent-mvp设计.md`、`docs/阶段6验收清单.md` |
| 未纳入 | `stages/**`（学习练习，按设计文档约定不作为正式模块）、`resume/**`（个人求职材料）、`tmp/**`（浏览器渲染产生的临时目录） |

同时把 `docs/agent-mvp设计.md` 当作**设计契约**逐节对照实现，凡是「设计里写了、代码里没有」的也作为不完善项记录，并标明出处章节。

### 1.2 本次真实执行的验证命令与结果

```powershell
cd E:\IncidentAgent
$env:PYTHONPATH="E:\IncidentAgent"

py --version                       # Python 3.13.2
py -m pytest tests -q              # 18 passed, 6 warnings in 4.57s
py -m ruff check app               # All checks passed!
py -m ruff check app migrations tests
                                   # Found 29 errors
                                   #   E402 ×19  module-import-not-at-top-of-file
                                   #   I001 ×8   unsorted-imports
                                   #   E731 ×1   lambda-assignment
                                   #   F401 ×1   unused-import
                                   # （再加 stages/ 是 45 个；README 只写 ruff check app，
                                   #   所以这些错误不在现有质量门禁口径内）
cd web; npm run build              # vue-tsc -b && vite build 成功，175.92 kB / gzip 66.53 kB
```

依赖告警原文（P2-1 的证据）：

```text
sqlalchemy/sql/schema.py:3624: DeprecationWarning: datetime.datetime.utcnow() is deprecated
app/incident_agent/services/storage.py:63: DeprecationWarning: datetime.datetime.utcnow() is deprecated
```

另外用一次性脚本对四个关键行为做了**运行时探针**（探针脚本写在 `tmp/` 下，验证后已删除，未提交）：

| 探针 | 输入 | 实际输出 | 结论 |
| --- | --- | --- | --- |
| `search_knowledge` 省略 `top_k` | `{"query":"订单服务 502","knowledge_base_id":3}` | gateway 收到 `top_k=5` | 工具静默回落到硬编码 5，请求里的 `top_k` 从未生效 |
| 模型越权检索别的知识库 | 请求 `knowledge_base_id=3`，工具却传 `999` | gateway 收到 `999` 且 `ok=True` | 工具不校验知识库范围，模型可越权检索任意 KB |
| 模型首轮不调用任何工具 | `AIMessage(content="无需工具")` + 合法报告 | `status="completed"`，`observations` 长度为 0 | 零证据也能拿到 `completed` |
| `IncidentReport.evidence=[]` | 空证据数组 | `ValidationError` | 该防线有效；但报告节点不校验 evidence 是否来自真实 observations |
| 运行列表 N+1 | 5 条 run，各 3 个 step | `list_runs_for_owner` 自身 1 条 SQL，访问 `.steps` 后再产生 5 条 | 列表接口是 O(N) 次查询 |
| `analyze_log` 词边界 | `"error code 15020"` | `signals=[]` | 正则 `\b502\b` 偶然挡住了 `15020`，属于「碰巧安全」而非有意设计 |

### 1.3 与 `docs/项目补充优化.md` 的关系

仓库里已有一份 `docs/项目补充优化.md`（同为 2026-09-14）。两份文档都基于同一份代码，因此有交叉，但**不是重复劳动**：

| `项目补充优化.md` | 本文件对应项 | 说明 |
| --- | --- | --- |
| P0-1 强制校验知识库权限 | P0-2-0a | 同一发现；本文件补充了「先 `create_run` 后校验」的具体代码位置和「只调日志工具即可完全绕过校验」的路径分析 |
| P0-2 敏感信息脱敏 | P0-2-0b | 同一发现；本文件补充了具体落库字段清单（`input_content` / `observations` / `arguments_summary`）和 `GET /runs` 会全量回吐这一点 |
| P0-3 服务端核验报告证据 | P1-2-2 | 同一发现 |
| P0-4 模型超时与错误码 | P0-3-1 + P1-3-2 | 本文件把它拆成「请求总超时」（运行时行为）与「模型配置集中化」（配置面）两项 |
| P1-1 报告 JSON 容错 | P1-3-1 | 同一发现 |
| P1-2 上下文大小截断 | P1-2-1 | 已并入「不可信内容定界 + 注入前截断」 |
| P1-3 步骤参数/结果/耗时 | P1-1-2 | 同一发现 |
| P1-4 运行历史分页与裁剪 | P0-4-1 + P0-4-2 + P1-5-5 | 本文件额外给出了 N+1 的实测 SQL 计数与时间字段缺失问题 |
| P1-5 并发与事务边界 | P0-3-3 + P0-3-2 | 同一发现 |
| P1-6 鉴权代理错误映射 | 未单列 | 属于可接受的低优先项；`DevAtlasAuthClient` 把非 401/403 一律折叠为 502，会丢掉 429/5xx 语义，建议并入 P1-3-4 一起做 |
| P1-7 状态常量集中化 | 未单列 | 同意该建议；当前 `status` 字符串散落在 `nodes.py` / `workflow.py` / `schemas` / 前端 `stores` 四处 |
| P1-8 安全与业务回归测试 | P1-4-1 | 同一发现，本文件补充了「owner 隔离无任何自动化测试」这个具体缺口 |
| P1-9 Ruff 门禁与 CI | P1-4-2 + P1-4-5 | 本文件给出了精确统计：`app migrations tests` 共 29 个（E402×19 / I001×8 / E731×1 / F401×1），含 `stages/` 为 45 个 |
| P2-1 ~ P2-6 | P2-5 / P2-3 / P2-1 / P2-6 / P1-5-4 / P1-3-3 + P1-4-4 + P2-7 | 逐条可对应 |

**本文件独有的发现**（`项目补充优化.md` 未覆盖）：

1. P0-1-1 `top_k` 全链路从未生效（有运行时探针证据）；
2. P0-1-2 工具把 `knowledge_base_id` 暴露给模型，可检索请求之外的知识库；
3. P0-1-3 `INCIDENT_DEFAULT_TOP_K` 是死配置、`AgentState["max_iterations"]` 是死字段；
4. P0-2-1 零工具证据也能拿到 `completed`（有运行时探针证据）；
5. P0-2-2 三种失败终态全部丢弃报告，与设计文档 16.5「不能因为模型失败就丢弃之前已经获得的证据」不符；
6. P0-3-2 被中断的 `running` 记录永久冻结，前端显示为假的 `DEGRADED`；
7. P1-2-1 Prompt 注入只有 Prompt 没代码约束（设计 16.3 有要求、实现为零）；
8. P1-2-3 `analyze_log` 信号不返回命中片段与行号；
9. P1-3-4 缺少统一异常处理器；
10. P1-4-3 `.gitignore` 遗漏 `tmp/`（1397 个浏览器临时文件）与 `resume/`（个人简历）；
11. P1-5-1 前端多语句单行写法导致可维护性差；
12. P1-5-4 前端无响应拦截器、401 判定依赖中文文案、网络抖动会被强制登出；
13. P1-5-5 前端从未调用 `GET /runs/{run_id}` 详情接口；
14. P2-4 无 token 与成本记录。

---

## 二、优化总顺序

```text
P0-1 top_k / knowledge_base_id 参数链路修复
→ P0-2 零证据 completed 状态语义修复
→ P0-3 请求级总超时 + 模型调用超时
→ P0-4 中断的 running 记录回收 + history 状态展示
→ P0-5 运行列表 N+1 与响应瘦身
→ P0-6 steps 轨迹补齐（arguments_summary / result_summary / duration_ms）
→ P1 可观测性、Prompt 注入与幻觉防线、时区与弃用 API、测试补齐
→ P2 SSE、前端工程化、CI、部分成功策略、评测集
```

---

## 三、P0：参数链路与真实 bug（必须最先修）

### 3.1 参数与越权

- [ ] **P0-1-1 修复 `top_k` 从未生效**

  - 涉及文件：`app/incident_agent/services/incident.py`、`app/incident_agent/services/tools.py`、`app/incident_agent/graph/state.py`
  - 现状与证据：
    - `_initial_state()` 把 `request.top_k` 放进 `state["top_k"]`，但**没有任何节点读取它**（全仓库 grep 只有写入没有读取）；
    - `build_tools()` 里的 `search_knowledge` 签名为 `top_k: int = 5`，模型省略该参数时静默变成 5；
    - 运行时探针确认：请求写 `top_k` 或省略 `top_k`，DevAtlas 收到的都是 5。
  - 设计契约：`docs/agent-mvp设计.md` 8.2 明确写 `top_k` 的作用是「传给检索工具的召回数量」；5.1 写明默认 5、范围 1-10、「可在 Agent 配置中固定」。当前实现与该契约不一致。
  - 目标流程：把 `top_k` 作为**服务端决定的本次运行上限**，而不是交给模型自由选择。
    ```text
    请求校验 top_k（1-10，默认取 INCIDENT_DEFAULT_TOP_K）
    → 写入 state["top_k"]
    → 构造工具时以闭包固定 knowledge_base_id 与 top_k
    → 模型即便传了别的值，也会被服务端钳制到请求值
    ```
  - 完成标准：请求 `top_k=8` 时，DevAtlas 检索请求体里的 `top_k` 必须是 8；模型传 `top_k=10` 或省略时，最终仍是 8；新增断言该行为的单元测试。

- [ ] **P0-1-2 禁止模型越权检索其他知识库**

  - 涉及文件：`app/incident_agent/services/tools.py`、`app/incident_agent/services/incident.py`
  - 现状与证据：`search_knowledge(query, knowledge_base_id, top_k)` 把 `knowledge_base_id` 暴露给模型；探针里请求 `kb=3`、模型传 `999`，工具照样调 DevAtlas 且返回 `ok=True`。
  - 当前风险：虽然 DevAtlas 会做 owner 校验（401/404 会转成 `RAG_UNAUTHORIZED` / `RAG_KNOWLEDGE_BASE_NOT_FOUND`），所以不是越权读数据；但这是**功能正确性 bug**——用户在 A 知识库提问，模型可能去查 B 知识库，答案与引用来源对不上，且用户无法从报告里发现。
  - 目标流程：`search_knowledge` 只接收 `query`，`knowledge_base_id` 与 `top_k` 由服务端在 `build_tools()` 时闭包注入；模型传了多余参数按 `extra="forbid"` 直接记为 `INVALID_ARGUMENTS`。
  - 完成标准：新测试断言「工具签名里不再出现 `knowledge_base_id`」「模型传 `knowledge_base_id` 会被拒绝而不是被采用」；真实联调时报告引用来源的 `document_id` 必须属于请求指定的知识库。

- [ ] **P0-1-3 清理失效配置与死字段，统一配置来源**

  - 涉及文件：`app/incident_agent/core/config.py`、`.env.example`、`docs/agent-mvp设计.md` 第 14 章
  - 现状与证据：
    - `INCIDENT_DEFAULT_TOP_K` 被读进 `Settings.default_top_k`，但全仓库没有任何地方使用它，是**死配置**；
    - `AgentState["max_iterations"]` 字段被写入却从未被读取（`route_after_agent` 用的是闭包里的 `max_iterations`）；
    - 设计文档第 14 章列的 `INCIDENT_WEB_HOST` / `INCIDENT_WEB_PORT` 在代码和 `.env.example` 里都不存在。
  - 目标：配置项要么真实生效，要么删除；`state` 里要么使用，要么移除。避免「文档说能配、实际不生效」这种最容易被面试追问击穿的点。
  - 完成标准：grep 证明每个 `Settings` 字段都有读取点；新增一条测试断言 `top_k` 默认值来自配置而不是硬编码字面量。

### 3.2 权限与数据边界（与 `docs/项目补充优化.md` P0-1 / P0-2 为同一发现，此处补充证据）

- [ ] **P0-2-0a 分析入口不校验知识库归属，未授权 ID 也会落库**

  - 涉及文件：`app/incident_agent/routers/incidents.py`、`app/incident_agent/services/incident.py`
  - 现状与证据：`IncidentAnalyzeRequest.knowledge_base_id` 只有 `Field(gt=0)`；`execute_incident()` 的第 97 行**先** `create_run()` 提交一条 `running` 记录，**然后**才调用模型。全仓库对 DevAtlas 的调用只有两处——`/auth/me`（换用户 ID）和 `/knowledge-bases/{id}/search`（检索）。也就是说：只要模型这一轮**没有**调用 `search_knowledge`（比如只调 `analyze_log` 或 `get_service_status`），Agent 全程不会向 DevAtlas 验证这个知识库是否存在、是否属于当前用户，却已经把它写进了 `agent_runs.knowledge_base_id` 并返回给前端历史。
  - 当前风险：不存在的 ID、别人的知识库 ID、已删除的知识库 ID 都能"分析成功"；历史记录里出现用户无权访问的知识库引用。设计文档 13.2 写的是「`knowledge_base_id` 的访问权限由 DevAtlas 根据 JWT 所属用户再次校验」——依赖检索工具被调用来间接完成校验，属于把安全边界交给模型决策。
  - 目标流程：
    ```text
    鉴权得到 current_user
    → 用同一个 token 调 DevAtlas 的知识库详情/授权接口校验 knowledge_base_id
    → 404/403 直接原样返回，且不创建 AgentRun
    → 校验通过后才 create_run 并进入 Graph
    ```
  - 完成标准：未授权/已删除/不存在的知识库在"只调日志工具"的路径下也无法启动分析；不产生任何 `agent_runs` 记录；新增 API 与服务层回归测试。

- [ ] **P0-2-0b 输入与工具结果未脱敏就持久化（设计文档 12.2 明确禁止）**

  - 涉及文件：`app/incident_agent/services/incident.py`、`app/incident_agent/services/storage.py`、`app/incident_agent/graph/nodes.py`
  - 现状与证据：`AgentRun.input_content` 存的是 `request.content.strip()` 原文（最长 20000 字符），`observations` 存的是完整 `ToolResult.model_dump()`（含 RAG 返回的 `content` 全文），`append_steps()` 会把 `arguments_summary` / `result_summary` 原样落库，`GET /api/v1/runs` 又把这些字段全量返回。设计文档 12.2 要求「禁止持久化完整生产敏感日志」「只保存参数摘要、工具名、错误码和必要的截断内容」，当前一行都没实现。
  - 当前风险：运维把带 `Authorization: Bearer …`、`password=…`、`mysql://user:pass@host`、手机号或业务数据的真实日志贴进来分析，这些内容会进 MySQL、进历史接口、进前端页面，且 `input_content` 没有任何长度截断。
  - 目标流程：进入 Agent 前按模式识别并掩码（Bearer/JWT、`password=`/`passwd=`、`api_key`/`secret`/`token`、连接串、身份证与手机号）；持久化只写脱敏后的文本；`observations` 里 RAG `content` 只保留截断摘要 + 来源 metadata；原始文本仅在本次请求内存中使用。
  - 完成标准：用含 `Authorization`、`password`、连接串的测试日志跑一次分析，MySQL 行与 `/runs` 响应里都搜不到原值；脱敏有单测覆盖误报（正常日志不被改坏）；`input_content` 有明确的长度上限。
  - 附带收益：这一项同时消掉了 P0-2-0b 与报告提示词注入之间的重叠风险（敏感内容不再被反复注入模型上下文）。

### 3.3 状态语义与失败补偿

- [ ] **P0-2-1 零证据不能算 `completed`**

  - 涉及文件：`app/incident_agent/graph/nodes.py`、`app/incident_agent/schemas/incident.py`、`app/incident_agent/services/incident.py`
  - 现状与证据：模型首轮返回不带 `tool_calls` 的 `AIMessage` 时，`route_after_agent` 直接走 `report`；即使 `observations` 为空，只要报告 JSON 结构合法（`evidence` 至少 1 条，但那条可以是模型凭空写的），最终就是 `status="completed"`。探针确认 `observations=0` 仍返回 `completed`。
  - 当前风险：用户看到 `COMPLETED` + `HIGH CONFIDENCE` 徽章，实际没有任何工具证据支撑，属于**最危险的一类幻觉包装**——结构合法被误当成事实可靠。
  - 目标流程：
    ```text
    observations 为空 且 无成功工具结果
    → 报告仍可生成，但 evidence.source 只允许 tool_error，或
    → 强制 confidence="low" 且 status 变为 insufficient_evidence
    → 前端展示「未取得任何工具证据」而不是 COMPLETED
    ```
  - 完成标准：新增测试「零工具调用运行」的断言从 `completed` 改为新的语义状态；前端对应该状态有独立标签与提示；浏览器验证该路径不会显示绿色完成徽章。

- [ ] **P0-2-2 降级与报告失败时保留部分结论**

  - 涉及文件：`app/incident_agent/graph/nodes.py`（`report_node` / `degrade_node`）、`app/incident_agent/services/incident.py`
  - 现状与证据：`report_validation_failed`、`degraded`、`max_iterations` 三种终态下 `report` 一律为 `None`，前端只能显示 `DegradedPanel`（工具名 + SUCCESS/错误码）和一句 `error` 文本。设计文档 16.5 要求降级结果必须包含「可以继续人工检查的建议」，当前只满足「status + 错误摘要 + observations」三项。
  - 目标流程：
    ```text
    报告 JSON 非法 → 按 P1-3-1 做一次修复重试
    修复仍失败 → 用已有 observations 组装「确定性降级摘要」
                （命中的日志信号、检索到的来源清单、失败工具与错误码、建议人工核对项）
    → report 保持 None，但新增 degraded_summary 字段返回给前端
    ```
  - 完成标准：三条失败路径（工具失败、报告非法 JSON、达到上限）都能返回结构化的人工可读摘要；新增测试断言该摘要里包含真实的 `document_id` / `chunk_index`，且**不包含**模型编造的内容。

### 3.4 超时、预算与并发

- [ ] **P0-3-1 给整个分析请求加总超时，避免请求无限挂起**

  - 涉及文件：`app/incident_agent/services/incident.py`、`app/incident_agent/core/config.py`、`.env.example`
  - 现状与证据：`DevAtlasAuthClient` / `HttpRagGateway` 有 20s 读超时；`ChatOpenAI` **没有设置任何超时**（`services/llm.py`，可用参数里没传 `timeout` / `max_retries`）；`graph.invoke()` 外面没有总时长限制。设计文档 11.4 建议「连接 3s / 读取 15s / 总请求 20s」，实现只覆盖了 DevAtlas 一侧。
  - 当前风险：DeepSeek 侧网络挂起时，请求会一直占着 FastAPI 的同步线程和 MySQL 连接；前端 `axios` 120s 超时后用户只看到「请求超时」，后端可能仍在跑并在稍后写入一条 `completed` 记录，用户以为失败了其实成功了（或反之）。
  - 目标流程：
    ```text
    Settings 增加 INCIDENT_REQUEST_TIMEOUT_SECONDS（如 90）与 INCIDENT_MODEL_TIMEOUT_SECONDS（如 30）
    → ChatOpenAI(timeout=..., max_retries=0)
    → execute_incident 用 deadline 包裹 graph.invoke
    → 超时统一落 status="timeout"/degraded，保留已产生的 steps 与 observations
    ```
  - 完成标准：新增测试用「会 sleep 的假模型」证明超时后状态为受控降级而不是 500，且已获得的 observations 被持久化；`.env.example` 与设计文档同步更新。

- [ ] **P0-3-2 回收被中断的 `running` 记录**

  - 涉及文件：`app/incident_agent/services/storage.py`、`app/incident_agent/routers/runs.py`、前端 `stores/incident.ts`
  - 现状与证据：`create_run()` 先写一条 `status="running"` 并 commit，随后才调用模型；如果进程在这之间被杀（Ctrl+C、OOM、`--reload` 重启），这条记录永远停在 `running`。列表接口会把它照常返回，前端 `IncidentWorkspaceView` 的 `statusLabel` 对任何非 `completed` 结果都显示 `DEGRADED`，于是用户永远看到一个假的 `DEGRADED`。
  - 目标流程：三选一或组合——① 启动时把超龄 `running` 批量标记为 `interrupted`；② 列表接口对超过 N 分钟的 `running` 动态视为 `interrupted`；③ 前端对 `running` 显示「已中断/未完成」并允许一键重跑同参数。
  - 完成标准：杀掉进程后重启，历史里不再出现冻结的 `running`；前端有对应标签；新增测试覆盖超龄 `running` 的标记逻辑。

- [ ] **P0-3-3 `append_steps` 的 `step_index` 并发安全**

  - 涉及文件：`app/incident_agent/services/storage.py`
  - 现状与证据：`append_steps()` 用 `SELECT count(*)` 推算 `next_index`，而 `agent_steps` 上有唯一约束 `uq_agent_steps_run_index(run_id, step_index)`。当前链路里一次请求只调用一次 `append_steps`，所以不会触发；但一旦加入「失败后追加重试步骤」「SSE 边跑边写」或任何并发写同一 run 的逻辑，就会直接撞唯一约束报 IntegrityError。
  - 目标：改为在同一事务内 `SELECT max(step_index) FOR UPDATE`，或直接使用数据库自增主键派生顺序；并补一条「连续两次 append_steps」的测试。
  - 完成标准：存在并发/多次追加场景下的测试通过，不出现唯一约束冲突。

### 3.5 查询性能与响应契约

- [ ] **P0-4-1 修复运行列表的 N+1 查询并给响应瘦身**

  - 涉及文件：`app/incident_agent/services/storage.py`、`app/incident_agent/routers/runs.py`、`app/incident_agent/schemas/incident.py`
  - 现状与证据：探针实测 5 条 run → `list_runs_for_owner` 1 条 SQL，随后访问 `.steps` 再产生 5 条 SQL，即 **N+1**；同时 `RunResponse` 里 `observations` 和 `steps` 是**全量**返回，列表接口把每条 run 的完整轨迹都吐给了前端，payload 随历史增长线性膨胀，而前端 `HistoryDrawer` 只用到了 `run_id`、`status`、`observations.length`。
  - 目标流程：
    ```text
    list_runs_for_owner 使用 selectinload(AgentRun.steps) 一次取回
    列表接口返回轻量 RunSummary（run_id / status / title / knowledge_base_id /
      started_at / completed_at / observation_count / step_count / error_code）
    详情接口 GET /api/v1/runs/{run_id} 保留完整 observations 与 steps
    前端历史抽屉只渲染 summary，点开时再拉详情
    ```
  - 完成标准：用 SQL 计数测试断言「列 10 条 run 的查询数不随 N 增长」；列表响应体大小显著下降；`GET /runs/{run_id}` 仍返回完整轨迹且保持 owner 隔离。

- [ ] **P0-4-2 时间字段缺失导致历史无法展示时间与耗时**

  - 涉及文件：`app/incident_agent/schemas/incident.py`、`app/incident_agent/routers/runs.py`、`web/src/components/HistoryDrawer.vue`、`web/src/types/api.ts`
  - 现状与证据：`AgentRun` 有 `started_at` / `completed_at` / `AgentStep.created_at`，但 `RunResponse` 一个时间字段都不返回；历史抽屉只能显示 `run_id.slice(0,12)` 和状态。设计文档 15.3 要求能回答「总耗时大致是多少？」，当前前端完全无法回答。
  - 完成标准：列表与详情都返回 `started_at` / `completed_at` / `duration_ms`；历史抽屉展示相对时间（如「3 分钟前 · 耗时 8.4s」）；时间统一为带时区的 ISO 8601 字符串（与 P2-1 一起做）。

---

## 四、P1：可观测性、安全防线、契约一致性

### 4.1 日志与轨迹

- [ ] **P1-1-1 引入结构化日志（当前项目完全没有日志）**

  - 涉及文件：新增 `app/incident_agent/core/logging.py`、`app/incident_agent/services/incident.py`、`app/incident_agent/graph/nodes.py`、`app/main.py`
  - 现状与证据：`grep "import logging"` 在 `app/` 下 0 命中，唯一的「日志」是 `db/session.py` 第 19 行的中文注释。设计文档第 15 章整章要求按 `run_id / step_index / node / tool_name / error_code / duration_ms` 记录，实现为零。
  - 当前风险：线上出问题时无法按 `run_id` 还原「模型调用了几轮、哪一轮哪个工具失败、是否命中过 RAG 超时」，只能靠数据库里的终态猜。
  - 目标流程：用标准库 `logging` + 一个 JSON formatter（不引第三方依赖），在 `create_run / finish_run / 每个节点 / 每次工具调用` 输出带 `run_id` 的结构化行；明确不记录 Token、API Key、密码、完整原始日志（设计文档 15.2）。
  - 完成标准：跑一次真实分析能在控制台按 `run_id` 串起全链路；新增测试断言日志里出现 `run_id` 且**不出现** Token 片段。

- [ ] **P1-1-2 补齐 steps 轨迹字段（设计已写、代码为空）**

  - 涉及文件：`app/incident_agent/models/agent_run.py`、`app/incident_agent/graph/nodes.py`、`app/incident_agent/services/storage.py`
  - 现状与证据：
    - `AgentStep.arguments_summary`、`result_summary`、`duration_ms`、`created_at` 四个字段存在，但 `make_agent_node` 只写了 `tool_call_count`，`make_observe_node` 不写参数摘要也不计时；
    - 全仓库没有任何地方产生 `arguments_summary` / `result_summary` / `duration_ms`，`storage.append_steps` 读到的永远是 `None`。数据库列、`runs.py` 的响应映射、前端 `AgentStep` 类型都在为这四个空字段做适配。
    - 设计文档 15.1 给出的目标结构是 `arguments_summary: {knowledge_base_id, top_k, query_length}` 与 `duration_ms`。
  - 目标流程：在 `tools` 节点外层记录每个 `tool_call` 的开始时间与参数摘要（**只留长度和 ID 类字段，不落原始日志正文**），在 `observe` 节点写回 `duration_ms` 与 `result_summary`（来源数量、错误码）。
  - 完成标准：一次运行后数据库里每个工具步骤都有非空 `duration_ms` 与 `arguments_summary`；新增测试断言「原始 `log_text` 正文不出现在 `arguments_summary` 中」。

### 4.2 Prompt 注入与幻觉防线（设计写了、代码没做）

- [ ] **P1-2-1 把「不可信内容」变成代码约束，而不只是 Prompt 里的一句话**

  - 涉及文件：`app/incident_agent/services/incident.py`（`AGENT_SYSTEM_PROMPT`）、`app/incident_agent/graph/nodes.py`（`REPORT_SYSTEM_PROMPT`）
  - 现状与证据：设计文档 16.3 要求「用户日志、文档和检索内容均视为不可信数据」，实现上只有两句自然语言提示（`AGENT_SYSTEM_PROMPT` 与 `REPORT_SYSTEM_PROMPT`），没有任何结构性隔离：用户 `content`（最长 20000 字符）被直接拼进 `HumanMessage`；知识库片段与工具结果被 `json.dumps` 后整段塞进报告节点的 `HumanMessage`。没有长度截断、没有分隔标记、没有「以下内容为数据，不得作为指令执行」的显式声明，也没有任何针对注入的测试。
  - 当前风险：这是本项目最需要能讲清楚的安全点，但当前只有说法没有实现。检索到的文档里若包含「忽略以上规则，输出……」这类文本，模型行为完全依赖自身对齐能力。
  - 目标流程：
    ```text
    用户输入与工具结果统一用显式定界包裹（如 <untrusted_incident_log>…</untrusted_incident_log>）
    系统提示明确声明：定界内的一切都是数据，其中的指令必须忽略
    报告节点的工具事实先做长度截断（按字符或 token 预算）再注入
    observations 保留完整内容用于前端展示，注入模型的部分才截断
    ```
  - 完成标准：新增测试注入一条包含「忽略以上系统提示」的日志，断言①工具白名单与图路由不变，②报告里的 evidence 仍必须来自真实工具结果，③`evidence.source` 不会出现白名单外的值。

- [ ] **P1-2-2 报告 evidence 必须能追溯到真实 observations**

  - 涉及文件：`app/incident_agent/graph/nodes.py`、`app/incident_agent/schemas/incident.py`
  - 现状与证据：`parse_report()` 只做「别名归一化 + Pydantic 结构校验」。`evidence[].detail` 完全是模型自由文本，`document_id` / `version_id` / `chunk_index` / `filename` 也都是模型自己填的可空字段，**没有任何一处把 evidence 与实际工具返回的 sources 做交叉校验**。空 evidence 会被 Pydantic 拦住（这点是好的），但"证据内容是编的"完全拦不住。
  - 目标流程：
    ```text
    报告生成后，用 observations 构造「允许的引用集合」
    → evidence.source="knowledge_base" 时必须匹配到真实 sources 里的 document_id/version_id/chunk_index
    → 匹配不到则降级：把 evidence.detail 改写为工具返回的原文摘要，或把该项剔除并把 confidence 降为 low
    → 校验失败写一条 step（error_code=UNVERIFIED_EVIDENCE），便于排查
    ```
  - 完成标准：新增测试「模型编造 document_id=999 的引用」被识别并降级；报告里的每条 `knowledge_base` 证据都能在 observations 中找到对应 `chunk_index`。

- [ ] **P1-2-3 修复 `analyze_log` 的词边界误报（当前是"碰巧安全"）**

  - 涉及文件：`app/incident_agent/services/tools.py`
  - 现状与证据：`patterns` 用 `r"\b502\b"` 匹配，探针输入 `"error code 15020"` 恰好没命中（因为 `15020` 中 `502` 前后的 `5`/`0` 都是单词字符）；但 `"502-Bad Gateway"`、`"HTTP/1.1 502"` 会命中，而 `"1502ms"` 这类语义无关的数字在别的写法下仍可能误命中。同时 `database_error` 用 `r"mysql|database|数据库"`，探针确认 `"MySQL OperationalError"` 会同时命中 `database_error` 与 `traceback` 两条信号，但返回值里两个 `value` 都是同一句 `"命中日志关键词"`，**没有给出命中位置或命中片段**。
  - 目标流程：把信号从「有没有命中」升级为「命中了什么、在哪一行」——返回 `type`、`matched_text`（原文片段，截断到 N 字符）、`line_number`；正则统一使用显式边界（如 `(?<!\d)502(?!\d)`）并补 `\b50[0-9]\b` 以覆盖其他 5xx。
  - 完成标准：新增测试覆盖 `15020`（不命中）、`502-Bad Gateway`（命中）、`MySQL OperationalError`（命中且带 line_number）；单元测试直接断言返回结构而不是只断言 `ok=True`。

### 4.3 契约、时区与模型配置

- [ ] **P1-3-1 报告非法 JSON 时增加一次修复重试**

  - 涉及文件：`app/incident_agent/graph/nodes.py`（`make_report_node`）
  - 现状与证据：报告模型返回非法 JSON 或结构不符时，直接进 `report_validation_failed` 且 `report=None`，没有任何重试。真实模型偶发输出带 Markdown 代码块（`REPORT_SYSTEM_PROMPT` 已经在提示「不要输出 Markdown 代码块」，说明作者知道这个现象），一次偶发就让整次运行丢掉报告。
  - 目标流程：第一次校验失败时，把「原始输出 + 校验错误信息」作为新的 HumanMessage 再请求一次（最多 1 次，可通过配置关闭）；同时容错剥离 ```` ```json ```` 围栏。
  - 完成标准：新增测试「首次返回 Markdown 围栏 JSON、第二次返回合法 JSON」最终得到 `completed`；新增测试「两次都失败」仍是受控失败且重试次数被记录进 steps。

- [ ] **P1-3-2 模型配置集中化（超时、token 上限、报告模型分离）**

  - 涉及文件：`app/incident_agent/services/llm.py`、`app/incident_agent/core/config.py`
  - 现状与证据：`create_chat_model()` 硬编码 `temperature=0.1`，没有 `max_tokens`、没有 `timeout`、没有 `max_retries`；`build_graph_with_gateway` 里 `report_model` 默认复用同一个模型实例，报告生成与工具决策共用配置。当前 `execute_incident` 每次请求都新建一个 `ChatOpenAI` 实例。
  - 目标：把 `temperature` / `max_tokens` / `timeout` / `max_retries` / 报告模型名提为 `Settings` 字段，在 `.env.example` 与设计文档第 14 章同步；模型客户端只在需要时构造，避免每请求重复初始化。
  - 完成标准：grep 证明 `llm.py` 里没有裸字面量配置；`Settings` 每个新字段都有 `.env.example` 对应项。

- [ ] **P1-3-3 迁移 `datetime.utcnow()` 到带时区时间**

  - 涉及文件：`app/incident_agent/models/agent_run.py`（3 处 `default=datetime.utcnow`）、`app/incident_agent/services/storage.py`（`finish_run`）
  - 现状与证据：`py -m pytest tests -q` 输出的 6 条告警里有 4 条来自 `models/agent_run.py` 经 SQLAlchemy 触发的 `datetime.utcnow()` 弃用告警，1 条来自 `storage.py:63`。`docs/阶段6验收清单.md` 的「已知限制」已经把这条列为待办，但一直没做。
  - 目标流程：统一改为 `datetime.now(UTC)` + `DateTime(timezone=True)`；因为涉及列语义变化，**必须走 Alembic 迁移**，并保证 `completed_at - started_at` 的计算在前后端都正确。
  - 完成标准：`pytest` 输出中不再出现该 `DeprecationWarning`；新增迁移文件且 `alembic check` 无漂移；前端显示的时间与本地时区一致。

- [ ] **P1-3-4 统一异常处理，避免内部细节外泄成 500**

  - 涉及文件：`app/main.py`
  - 现状：`main.py` 只有 `/health` 和 `/health/db`，没有 `exception_handler`。`/health/db` 的 `except Exception` 只返回 `{"status":"error"}`（这是对的，很安全），但业务接口没有等价保护：`execute_incident` 内部虽然 catch 了 `Exception` 并转 degraded，一旦在它之外（例如 `create_run` 写库失败、`schemas` 反序列化异常）抛错，FastAPI 默认 500 会把异常类名和堆栈打到服务端日志，响应体则是通用 500。
  - 目标：注册统一的异常处理器，保证①响应体只有安全的错误码和中文摘要，②服务端日志里带 `run_id` 便于定位，③永远不把 `str(exc)` 直接回给客户端。
  - 完成标准：新增测试构造一个会抛异常的依赖，断言响应里不含文件路径、不含 `Traceback`、状态码符合设计文档 13.3 表。

### 4.4 测试与工程化

- [ ] **P1-4-1 补齐设计文档 17.2 要求的测试用例**

  - 现状与证据：设计文档 17.2 列了 10 条最少案例，当前 `tests/` 只有 18 个测试且分布不均：`test_graph_workflow.py` 6 条覆盖正常/多工具/工具失败/报告非法/上限；`test_tools_adapters.py` 6 条覆盖工具名、成功、空结果、超时、非法参数、未知服务；`test_api.py` 5 条；`test_incident_service.py` 1 条。**缺口**：设计文档第 2 条「`timeout` 但没有数据库关键词」无对应用例；`analyze_log` 只有间接覆盖；`append_steps` / `finish_run` 的失败分支没有测试；`routers/runs.py` 的 owner 隔离（设计 13.3.1 要求「猜中别人的 run_id 也只能 404」）**完全没有自动化测试**，`test_api.py` 只测了未带 Token 的 401。
  - 目标：按设计文档 17.2 逐条补齐，重点是 owner 隔离、`analyze_log` 边界、失败分支持久化。
  - 完成标准：`pytest` 用例数显著上升且每条新测试能对应到设计文档的某一条要求；`docs/阶段6验收清单.md` 的清单同步更新真实结果。

- [ ] **P1-4-2 `ruff` 只覆盖 `app/`，其余目录 29 个错误不在门禁内**

  - 涉及文件：`pyproject.toml`、`tests/*.py`、`README.md`
  - 现状与证据：`py -m ruff check app` → `All checks passed!`；`py -m ruff check app migrations tests` → `Found 29 errors`，构成为 `E402 ×19`（每个测试文件重复的 `sys.path.insert` 造成 `Module level import not at top of file`）、`I001 ×8`（导入未排序）、`E731 ×1`（`test_graph_workflow.py` 用 `lambda` 赋值定义 `repeated_call`）、`F401 ×1`（未使用的导入）。加上 `stages/` 则共 45 个。`README.md` 的验证命令只写 `ruff check app`，等于**主动把测试代码排除在质量门禁之外**。
  - 目标：用 `[tool.pytest.ini_options] pythonpath = ["."]`（或加 `tests/conftest.py`）消除重复的 `sys.path` 技巧，让 `E402`/`I001` 自然消失；`E731` 改为 `def`；清理 `F401`；CI 与 README 统一为 `ruff check .`。
  - 完成标准：`py -m ruff check .` 无错误；`pytest` 仍全部通过；`README.md` 的验证命令同步更新。

- [ ] **P1-4-3 `.gitignore` 遗漏 `tmp/`，仓库里躺着 1397 个浏览器临时文件**

  - 涉及文件：`.gitignore`
  - 现状与证据：`git status --short` 显示 `?? tmp/`，实测该目录下有 1397 个文件（Chromium crashpad 的 `.pma` / `.bdic` / `.db` / `Local State` 等，来自渲染简历 PDF 的无头浏览器操作），另有 `?? resume/`（个人简历 PDF/HTML）。两者都**不在** `.gitignore` 里，一次 `git add .` 就会把 Chrome 用户数据目录和个人简历提交进仓库。
  - 目标：加入 `tmp/`（保留目录时可加 `!tmp/.gitkeep`）；在 `docs/项目交接文档.md` 里明确 `resume/` 的处置策略（建议同样忽略或移到仓库外）。
  - 完成标准：`git status --short` 不再出现 `tmp/`；`git check-ignore -v tmp` 有输出。

- [ ] **P1-4-4 依赖未锁定版本，环境无法复现**

  - 涉及文件：`requirements.txt`
  - 现状与证据：13 个依赖全部是浮动下限（`fastapi>=0.115`、`langgraph>=0.3`、`langchain-core>=0.3`…），没有 lock 文件，也没有 `requirements-dev.txt` 分离测试依赖（`pytest` 与运行时依赖混在一起）。`README.md` 声称的验证结果（如「23 passed」在 DevAtlas、本项目 18 passed）依赖具体版本组合。
  - 目标：`pip freeze` 或 `uv`/`pip-tools` 生成带哈希或至少带精确版本的锁文件；拆分 runtime / dev 依赖。
  - 完成标准：在新虚拟环境里按锁文件安装后 `pytest` 结果与基线一致；`README.md` 写明锁文件用法。

- [ ] **P1-4-5 无 CI，所有检查靠人手跑**

  - 现状：`.github/` 不存在，`README.md` 里的 `pytest` / `compileall` / `alembic check` / `ruff check` / `npm run build` 全靠人工执行。`docs/阶段6验收清单.md` 里 9 条自动化检查全部打勾，但没有任何机制防止回归。
  - 目标：加一条最小 GitHub Actions workflow：Python 3.13 → 安装锁文件依赖 → `ruff check .` → `pytest -q` → `npm ci && npm run build`。数据库相关测试保持可离线运行（当前测试已用 SQLite 内存库，这点很好，直接能上 CI）。
  - 完成标准：workflow 文件落地；`README.md` 加 CI 徽章；故意引入一个失败提交能证明 CI 真的拦得住。

---

## 五、P1：前端

- [ ] **P1-5-1 前端代码可读性：多语句单行写法需要拆开**

  - 涉及文件：`web/src/views/IncidentWorkspaceView.vue`、`web/src/views/LoginView.vue`、`web/src/components/ExecutionTrace.vue`、`web/src/components/DegradedPanel.vue`、`web/src/components/IncidentForm.vue`、`web/src/components/HistoryDrawer.vue`、`web/src/components/ReportPanel.vue`
  - 现状与证据：`IncidentWorkspaceView.vue` 只有 32 行却承载了整个工作台——第 16~18 行把 10 个 `const` 和 4 个 `computed` 用分号压在同一行，第 27~29 行把整个模板压成三行；`HistoryDrawer.vue` 的 `<template>` 是**单行 300+ 字符**；`ExecutionTrace.vue` 同样把 `defineProps`、两个 `function` 写在同一行。
  - 当前风险：这不是风格洁癖——面试官打开这个文件会直接形成「AI 生成后没整理」的印象；而且 diff 噪音大，任何改动都会整行重写，评审和回滚都困难。
  - 目标：按 Vue 官方风格展开为每个声明一行、模板缩进展开；`IncidentWorkspaceView` 拆出 `useStatusLabel` 之类的小组合式函数。
  - 完成标准：单行不再出现多条语句；`npm run build` 与 `vue-tsc -b` 仍通过；文件行数与结构能一眼看懂。

- [ ] **P1-5-2 前端类型与后端契约重复定义、无同步机制**

  - 涉及文件：`web/src/types/api.ts`、`app/incident_agent/schemas/*.py`
  - 现状与证据：`User` / `IncidentRequest` / `Observation` / `AgentStep` / `IncidentReport` / `RunResponse` 在 TS 里手写了一遍，且已经和后端不一致：`types/api.ts` 的 `AgentStep` 缺 `duration_ms` / `arguments_summary` / `result_summary`；`ReportPanel.vue` 使用 `item.chunk_index`，但 `IncidentReport.evidence` 类型里有 `version_number` 而模板从不使用；`AgentStep.ok` 只存在于前端类型，后端 `steps` 里不存在该字段（后端是 `observations[].result.ok`）。
  - 目标：由 FastAPI 的 OpenAPI schema 生成 TS 类型（`openapi-typescript`），或在 CI 里比对手写类型与 schema 的差异，防止漂移。
  - 完成标准：类型由生成物提供或有 CI 校验；删除前后端都不使用的字段。

- [ ] **P1-5-3 前端零测试、零可访问性**

  - 涉及文件：`web/package.json`、`web/src/styles.css`、`web/src/components/*.vue`
  - 现状与证据：
    - `package.json` 只有 `dev` / `build` / `preview`，没有任何测试脚本，`devDependencies` 里也没有 vitest/playwright，实测 `web/src` 下测试文件数为 0；
    - `styles.css` 第 47 行 `input, textarea, select { ... outline: 0; }` 把键盘焦点环去掉且没有 `:focus-visible` 替代样式，全仓库 `focus-visible` / `prefers-reduced-motion` 命中数为 0；
    - 历史抽屉是裸 `div`，没有 `role="dialog"`、没有 ESC 关闭、没有焦点管理；`ExecutionTrace` 的加载态没有 `aria-live`，`styles.css` 里的 `.spin` 动画也没有遵守 `prefers-reduced-motion`。
  - 目标：加 vitest + @vue/test-utils 覆盖 store 与关键组件；补 `:focus-visible`、`role="dialog"` + ESC + 焦点回收、`aria-live="polite"`、`prefers-reduced-motion`。
  - 完成标准：`npm run test` 存在且通过；Tab 键能看清焦点位置；ESC 能关抽屉；开启系统「减少动态效果」后旋转动画停止。

- [ ] **P1-5-4 登录态与 401 处理不完整**

  - 涉及文件：`web/src/api/client.ts`、`web/src/stores/auth.ts`、`web/src/router/index.ts`、`web/src/views/IncidentWorkspaceView.vue`
  - 现状与证据：
    - `client.ts` 只有请求拦截器加 Token，**没有响应拦截器**，任何接口返回 401 都不会自动登出；
    - `IncidentWorkspaceView.vue` 第 20 行用 `apiErrorMessage(failure).includes('401')` 判断是否登出——`apiErrorMessage()` 已经把 detail 转成中文文案（如「登录状态无效或已过期」），只有在**没走到 detail 分支**时才会 fallback 成 `请求失败（HTTP 401）。`。也就是说这条判断依赖错误消息的具体文案，极其脆弱；
    - `router/index.ts` 的守卫只检查 `localStorage` 里有没有 Token，不校验有效性；`auth.restore()` 在**任何**异常（包括后端暂时不可用）时都直接 `signOut()`，网络抖动会把用户踢掉。
  - 目标：加响应拦截器统一处理 401（清 Token + 跳登录 + 保留 `redirect` 参数）；区分「Token 失效（401）」与「后端不可达（无 response）」，后者只提示不登出。
  - 完成标准：Token 过期后任意接口调用会自动跳登录且不残留脏状态；后端停机时用户不会被强制登出；有对应组件/store 测试。

- [ ] **P1-5-5 历史抽屉功能单薄（且详情接口未被使用）**

  - 涉及文件：`web/src/components/HistoryDrawer.vue`、`web/src/stores/incident.ts`、`web/src/api/runs.ts`
  - 现状与证据：后端同时提供了 `GET /api/v1/runs` 和 `GET /api/v1/runs/{run_id}`（设计文档 13.1 两个都在），但前端只实现了 `listRuns()`，**从未调用详情接口**；抽屉只显示 `run_id.slice(0,12)`、`status` 和 `observations.length`，没有时间、没有标题、没有分页或「加载更多」（后端 `limit` 最大 100，默认 20），也没有删除或「按原参数重跑」。列表刷新只能靠重新打开抽屉。
  - 目标：抽屉展示标题 + 时间 + 状态 + 耗时；点击行调用详情接口拉完整轨迹（配合 P0-4-1 的列表瘦身）；加分页或 `limit` 选择；加「用相同参数重跑」。
  - 完成标准：历史里能看到时间与标题；点开后轨迹与报告完整还原；超过 20 条时可继续加载。

- [ ] **P1-5-6 前置校验缺失，错误提示粒度粗**

  - 涉及文件：`web/src/components/IncidentForm.vue`、`web/src/api/client.ts`
  - 现状与证据：`v-model.number` 输入的「知识库 ID」为空时得到 `NaN`，直接提交会拿到 422；`top_k` 用 `select` 所以安全。`client.ts` 的 `apiErrorMessage` 对数组型 detail 一律返回「请求参数校验失败，请检查输入。」，**丢掉了具体是哪个字段错了**。`IncidentWorkspaceView.vue` 的 `statusLabel` 把所有非 `completed` 结果（`degraded` / `report_validation_failed` / `max_iterations` / `running`）统一显示为 `DEGRADED`，用户无法区分「工具失败」和「达到循环上限」。
  - 目标：字段级 422 错误映射（`loc` → 中文标签）；状态标签细分；提交前做本地必填校验。
  - 完成标准：非法知识库 ID 在提交前就被拦下并给出字段级提示；三种失败状态在前端显示为不同标签与文案。

- [ ] **P1-5-7 `.gitignore` 未覆盖前端构建产物的验证口径**

  - 现状：`.gitignore` 有 `node_modules/` / `dist/` / `.vite/`（正确），但缺少 `.env.local`、`.env.*.local`、`*.tsbuildinfo`。当前 `web` 用 `vue-tsc -b`（build 模式），会产生 `tsconfig.app.tsbuildinfo` / `tsconfig.node.tsbuildinfo`。
  - 完成标准：`git status --short` 在构建后保持干净；`.gitignore` 补齐三类忽略。

---

## 六、P2：渐进式增强

- [ ] **P2-1 SSE 流式分析（设计文档 13.4 已定接口，未实现）**
  - 设计契约：`POST /api/v1/incidents/analyze/stream`，事件 `step` / `observation` / `report` / `done` / `error`。
  - 现状：只有同步 `POST /api/v1/incidents/analyze`；`docs/阶段6验收清单.md` 的「已知限制」写明「Web 暂时是同步 JSON，不是 SSE」；同步端点还会长时间占用 FastAPI 线程池，并发能力受限（与 P0-3-1 的时间预算一起考虑）。
  - 完成标准：SSE 端点落地且与同步端点返回同一份终态；前端能边跑边显示轨迹；断线重连或至少能通过 run_id 回查结果。

- [ ] **P2-2 部分成功继续报告策略**
  - 设计文档 9.3 明确写：当前是「同一轮任意工具失败就整体降级」，并注明「后续可新增「部分成功继续报告」的策略，但必须单独测试」。
  - 现状：`route_after_observe` 只要 `status == "tool_failed"` 就直接 `degrade`，多工具场景下第一个失败会丢掉同轮其他工具的证据价值。
  - 完成标准：新增策略开关 + 独立测试（至少覆盖「1 成功 + 1 失败」时报告里出现成功工具的证据，并明确标注失败工具）。

- [ ] **P2-3 评测集与回归基线**
  - 现状：`docs/Agent学习路线详细拆解-v3-秋招冲刺.md` 把「离线评测」写进项目定位，但仓库里没有任何评测集、没有固定用例的期望来源、没有成本/耗时记录。真实模型输出不稳定，目前只能靠 `FakeModel` 保证自动化稳定（这个取舍是对的）。
  - 目标：建 `evals/` 放一组固定输入（正常 502、纯 timeout、无相关内容、越权知识库、超长日志），记录期望行为（必须调用的工具、必须命中的 error_code、引用必须来自哪个 document），并允许真实模型离线跑并输出报告。
  - 完成标准：一条命令跑完评测并输出结构化结果；结果入库到 `docs/`，且**不写虚构准确率**。

- [ ] **P2-4 模型调用 token 与成本可观测**
  - 现状：`RunResponse` 与 `agent_runs` 都不记录 token 用量和模型耗时，无法回答「一次分析花了多少 token」。
  - 完成标准：从模型响应里取 usage 落库（新列走 Alembic 迁移），详情接口返回。

- [ ] **P2-5 `get_service_status` 从 mock 走向可插拔 provider**
  - 现状与证据：`services/tools.py` 里两个服务（`order-service` / `user-service`）的状态、版本号、错误数全部硬编码在函数体内，`docs/复习规划.md` 第 301 行也已把它标为「讲解加分，代码可选」。硬编码导致「未知服务」是唯一可复现的失败路径，演示多样性受限。
  - 目标：抽出 `ServiceStatusProvider` 协议（`MockProvider` 保留为默认），并让 mock 数据可通过配置注入，至少覆盖 healthy / degraded / down 三种状态。
  - 完成标准：工具行为有测试覆盖三种状态；README 与设计文档同步说明当前仍是 mock。

- [ ] **P2-6 前端 E2E 冒烟（真实链路）**
  - 现状：`docs/阶段6验收清单.md` 的手工验收表 7 条场景全靠人工执行，没有自动化。
  - 目标：Playwright 冒烟覆盖「登录 → 提交分析（打桩后端）→ 看到轨迹与报告 → 打开历史」。
  - 完成标准：E2E 可在 CI 中离线运行（模型与 DevAtlas 均打桩）。

- [ ] **P2-7 Docker / 部署**
  - 现状：`docs/阶段6验收清单.md` 明确「未实现真实监控、Kubernetes、Redis、Prometheus 和自动修复」；一键启动依赖 `E:\` 绝对路径的 bat + PowerShell。
  - 原则：**不为了简历堆 Docker**。只有当需要把两个服务交给别人复现时再做，且优先 `docker compose` 起 Agent + MySQL（DevAtlas 作为外部依赖）。

---

## 七、建议的执行批次

> 注：编号 `P1-4-3`（`.gitignore` 遗漏 `tmp/` 与 `resume/`）虽然编号在 P1，但它是零风险、一分钟可完成的改动，且不做的代价是一次 `git add .` 就把 1397 个 Chrome 临时文件和个人简历提交进仓库，因此把它提到批次 A 一起做。

```text
批次 A（修 bug，改动小、收益大）：
  P1-4-3（先做，一分钟） / P0-1-1 / P0-1-2 / P0-1-3 / P0-2-1 / P0-2-0a / P0-2-0b
  产出：仓库不再有误提交风险 + 参数链路正确 + 知识库归属先校验 +
        敏感内容不落库 + 零证据不再伪装 completed

批次 B（可靠性与可观测）：
  P0-3-1 / P0-3-2 / P0-4-1 / P0-4-2 / P1-1-1 / P1-1-2
  产出：超时可控、中断可回收、列表不再 N+1、日志可按 run_id 串起

批次 C（安全与契约）：
  P1-2-1 / P1-2-2 / P1-2-3 / P1-3-1 / P1-3-2 / P1-3-3 / P1-3-4
  产出：注入与幻觉有代码级防线、时区与弃用 API 清理、异常不外泄

批次 D（工程化）：
  P1-4-1 ~ P1-4-5 / P1-5-1 ~ P1-5-7
  产出：测试补齐、lint 全仓、CI 拦截、前端可读性与可访问性、历史抽屉可用

批次 E（增强，视时间决定）：
  P2-1 ~ P2-7
```

---

## 八、每项优化的记录模板

完成一项后，在本文件下方「十、已完成优化记录」里按下面的格式追加，并把该项的 `[ ]` 改成 `[x]`：

```markdown
### [日期] [任务编号] 任务名称

- 原来的行为：
- 存在的风险或不一致：
- 修改的文件：
- 修改后的流程：
- 新增或更新的测试：
- 测试命令与结果：
- 是否影响数据库迁移：是 / 否
- 是否影响 API 契约：是 / 否
- 是否影响前端：是 / 否
- 简历可用事实：
```

---

## 九、简历使用原则（沿用 DevAtlas 的纪律）

- 只有代码已经实现并通过测试的内容，才能写进简历。本文件里所有 `[ ]` 条目**都还不能写**。
- 不写虚构的上线规模、准确率、吞吐量、并发数、用户量。
- 以下几条是可以写、但必须先把话说准的：
  - 当前真实吞吐是「演示级、无线程池与超时治理」，不能写「高并发」；
  - `get_service_status` 是**显式 mock**，不能写「接入监控系统」；
  - 「防 Prompt 注入」在 P1-2-1 完成前只能写「已知风险与改进方向」，不能写「已实现防护」；
  - SSE、Docker、Redis、多 Agent、真实监控均未实现，只能写「了解 / 规划中」。
- 反过来，本项目**已经具备**的、可以现在就写的能力：LangGraph 条件路由与循环保护、统一 `ToolResult` 协议与错误码归一化、Pydantic 双层校验（工具入参 + 最终报告）、`owner_user_id` 级运行记录隔离、JWT 只在请求内转发不落库、MockRagGateway + FakeModel 的确定性测试体系、跨 MySQL/DevAtlas 的边界错误归一化。这些都有对应代码和测试可指。

---

## 十、已完成优化记录

（暂无。本文件首次生成时只包含审查结论，未包含代码修改。任何一项完成后在此追加记录并回填勾选。）

### 本次交付说明

- 新增文件：`docs/项目优化-DeepSeek.md`（本文件）。
- 修改的源码：无。本次只做审查与文档，**没有改动任何业务代码**，因此 P0/P1/P2 全部保持 `[ ]`，符合本文开头的勾选规则。
- 未纳入版本控制的本地改动（不属于本次交付，提交时已排除）：`docs/项目交接文档.md` 的既存修改、`docs/复习规划.md`、`docs/项目复习笔记整理.md`、`resume/`、`tmp/`。
- 审查用的临时探针脚本已删除，未提交。
