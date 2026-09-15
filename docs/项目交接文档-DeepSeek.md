# Incident Agent 交接文档（DeepSeek 会话）

> 用途：**上下文压缩、会话切换或换模型后的第一恢复入口**。新会话读完本文即可接手，不需要回溯历史对话。
>
> 最后更新：2026-09-15（P1-3-1 完成，`HEAD`=`432baff`）
>
> 项目根目录：`E:\IncidentAgent`｜关联项目：`E:\RagKnowledgeSystem`（DevAtlas）
>
> 本文件由 DeepSeek 在本轮会话结束时编写。仓库里原有的 `docs/项目交接文档.md`（2026-09-04）是上一轮的版本，**未包含本轮任何内容**；本文是当前有效版本。

---

## 1. 用户与求职背景（影响"该做什么"的判断）

- 淮安大学软件工程专业，**2027 年 6 月毕业**（大四上），目前无实习，正在秋招中。
- 求职方向：**AI 应用开发 / LLM 应用开发 / Python 后端**。两个项目：DevAtlas（知识库基础设施）与 Incident Agent（本项目，Agent 编排层）。
- 现实约束：学校课程多、每天至少两节课，**在校时间碎片化**，因此要求"一项一项推进、每完成一项就测试并提交"。
- 简历纪律（必须遵守）：只有**代码已实现并通过测试**的内容才能写进简历；不写虚构的准确率/吞吐量/用户量。当前**未勾选**的条目一律不能写成"已实现"。

### 用户的明确工作约束（与本文档同等重要）

1. **一次只做一项，做完等指示**再继续下一项。
2. **不要 `git add .`**：改了什么就提交什么，commit message 要说明做了什么。
3. **每完成一项就提交并推送到仓库**，出问题可回退。
4. **打勾规则（用户本轮明确要求）**：`实现 + 测试通过 + 已推送` 三者齐了才允许把 `[ ]` 改成 `[x]`；未做的必须保持未勾选。
5. 不为了简历堆砌技术（不引入 Redis/MCP/Docker 等，除非有真实需求）。
6. `stages/` 是学习练习，保留但不作为正式模块；用户个人材料（简历、复习笔记）不得提交。

---

## 2. 仓库与协作方式

```text
仓库地址（公开）: https://github.com/3262253821/Incident-Agent
GitHub 账号     : 3262253821
默认分支        : main
本机路径        : E:\IncidentAgent
提交作者信息    : Hello World <chuanjianzhu1014@outlook.com>
```

### 推送注意（本轮踩过多次）

- 国内直连 `github.com:443` 时通时断。已配置**只对 GitHub 生效**的代理：

  ```powershell
  git config --global "http.https://github.com.proxy" "http://127.0.0.1:7897"
  ```

  对应的 Clash Verge 混合端口是 `7897`。若推送报 `Recv failure: Connection was reset` 或 `Failed to connect to github.com port 443`，**先确认梯子开着**，再重试；提交本身在本地是安全的，不要慌着重来或改历史。
- 另有两项本轮设过的配置：`http.version=HTTP/1.1`（排查 HTTP/2 重置）与 `http.postBuffer=157286400`。保留无害。
- **GitHub Actions 的实际运行结果始终未能自动确认**：查询 `api.github.com` 时被匿名配额限流（`x-ratelimit-remaining: 0`）。需要人工打开 `https://github.com/3262253821/Incident-Agent/actions` 查看。

### 隐私处理（已生效）

`.gitignore` 已挡住并验证（`git check-ignore -v` 全部命中）：`resume/`（个人简历，含姓名/电话/邮箱）、`tmp/`（实测 1397 个 Chrome 临时文件）、`docs/复习规划.md`、`docs/项目复习笔记整理.md`、`*.tsbuildinfo`、`.env.local`。`.env` 从未被跟踪，仓库里只有 `.env.example`。

---

## 3. 本轮我做的事（TL;DR）

对本项目做了一次**完整源码审查 + 优化实施**，产出一份带优先级勾选框的优化清单，并按批次实现、测试、推送。

| 指标 | 上一轮开始时 | 当前 |
| --- | --- | --- |
| 提交数 | 0（上一轮） | **27 个提交**（`f5af0d7` … `d0d711f`） |
| 测试用例 | 18 passed | **304 passed, 0 warnings** |
| 测试文件 | 4 个（用户原有） | 24 个（**新增 20 个**，另有 `tests/conftest.py`） |
| ruff（全仓） | 193 个错误 | **0** |
| 弃用/SQLAlchemy 警告 | 131 条 | **0** |
| 数据库迁移 | 1 个（`20260904_0001`） | 3 个（新增 `370ee3c8987d` 中断标记列、`c78153d58823` 降级摘要列） |
| 清单完成度 | — | **已勾 28 项（含审计基线）/ 未勾 19 项**（其中 4 项是"暂不建议直接加入"） |

当前 `HEAD` = `d0d711f`，工作区干净，本地与 `origin/main` 一致。

---

## 4. 我对齐的两个文档（对哪个文件优化）

| 文件 | 作用 |
| --- | --- |
| `docs/项目补充优化.md` | **唯一的优化清单与进度台账**。由用户把我（DeepSeek）的审查版与 Codex 的审计版合并而成。包含优先级、完成标准、完成记录、打勾规则、执行顺序记录。**这是继续工作的唯一任务源。** |
| `docs/项目优化-DeepSeek.md` | 我最初的独立审查报告（41 项，含运行时探针证据、与另一份清单的逐条对应表）。作为证据留档，**不再作为执行入口** |
| `docs/agent-mvp设计.md` | 项目自身的设计契约。审查时逐节对照它来判断"设计写了但代码没做"的缺口；本轮我把多处实现补进它的对应章节 |
| `docs/项目交接文档.md` | 上一轮（2026-09-04）的交接文档，**已过期且含本轮内容为零**；在 PowerShell 里读会中文乱码，用文件工具读正常 |

---

## 5. 具体流程（新会话照这个走）

```text
1. 读 docs/项目补充优化.md，找到第一个未勾选且优先级最高的条目
   （当前应做：P1-4-1 补齐设计文档要求的测试；P1-3 整组已于本会话完成）

2. 读该条目下面列出的「涉及文件」，先读代码再动手，不要凭记忆假设接口
   —— 涉及 DevAtlas 接口时必须读 E:\RagKnowledgeSystem\backend 的真实代码

3. 实现改动，然后按顺序验证：
     py -m pytest tests -q            # 必须全绿；若警告数上升要查原因
     py -m ruff check .               # 全仓必须 0（CI 也跑这条）
     py -m compileall -q app migrations tests
     py -m alembic check              # 只在动了 models/ 时才需要（本机 MySQL）
     cd web; npm run build            # 只在动了前端时才需要

4. 做「反证」：把修复临时回退成旧行为，确认相关测试确实会失败，再恢复
   —— 这是本项目每项完成记录里都有的固定动作，也是能写进简历的证据

5. 更新 docs/项目补充优化.md：打勾 + 写完成记录（改了什么文件、怎么验证、
   反证结果、测试结果、是否影响迁移/API/前端、简历可用事实）

6. 提交（逐文件 git add，不用 git add .），message 说明做了什么并附验证结果

7. 推送；若失败先查梯子，再重试；推送后核对 local == origin
```

### 一条重要经验（本轮多次验证）

**写测试 ≠ 功能完整。** 本轮有一个真实缺口（降级摘要只存在响应里、没入库），是在**把服务真的启动起来、打真实 HTTP 请求、检查真实序列化输出**时才发现的，209 条测试当时全绿也没抓到它。因此对"当次响应 / 历史回查"这类一致性问题，务必做一次活体验证。

---

## 6. 已完成的内容（28 项含审计基线，每项都满足"实现+测试+推送"）

| 项目 | 一句话说明 | 提交 |
| --- | --- | --- |
| P0-1-1 / -2 / -3 | `top_k` 全链路真正生效；工具不再把 `knowledge_base_id` 暴露给模型；清理死配置与死字段 | `f5af0d7` |
| P0-2-1 | 分析入口强制校验知识库归属，失败不产生任何运行记录 | `f698820` |
| P0-2-2 | 输入与工具结果在进模型前、落库前脱敏（Bearer/JWT/密码/连接串/手机号等） | `9fbe409` |
| P0-3-1 | 零工具证据不再伪装成 `completed`，返回 `insufficient_evidence` + 强制 `confidence=low` | `2029157` |
| P0-3-2 | 服务端核验报告证据来源，无法追溯的引用被剔除并由服务端回填真实 metadata | `8a780cf` |
| P0-3-3 | 失败时生成确定性降级摘要（不经过模型） | `da17d52` |
| P0-3-3b | 补修：降级摘要入库，历史记录与当次响应一致 | `e8941d2` |
| P0-4-1 | 模型调用超时 + 请求总预算（协作式 deadline）+ SDK 异常归一化为 `MODEL_*` 错误码 | `6b5f0e5` |
| P0-4-2 | 启动时回收被中断的 `running` 记录（新增 `interrupted_at` 列） | `6b5f0e5` |
| P0-4-3 | `append_steps` 改为幂等整体替换，消除唯一约束冲突风险 | `6b5f0e5` |
| P1-1-1 | 结构化日志（每行一个 JSON，按 `run_id` 串起全链路，字段级脱敏） | `40767df` |
| P1-1-2 | 步骤轨迹补齐 `duration_ms` 与脱敏摘要 | `40767df` |
| P1-1-3 | 不可信内容定界（`<untrusted-*>`）+ 注入形状中和（保留原文） | `ec8d46b` |
| P1-1-4 | `analyze_log` 返回命中片段与行号，改用显式数字边界 | `40767df` |
| P1-2-1 | 报告 JSON 容错解析（围栏/前后文字/尾随逗号）+ 最多一次修复重试 | `f2c788d` |
| P1-2-2 | 模型配置集中到 `Settings`，报告模型与决策模型分离 | `f2c788d` |
| P1-2-3 | 改用 `datetime.now(UTC)`，测试警告 131 → 0（**刻意不加带时区列，理由见清单记录**） | `f2c788d` |
| P1-2-4 | 统一异常处理器：错误响应统一为 `detail`/`error_code`/`request_id`，兜底 500 不泄露堆栈；鉴权代理不再把上游 422/429/5xx/超时全折叠成 502 | `5d6a0eb` |
| P1-3-1 | 历史列表改为**一条 SQL** 的 `RunSummary` 摘要契约（steps 子查询计数、observations 用方言 JSON 长度函数就地计数），详情接口用 `selectinload` 返回完整轨迹 | `abd15e5` |
| P1-3-2 | 两个接口都返回 `title` / `started_at` / `completed_at` 与派生的 `duration_ms`（未结束或被回收的中断运行明确为 `null`）；前端展示相对时间与耗时 | `efebf8c` |
| P1-3-3 | 历史列表改游标分页（`(started_at, id)` 行值比较，每页一条 SQL）+ 状态/时间过滤 + 可配置保留策略（默认关闭，删除带审计日志） | `19e3e12` |
| P1-3-4 | 权限与失败分支回归测试：越权与不存在 ID 响应不可区分、过期令牌三入口 401 且零副作用、数据库写失败安全 500 并可回收、失败状态确实落库 | `d0d711f` |
| P1-4-2 | 全仓 ruff 清零并把 CI 门禁扩到全仓 | `0f67b91` |
| P1-4-3 | `.gitignore` 补齐（隐私与临时文件） | `062ee69` |
| P1-4-4 | 锁定依赖（`requirements-lock.txt` 62 个精确版本 + `requirements-dev.txt`） | `32ed023` |

详细完成记录（含反证与验证命令）都在 `docs/项目补充优化.md` 对应条目下。

---

## 7. 未完成的内容（19 项，其中 4 项是"暂不建议直接加入"）

```text
P1-4-1                补齐设计文档 17.2 要求的测试（缺「数据库写入失败」专项已由 P1-3-4 部分补上，
                      仍缺超长日志/大输入、工具结果非法等专项；过期 Token 链路已补强）  ← 下一项
P1-4-5                CI —— 产物已推送，但未在 GitHub 上确认运行结果（不要勾选）
P1-5-1 ~ P1-5-6       前端质量（多语句单行、类型统一、测试与可访问性、401 处理、历史抽屉、字段级校验）
P2-1 ~ P2-7           仅在有真实需求时做
```

> 注意：知识库下拉选择（第 8 节）**仍未做**，它不在 42 项清单里；若要做，先按规则在
> `docs/项目补充优化.md` 里新增并编号，再实施。
>
> P1-5-5（历史抽屉）现在的剩余范围已经变小：P1-3-1 已让抽屉用详情接口加载轨迹、
> P1-3-3 已接上"加载更多"与游标分页；剩下的主要是筛选交互、重跑与失败状态的细分展示。

### 关于执行顺序（本轮有偏离，已记录原因）

文档第八节的初始批次计划是 `A → B → C → D → E`，但实际把批次 D 的工程化项（P1-4-2/-4/-5）提前到了批次 C（P1-2、P1-3）之前——因为是提议后用户确认的调整，且这几项之间没有代码依赖。**代价是当时没同步文档，看起来像乱序。**

**后续约定（用户本轮要求）：不再跳项。** 顺序为：

```text
P1-2-4 → P1-3 全部 → P1-4-1 → 知识库下拉 UX（见第 8 节）→ P1-5 全部 → P2
```

若确实需要调整顺序，**必须先在 `docs/项目补充优化.md` 更新批次计划并写明原因，再动手**。

---

## 8. 本轮发现的真实问题：前端知识库 ID 硬编码（**已确认是用户测试失败的直接原因**）

### 现象

用户用 `E:\RagKnowledgeSystem\backend\scripts\seed_dev_data.py` 创建的账号测试，界面上一直失败，提示：

```text
知识库不存在或当前用户无权访问
```

### 根因（已用数据库查询确认，不是猜测）

```text
DevAtlas 数据库真实内容：
  users            : alice(1) zhangsan(2) lisi(3) s'da's(4) devatlas-demo(5)
  knowledge_bases  : 只有一条  kb_id=4  owner_id=5  "DevAtlas 开发演示知识库"
  documents        : kb_id=4 有 3 个文档
```

而 `seed_dev_data.py` 创建的账号是 **`devatlas-demo`**，它拥有的知识库 **ID 是 4（不是 1）**。前端 `web/src/views/IncidentWorkspaceView.vue` 把知识库 ID 的默认值写死为 `3`（表单默认 `1`），用户按默认填 `1` → Agent 调 DevAtlas `GET /api/v1/knowledge-bases/1` → DevAtlas 按 `id + owner_id` 双重过滤查不到 → 404 → Agent 原样返回该提示。

**这条链路完全按设计工作**：以前这个错误要等模型去检索才会暴露，现在**提交时立刻拦下**（P0-2-1 的效果）。也就是说，这次"失败"恰恰证明前置授权校验生效了。

### 为什么这是个需要修的真问题

知识库 ID 是**硬编码默认值**，一旦 DevAtlas 数据变化（换账号、重建库、清理数据），必然对不上，用户只能靠猜数字。而 DevAtlas 明明提供了 `GET /api/v1/knowledge-bases` 接口可列出当前用户的知识库。

### 建议的修法（未实施）

1. 给 Agent 增加一个代理端点（例如 `GET /api/v1/knowledge-bases`，用当前 token 转发到 DevAtlas），因为前端直连 DevAtlas 会踩 CORS。
2. 前端把"知识库 ID"文本框改成**下拉选择**，登录后自动加载；
3. 至少也要把默认值做成可配置，并把 DevAtlas 真实 ID 写进 `.env.example` 注释。

**注意**：这是一项**新增功能**，不在现有 42 项清单里。若决定做，应先把它作为一条新条目加进 `docs/项目补充优化.md` 并编号，再实施。

### 立即可用的临时办法

测试时把界面上的知识库 ID 手动改成 **`4`**；并且 **DevAtlas 后端（8000）必须处于运行状态**，否则提示会变成 502 而不是 404。

---

## 9. 本机环境与依赖（新会话可直接用）

```text
操作系统   : Windows（PowerShell 5.1；`**` 通配不递归，获取文件要用 Get-ChildItem -Recurse）
Python     : 3.13.2，`py` 启动
Node       : v22.19.0，npm 11.9.0
MySQL      : 本机 3306 可用；数据库 incident_agent；当前 alembic 版本 c78153d58823
DevAtlas   : E:\RagKnowledgeSystem（后端在 backend\，端口 8000）
端口       : DevAtlas 8000 / Agent 8001 / 前端 5174
```

### 关键依赖版本（见 `requirements-lock.txt`）

```text
openai 3.13.0        langchain-core 1.6.3     langchain-openai 1.6.2
langgraph 1.2.11     fastapi 0.141.1          SQLAlchemy 2.0.52
pydantic 2.13.5      alembic 1.20.0           httpx 0.28.1
pytest 9.1.1         ruff 0.16.5
```

⚠️ **注意**：这些版本比 `requirements.txt` 的下限新很多。因此本轮已把下限校准为 `langchain-core>=1.0`、`langchain-openai>=1.0`、`langgraph>=1.0`、`httpx>=0.28`、`openai>=3.0`——**旧下限（0.3/0.27）会把干净环境装成另一个大版本，直接跑不起来**。复现环境请用 `requirements-lock.txt`。

### 环境变量

`.env`（不提交）需要：`INCIDENT_DB_*`、`DEVATLAS_BASE_URL`、`DEEPSEEK_API_KEY`。其余可选，均有默认值：`INCIDENT_AGENT_MODEL`、`INCIDENT_AGENT_REPORT_MODEL`、`INCIDENT_AGENT_TEMPERATURE`、`INCIDENT_AGENT_MAX_TOKENS`、`INCIDENT_MODEL_TIMEOUT_SECONDS`（默认 30）、`INCIDENT_REQUEST_TIMEOUT_SECONDS`（默认 90）、`INCIDENT_MODEL_MAX_RETRIES`、`INCIDENT_LOG_LEVEL`、`INCIDENT_LOG_FORMAT`。完整模板见 `.env.example`。

### 测试不需要 MySQL

**全部 254 条测试使用 SQLite 内存库**，因此可离线运行，CI 里也不需要数据库服务。只有 `alembic check`（比对真实表结构与模型）需要本机 MySQL。

### ⚠️ 代理环境变量（新会话必读）

这台机器的环境里带着 `HTTP_PROXY`/`HTTPS_PROXY`（Clash，`127.0.0.1:7897`）以及 `NO_PROXY=localhost,127.0.0.1,::1,[::1]`。`[::1]` 这个写法会让 `httpx.Client` 在**构造阶段**就抛 `InvalidURL: Invalid port: ':1]'`，后果是：

- `py -m pytest tests -q` 有 23 条测试在任何断言前失败 → 已由 `tests/conftest.py` 在会话开始时清掉代理变量修好，现在应当是 **254 passed**；
- **真实启动服务后所有 DevAtlas 调用都会 500**（登录、知识库授权、检索）。要跑活体验证时，先用一个清过代理变量的包装脚本启动服务（本次用的是 `tmp/run_agent_clean.py`，`tmp/` 不提交）。

注意：在这个 shell 里直接 `$env:NO_PROXY=...` 对子进程无效（每层子进程都会被重新注入），必须由 Python 进程自己 pop 掉。

---

## 10. 尚未验证的事项（如实列出，不要当成已完成）

1. **真实模型返回与真实检索仍未跑通**：需要真实 DevAtlas（8000）+ 真实 DeepSeek Key + 登录态。已验证过的：应用真实启动（`Application startup complete`，lifespan 回收未报错）、真实 HTTP 打 `/health`、`/health/db`、`/openapi.json`、鉴权边界（401/502）、7 条输入校验（全部 422）、未知 run_id（404）、4 类错误响应不含堆栈/路径/密钥；以及用 `httpx.MockTransport` 打通真实客户端代码的 API 级测试。P1-3-1 另外做了一次更完整的活体验证：真实 DevAtlas（8000）+ 真实 Agent（8011）+ 真实 MySQL，`devatlas-demo` 真实登录拿 JWT 后调历史接口，列表 316 B / 详情 18,698 B、计数与直接查 MySQL 一致。但**分析链路（真实模型返回 + 真实检索）**仍未跑通。
2. **CI 在 GitHub 上的运行结果未确认**（API 限流）；因此 P1-4-5 保持未勾选。
3. **前端没有自动化测试**：只有 `vue-tsc` 类型检查 + `vite build` 通过，"界面上实际长什么样"没有自动验证手段。
4. **已知功能边界**（已记录在文档，不是漏项）：`138-0013-8000` 这类带分隔符的手机号不会被脱敏命中；`AgentStep.arguments_summary` 等的原始文本不入库（只存长度/计数，这是有意设计）。
5. **本机 `NO_PROXY` 会让 httpx 构造失败（已定位、已隔离，但没改应用代码）**：这台机器的环境变量里有 `NO_PROXY=localhost,127.0.0.1,::1,[::1]`，`httpx.Client` 会把 `[::1]` 拼成 `all://*[::1]` 模式并在构造阶段抛 `InvalidURL: Invalid port: ':1]'`。现象是 23 条测试在任何断言前失败，且**真实服务上任何一次 DevAtlas 调用都会返回 500**（已在真实启动的服务上复现 `exception_type: InvalidURL`）。处理方式：`tests/conftest.py` 在会话开始时清掉代理变量（测试与机器环境解耦）；跑真实服务时同样要先清掉这些变量再启动。**没有改应用代码**（`trust_env=True` 是 httpx 的正常行为，生产可能需要代理）。
6. **JSON 列的空值语义不一致（已记录，未修）**：`report` / `degraded_summary` 是 JSON 列，"没有报告"在不同写入路径下会落成 SQL `NULL` 或 JSON 字面量 `null`——真实 MySQL 8.0.41 上实测 `report IS NULL` 为 `0` 而 `JSON_TYPE(report)` 为 `'NULL'`。因此 P1-3-1 的摘要里**没有**加 `has_report` 这类 `IS NOT NULL` 推导的布尔字段。将来若要用 SQL 过滤"有报告"，需先统一写入语义（`none_as_null=True`）或改用 `JSON_TYPE`。
7. **历史列表的破坏性契约变更已同步前端，但前端仍无自动化回归**：`GET /api/v1/runs` 现在是 `{"items": [...], "next_cursor": ...}` 的分页信封（P1-3-3），条目里含 `title`/时间/`duration_ms`；前端已适配"列表 + 加载更多 + 点开拉详情"，但只经过 `vue-tsc` + `vite build` 与一次 Node 直跑时间工具的手工验证，没有组件测试。
8. **保留策略默认关闭**：`INCIDENT_RUN_RETENTION_DAYS=0`。启用后会删除超期记录（连带 steps），删除条数写启动日志；它**从未在真实环境的默认配置下运行过**，只在测试与一次"savepoint 内执行后回滚"的真实 MySQL 验证中跑过。

---

## 11. 给新会话的第一句话建议

> 读 `docs/项目交接文档-DeepSeek.md` 和 `docs/项目补充优化.md`，然后继续做 **P1-4-1 补齐设计文档要求的测试**。按约定：一次一项、实现+测试+推送齐了才打勾、不跳项、不用 `git add .`。

如果要先处理用户测试受阻的问题，则改为：

> 读交接文档第 8 节，先做"知识库下拉选择"这项新功能（需先在优化清单里新增并编号）。

---

## 12. 简历可用事实（本项目当前能真实写的内容）

已实现且可核查：LangGraph 条件路由与循环上限、统一 `ToolResult` 协议与错误码归一化、Pydantic 双层校验（工具入参 + 最终报告）、`owner_user_id` 级运行记录隔离、JWT 只在请求内转发不落库、MockRagGateway/FakeModel 确定性测试体系、跨 MySQL/DevAtlas 的边界错误归一化；此前几轮新增可写的还有：知识库归属强制预校验、敏感数据落库前脱敏、零证据语义、证据来源服务端溯源核验、确定性降级摘要、模型超时与请求预算治理、中断记录回收、结构化日志与步骤轨迹、不可信内容定界、报告容错与受限修复、全仓 lint 门禁与 CI、统一错误响应契约；P1-3 整组新增：**历史列表用一条聚合 SQL 消除 N+1 并改为摘要契约（实测列表体积由单条 18.7 KB 降到 316 B）、运行时间线与服务端派生耗时、基于 `(started_at, id)` 行值比较的游标分页（每页一条 SQL、并发新增下不重不漏）、状态与时间过滤、可配置且带审计日志的历史保留策略，以及权限/过期令牌/数据库失败分支的回归测试**。

**仍不能写成"已实现"**：SSE 流式分析、真实监控 provider、Redis、MCP、多 Agent、自动修复、高并发、真实准确率、生产上线规模。
