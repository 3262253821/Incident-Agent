# Incident Agent 交接文档（DeepSeek 会话）

> **用途**：上下文压缩、会话切换或换模型后的**第一恢复入口**。新会话读完本文即可接手，不需要回溯历史对话。
>
> **最后更新**：2026-09-15（P1-3 整组完成）
>
> **提交锚点**：本轮代码提交范围 `f5af0d7` … `d0d711f`（`d0d711f` = P1-3-4），其后只有文档提交。**当前 HEAD 请以 `git log --oneline -5` 为准**（本文档自身也是提交之一，写死哈希会立刻过时）。
>
> **项目根目录**：`E:\IncidentAgent`｜**关联项目**：`E:\RagKnowledgeSystem`（DevAtlas）
>
> 仓库里原有的 `docs/项目交接文档.md`（2026-09-04）是上一轮的版本，**已过期**；本文是当前有效版本。

---

## 1. 用户与求职背景（影响"该做什么"的判断）

- 淮安大学软件工程专业，**2027 年 6 月毕业**，目前无实习，正在秋招。
- 求职方向：**AI 应用开发 / LLM 应用开发 / Python 后端**。两个项目：DevAtlas（知识库基础设施）与 Incident Agent（本项目，Agent 编排层）。
- 现实约束：学校课程多、在校时间碎片化，因此要求"一项一项推进、每完成一项就测试并提交"。
- 简历纪律：只有**代码已实现并通过测试**的内容才能写进简历；不写虚构的准确率/吞吐量/用户量；清单里未勾选的一律不能写成"已实现"。

### 用户的硬性工作约束（与本文档同等重要）

1. **一次只做一项，做完等指示**（除非用户明确要求几项一起做）。
2. **不要 `git add .`**：改了什么就提交什么，commit message 说明做了什么。
3. **每完成一项就提交并推送**；出问题可回退。
4. **打勾规则**：`实现 + 测试通过 + 已推送` 三者齐了才允许把 `[ ]` 改成 `[x]`。
5. 不为简历堆砌技术（不引入 Redis/MCP/Docker/Kafka 等，除非有真实需求）。
6. `stages/` 是学习练习（保留、不作为正式模块导入）；用户个人材料（简历、复习笔记）不得提交。

---

## 2. 仓库、推送与隐私

```text
仓库地址（公开）: https://github.com/3262253821/Incident-Agent
GitHub 账号     : 3262253821
默认分支        : main
本机路径        : E:\IncidentAgent
提交作者信息    : Hello World <chuanjianzhu1014@outlook.com>
```

### 推送注意

- 国内直连 `github.com:443` 时通时断。已配置**只对 GitHub 生效**的代理：

  ```powershell
  git config --global "http.https://github.com.proxy" "http://127.0.0.1:7897"
  ```

  对应 Clash Verge 混合端口 `7897`。推送报 `Recv failure` / `Failed to connect port 443` 时**先确认梯子开着**再重试；提交在本地是安全的，不要慌着重来或改历史。
- 另外两项历史配置（保留无害）：`http.version=HTTP/1.1`、`http.postBuffer=157286400`。
- **GitHub Actions 的运行结果至今无法自动确认**：查询 `api.github.com` 一直被拒（403 / 匿名配额）。需要**人工**打开 <https://github.com/3262253821/Incident-Agent/actions> 查看。这直接卡着清单里的 P1-4-5。

### 隐私处理（已生效并验证过）

`.gitignore` 已挡住：`resume/`（含姓名/电话/邮箱）、`tmp/`、`docs/复习规划.md`、`docs/项目复习笔记整理.md`、`*.tsbuildinfo`、`.env.local`、`.env.*.local`。`.env` 从未被跟踪，仓库里只有 `.env.example`。

---

## 3. 当前进度快照

| 指标 | 最初 | 现在 |
| --- | --- | --- |
| 提交数 | 0 | **29 个提交**（`f5af0d7` … `d0d711f`，另有若干文档提交） |
| 测试用例 | 18 passed | **304 passed, 0 warnings** |
| 测试文件 | 4 个（用户原有） | **24 个**（另有 `tests/conftest.py` 做代理变量隔离） |
| ruff（全仓） | 193 个错误 | **0** |
| 弃用/SQLAlchemy 警告 | 131 条 | **0** |
| 数据库迁移 | 1 个 | 3 个（新增 `370ee3c8987d` 中断标记列、`c78153d58823` 降级摘要列） |
| 清单完成度 | — | **已勾 28 项（含审计基线）/ 未勾 19 项** |

**唯一的任务源是 `docs/项目补充优化.md`**（勾选表 + 完成记录 + 执行顺序记录）。本文只做导航与背景。

---

## 4. 已完成内容一览（28 项，每项都满足"实现 + 测试 + 推送"）

| 项目 | 一句话说明 | 提交 |
| --- | --- | --- |
| 审计基线 | 建立可复现的验证基线与运行时探针证据 | — |
| P0-1-1 / -2 / -3 | `top_k` 全链路生效；工具不再把 `knowledge_base_id` 暴露给模型；清理死配置与死字段 | `f5af0d7` |
| P0-2-1 | 分析入口强制校验知识库归属，失败不产生任何运行记录 | `f698820` |
| P0-2-2 | 输入与工具结果在进模型前、落库前脱敏 | `9fbe409` |
| P0-3-1 | 零工具证据不再伪装成 `completed`，返回 `insufficient_evidence` + `confidence=low` | `2029157` |
| P0-3-2 | 服务端核验报告 evidence 来源，无法追溯的引用被剔除并回填真实 metadata | `8a780cf` |
| P0-3-3 / -3b | 失败时生成确定性降级摘要；补修入库，历史与当次响应一致 | `da17d52` / `e8941d2` |
| P0-4-1 / -2 / -3 | 模型超时与请求预算；启动回收中断的 `running` 记录；`append_steps` 幂等整体替换 | `6b5f0e5` |
| P1-1-1 / -2 / -4 | 结构化 JSON 日志（按 `run_id` 串联、字段级脱敏）；步骤 `duration_ms` 与摘要；`analyze_log` 命中片段与行号 | `40767df` |
| P1-1-3 | 不可信内容定界（`<untrusted-*>`）+ 注入形状中和 | `ec8d46b` |
| P1-2-1 / -2 / -3 | 报告 JSON 容错 + 一次修复重试；模型配置集中化；`datetime.now(UTC)`（警告 131 → 0） | `f2c788d` |
| P1-2-4 | 统一异常处理器：错误响应统一 `detail`/`error_code`/`request_id`；鉴权代理不再把上游 422/429/5xx/超时折叠成 502 | `5d6a0eb` |
| P1-3-1 | 历史列表改为**一条 SQL** 的 `RunSummary` 摘要契约（步骤子查询计数、observations 用方言 JSON 长度函数就地计数），详情用 `selectinload` 返回完整轨迹 | `abd15e5` |
| P1-3-2 | 两个接口都返回 `title`/`started_at`/`completed_at` 与派生 `duration_ms`（未结束或被回收的中断运行为 `null`）；前端展示相对时间与耗时 | `efebf8c` |
| P1-3-3 | 游标分页（`(started_at, id)` 行值比较，每页一条 SQL，并发新增下不重不漏）+ 状态/时间过滤 + 可配置保留策略（默认关闭，删除带审计日志） | `19e3e12` |
| P1-3-4 | 权限与失败分支回归测试：越权与不存在 ID 响应不可区分、过期令牌三入口 401 且零副作用、数据库写失败安全 500 并可回收、失败状态确实落库 | `d0d711f` |
| P1-4-2 | 全仓 ruff 清零并把 CI 门禁扩到全仓 | `0f67b91` |
| P1-4-3 | `.gitignore` 补齐（隐私与临时文件） | `062ee69` |
| P1-4-4 | 锁定依赖（`requirements-lock.txt` 62 个精确版本 + `requirements-dev.txt`） | `32ed023` |

详细完成记录（改了什么文件、怎么验证、反证结果、是否影响迁移/API/前端、简历可用事实）都在 `docs/项目补充优化.md` 对应条目下。

---

## 5. 还差什么

### 5.1 清单内未完成（19 项）

| 分组 | 条目 | 现状与说明 |
| --- | --- | --- |
| 测试与工程化 | **P1-4-1 补齐设计文档要求的测试** | 性质是"对账 + 补缺口"：owner 隔离 / 失败持久化 / 越权 KB / 脱敏都已有测试，缺的是**超长日志与大输入、工具结果非法形状、纯 timeout** 等专项，以及"每条测试标注设计文档章节"这件记账 |
| | **P1-4-5 增加 CI** | workflow 已写好并推送到 `origin/main`，本地按 CI 的确切方式每一步都验证过，但**从未在 GitHub 上确认过一次真实运行结果**，按规则不能勾 |
| 前端质量（6 项） | P1-5-1 拆分多语句单行代码 | `web/src/styles.css` 与部分 Vue 仍是压行写法 |
| | P1-5-2 前后端类型统一 | 真实漂移仍在：`web/src/types/api.ts` 的 `AgentStep` 缺 `duration_ms`/`arguments_summary`/`result_summary`/`tool_call_id`，还留着已废弃的 `ok` |
| | P1-5-3 前端测试与可访问性 | 无 Vitest/组件测试；历史抽屉无 `role=dialog`/ESC/焦点管理；加载态无 `aria-live`；无 `prefers-reduced-motion`；焦点环被去掉 |
| | P1-5-4 统一 401 处理 | 无响应拦截器，仍靠"错误文案里包含 401"判断退出；网络抖动会误清 Token |
| | P1-5-5 历史抽屉使用详情接口 | **已被 P1-3-1 / P1-3-3 部分完成**（点开拉详情、"加载更多"已通）；剩下筛选交互、重跑、失败状态细分展示 |
| | P1-5-6 前置校验与字段级提示 | KB ID 为空会变 `NaN`；422 数组错误没按 `loc` 映射到字段；不同失败都显示 DEGRADED |
| 产品增强（7 项） | P2-1 SSE 流式分析 / P2-2 部分成功继续报告 / P2-3 固定评测集与回归基线 / P2-4 Token 与成本观测 / P2-5 真实服务状态 provider / P2-6 前端 Playwright E2E / P2-7 Docker 部署复现 | 都未开始做。注意 P2-4 里"耗时"部分已由 P1-3-2 完成，剩 token usage 与成本 |
| 明确不做（4 项） | Redis 缓存、MCP/多 Agent/自动修复、Kafka/K8s/微服务拆分、Reranker/LLM-as-judge | 没有真实需求前不动 |

### 5.2 清单外但仍然欠着的（按"影响用户"排序）

1. **知识库下拉选择（本文第 8 节）—— 仍未做，而它是用户当初测试失败的直接原因。** 前端 `web/src/views/IncidentWorkspaceView.vue` 里仍是 `knowledgeBaseId = ref(3)`，而 `devatlas-demo` 真实知识库 ID 是 **4**；不修的话每次自测都要手填 4。它**不在 42 项清单里**，要做需先在 `docs/项目补充优化.md` 新增并编号。
2. **真实端到端从未跑通**：已做过的活体验证覆盖真实 MySQL、真实 DevAtlas 鉴权、真实 HTTP、真实过期 JWT、真实 MySQL 删除（savepoint 回滚），但**分析与检索本身是打桩的**——真实 DeepSeek 模型返回 + 真实 `/search` 检索这条链路一次都没跑过。
3. **GitHub Actions 结果未确认**（API 403），需要人工打开 actions 页面；这条卡着 P1-4-5。
4. **前端零自动化测试**：目前只有 `vue-tsc` + `vite build`，外加用 Node 直跑时间工具的手工验证（见 7.4）；界面实际长什么样没有自动手段。
5. **两笔已知未修的小债**：① `report`/`degraded_summary` 是 JSON 列，"没有报告"可能落成 SQL `NULL` 或 JSON 字面量 `null`（真实 MySQL 8.0.41 上实测 `report IS NULL` 为 0 而 `JSON_TYPE(report)` 为 `'NULL'`），将来用 SQL 过滤"有报告"会踩；② 保留策略默认 `INCIDENT_RUN_RETENTION_DAYS=0`（关闭），**从未在真实默认配置下开启运行过**，只在测试与一次"savepoint 内执行后回滚"的真实 MySQL 验证里跑过。

### 5.3 建议的下一步顺序（三选一，等用户定）

- **A（最实用）**：先做"知识库下拉选择"——先在清单新增并编号，后端加代理端点（前端直连 DevAtlas 会踩 CORS）+ 前端改成登录后自动加载的下拉。
- **B（按清单顺序）**：P1-4-1 → P1-4-5（顺便人工确认 CI 是否绿）。
- **C（前端整组）**：P1-5-1 ~ P1-5-6，一次收掉类型漂移、可访问性、401 处理与字段级提示。

DeepSeek 的建议是 **A → B → C**：A 解决用户实际使用受阻，B 把测试与 CI 这块账结清（后面做 P2 才有基线），C 是成组的前端质量活。**但要遵守"一次一项、做完等指示"。**

---

## 6. 新会话照这个走的流程

```text
1. 读 docs/项目交接文档-DeepSeek.md（本文）和 docs/项目补充优化.md，
   找到第一个未勾选且优先级最高的条目（当前应是 P1-4-1，或用户指定的"知识库下拉"）

2. 读该条目下面列出的「涉及文件」，先读代码再动手，不要凭记忆假设接口
   —— 涉及 DevAtlas 接口时必须读 E:\RagKnowledgeSystem\backend 的真实代码

3. 实现改动，然后按顺序验证：
     py -m pytest tests -q            # 必须全绿（当前基线 304 passed）
     py -m ruff check .               # 全仓必须 0（CI 也跑这条）
     py -m compileall -q app migrations tests
     py -m alembic check              # 只在动了 models/ 时才需要（需本机 MySQL）
     cd web; npm run build            # 只在动了前端时才需要

4. 做「反证」：把修复临时回退成旧行为，确认相关测试确实会失败，再恢复
   —— 这是本项目每项完成记录里都有的固定动作，也是能写进简历的证据
   —— 实操：先 Copy-Item 备份到 tmp/，改坏，跑测试看失败，再 Copy-Item 恢复

5. 更新 docs/项目补充优化.md：打勾 + 写完成记录（改了什么文件、怎么验证、
   反证结果、测试结果、是否影响迁移/API/前端、简历可用事实）

6. 提交（逐文件 git add，不用 git add .），message 说明做了什么并附验证结果
   —— 较长/含中文的 message 写到 tmp/msg.txt 再 git commit -F tmp/msg.txt

7. 推送；若失败先查梯子，再重试；推送后核对 local == origin
   —— 之后再补一个"docs: record the <编号> commit hash"的小提交（本项目的惯例）
```

### 一条反复验证过的经验

**写测试 ≠ 功能完整。** 本项目已经出现两次"测试全绿但功能有缺口"：降级摘要只存在响应里没入库、列表接口 N+1 与体积膨胀。两者都是**把服务真启动起来、打真实 HTTP、看真实序列化输出/真实 SQL** 才发现的。因此对"当次响应 / 历史回查""真实方言行为"这类问题，务必做一次活体验证（方法见第 8 节）。

---

## 7. 本机环境与启动方式

```text
操作系统   : Windows（PowerShell 5.1；`**` 通配不递归，取文件要用 Get-ChildItem -Recurse）
Python     : 3.13.2，用 `py` 启动
Node       : v22.19.0，npm 11.9.0
MySQL      : 本机 3306 可用；数据库 incident_agent；alembic 版本 c78153d58823
DevAtlas   : E:\RagKnowledgeSystem（后端在 backend\，端口 8000）
端口       : DevAtlas 8000 / Agent 8001 / 前端 5174（活体验证时常用 8011，避免和用户的服务打架）
```

### 7.1 启动命令

```powershell
# DevAtlas 后端（活体验证需要它，启动约 40-60 秒，会加载 embedding 模型）
cd E:\RagKnowledgeSystem\backend; py -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Agent（注意代理变量，见 7.2）
cd E:\IncidentAgent; $env:PYTHONPATH="E:\IncidentAgent"; py tmp\run_agent_clean.py

# 前端
cd E:\IncidentAgent\web; npm run dev -- --host 127.0.0.1 --port 5174
```

### 7.2 ⚠️ 代理环境变量（新会话必读）

这台机器的环境里有 `HTTP_PROXY`/`HTTPS_PROXY`（Clash，`127.0.0.1:7897`）以及

```text
NO_PROXY=localhost,127.0.0.1,::1,[::1]
```

`[::1]` 这个写法会让 `httpx.Client` 在**构造阶段**就抛 `InvalidURL: Invalid port: ':1]'`（httpx 把它拼成 `all://*[::1]` 模式）。后果与处理：

- **pytest**：会让 23 条测试在任何断言之前失败 → 已由 `tests/conftest.py` 在会话开始时清掉代理变量修好，现在应当是 **304 passed**；
- **真实服务**：所有 DevAtlas 调用（登录、知识库授权、检索）都会 500（已复现 `exception_type: InvalidURL`）→ 用 `tmp/run_agent_clean.py` 启动（它在 Python 里 pop 掉代理变量再 `uvicorn.run`）；
- **注意**：在这个 shell 里 `$env:NO_PROXY=...` 对子进程**无效**（每层子进程都会被重新注入），必须由 Python 进程自己 pop。

### 7.3 依赖与环境复现

- `requirements-lock.txt`（62 个精确版本）+ `requirements-dev.txt`（pytest、ruff）是复现环境的正确入口；`requirements.txt` 是**经实测校准的下限**（`openai>=3.0`、`langchain-core>=1.0`、`langchain-openai>=1.0`、`langgraph>=1.0`、`httpx>=0.28`），旧下限（0.3/0.27）会把干净环境装成另一个大版本。
- 本机关键的实测版本：openai 3.13.0、langchain-core 1.6.3、langchain-openai 1.6.2、langgraph 1.2.11、fastapi 0.141.1、SQLAlchemy 2.0.52、pydantic 2.13.5、alembic 1.20.0、httpx 0.28.1、pytest 9.1.1、ruff 0.16.5。
- `.env`（不提交）需要：`INCIDENT_DB_*`、`DEVATLAS_BASE_URL`、`DEEPSEEK_API_KEY`。可选变量与默认值见 `.env.example`（含 `INCIDENT_RUN_RETENTION_DAYS=0`）。
- **测试不需要 MySQL**：全部 304 条测试使用 SQLite 内存库，可离线运行；只有 `alembic check` 需要本机 MySQL。

### 7.4 前端工具函数的真实验证方式（前端还没有测试框架）

Node 22 支持类型擦除，可以直接执行 TS 工具函数：

```powershell
cd E:\IncidentAgent; node --experimental-strip-types tmp\check_time_helpers.ts
```

（`tmp/check_time_helpers.ts` 已验证 `web/src/utils/time.ts` 的 14 条用例。P1-5-3 引入 Vitest 后应改为正式测试。）

---

## 8. 活体验证的正确做法（本项目最有价值的验证手段）

`tmp/` 下已有可复用的探针脚本（`tmp/` 不提交，新会话可直接改）：

| 脚本 | 用途 |
| --- | --- |
| `tmp/run_agent_clean.py` | 清掉代理变量后启动真实 Agent（8011） |
| `tmp/live_http_history.py` | 真实登录 + 打历史接口，量 payload 体积 |
| `tmp/live_p133_mysql.py` | 直接对真实 MySQL 跑存储层查询；保留策略用 savepoint 包住后回滚 |
| `tmp/live_p133_http.py` | 真实 HTTP 分页/过滤/错误形状 |
| `tmp/live_p134_expired_token.py` | 真实过期 JWT 链路 |
| `tmp/measure_n_plus_one.py` | 用 SQLAlchemy 事件统计语句数（N+1 证据） |
| `tmp/backup_agent_runs_before_p042.sql`、`tmp/backup_before_degraded_summary.sql` | 改数据前留的 MySQL 备份（当时的安全网） |

> `tmp/` 里还有一堆 `*_backup.py` 是各次反证前的文件备份，以及 `commit_msg_*.txt` 是提交信息草稿——都可以随时删，不影响任何东西。

要点：

1. **DevAtlas 必须先启动**（8000），否则登录会 502/503；
2. DevAtlas 演示账号（`backend/scripts/seed_dev_data.py` 的默认值）：用户名 `devatlas-demo`、密码 `DevAtlas123!`，它的**知识库 ID 是 4**；
3. 需要"另一个用户的历史数据"时，可以用 DevAtlas 自己的 `JWT_SECRET_KEY`（在 `E:\RagKnowledgeSystem\.env`）签一个 HS256 令牌，claims 是 `{"sub": "<user_id>", "iat", "exp"}`——这是验证工具，不是产品改动；
4. **绝不要为了让验证通过而改用户数据**：批量 DELETE 之类操作用 `Session(bind=connection, join_transaction_mode="create_savepoint")` 包起来，验证完 `outer.rollback()`（已在真实 MySQL 上实践过）；
5. 用完**把服务杀掉**、核对端口不再监听；
6. 真实 HTTP 请求用 `httpx.Client(trust_env=False)`，避免再踩代理变量。

### 当前 MySQL 里的真实数据（写本文时）

```text
DevAtlas users: alice(1) zhangsan(2) lisi(3) s'da's(4) devatlas-demo(5)
DevAtlas knowledge_bases: 只有 kb_id=4（owner_id=5，DevAtlas 开发演示知识库）
incident_agent.agent_runs: owner 1 有 4 条，owner 5 有 1 条（合计 5 条运行、30 条步骤）
```

---

## 9. 已知坑与踩过的教训（新会话可直接复用）

1. **路由层自己构造并注入 authorizer**：patch `services.incident.HttpKnowledgeBaseAuthorizer` 对 API 路径**无效**，必须 patch `routers.incidents.HttpKnowledgeBaseAuthorizer`。另外路由的 `finally` 会关闭它构造的授权器，替换品必须提供 `close()`，否则看到的是与业务无关的 `AttributeError`。（P1-3-4 记录里）
2. **报告模型要显式 patch**：P1-2-2 把模型配置拆成 `create_chat_model` / `create_report_model` 之后，测试若只 patch 前者，报告节点会真的去调 DeepSeek API。已有多个测试文件用 `incident_module.create_report_model` patch。
3. **`append_steps` 的 identity map 冲突**：删除后重插时，调用方此前读过的 `run.steps` 会留在 identity map 里，SQLite 复用自增主键就触发 `SAWarning`。修法是删除前 `db.expire(run, ["steps"])`。
4. **MySQL 的 JSON 列不会存 SQL NULL**：Python `None` 可能落成 JSON 字面量 `null`（`JSON.none_as_null` 默认 False），所以 `report IS NOT NULL` 对"没有报告"也可能为真。要判定请用 `JSON_TYPE()`，或先统一写入语义。
5. **SQLite 默认不开外键级联**：删主表不会带走子表，批量删除必须显式先删 `agent_steps`。
6. **MySQL 不允许 `FOR UPDATE` + `LIMIT` 组合**，也不允许在删除某表的子查询里再读同一张表（先把主键取出来再删）。
7. **Starlette 的 `HTTP_422_UNPROCESSABLE_ENTITY` 已弃用**，直接写数字 `422` 最省事（不同版本替代常量名不一致）。
8. **前端 axios 数组参数**默认序列化成 `status[]=a`，FastAPI 的 `Query(list[str])` 只认重复键；已在 `web/src/api/runs.ts` 用 `paramsSerializer: { indexes: null }` 处理。
9. **文档里的命令输出会乱码**：在 PowerShell 里 `Get-Content` 读 UTF-8 会中文乱码，用文件工具（read）读；测试日志里的中文乱码同理，不影响断言。

---

## 10. 尚未验证 / 已知功能边界（如实列出，不要当成已完成）

1. **真实模型返回与真实检索未跑通**（见 5.2 第 2 条）：已验证的是真实 DB、真实鉴权、真实 HTTP、真实过期令牌；**分析链路仍靠 FakeModel/MockRagGateway**。
2. **CI 在 GitHub 上的运行结果未确认**（API 403），P1-4-5 保持未勾。
3. **前端没有自动化测试**：只有 `vue-tsc` + `vite build` 与一次 Node 直跑时间工具。
4. **保留策略从未在真实默认配置下开启运行过**（默认关闭）。
5. **已知功能边界**（有意设计，不是漏项）：`138-0013-8000` 这类带分隔符的手机号不会被脱敏命中；`AgentStep.arguments_summary` 等的原始文本不入库（只存长度/计数）；历史列表不返回 `total`（用游标判断是否还有下一页）。

---

## 11. 简历可用事实

**可以写**：LangGraph 条件路由与循环上限、统一 `ToolResult` 协议与错误码归一化、Pydantic 双层校验（工具入参 + 最终报告）、`owner_user_id` 级运行记录隔离、JWT 只在请求内转发不落库、MockRagGateway/FakeModel 确定性测试体系、跨 MySQL/DevAtlas 的边界错误归一化、知识库归属强制预校验、敏感数据落库前脱敏、零证据语义、证据来源服务端溯源核验、确定性降级摘要、模型超时与请求预算治理、中断记录回收、结构化日志与步骤轨迹、不可信内容定界、报告容错与受限修复、全仓 lint 门禁与 CI、统一错误响应契约（`request_id` 关联响应与日志）。

P1-3 整组新增可写：

- 历史列表用一条聚合 SQL 消除 N+1 并改为摘要契约（实测列表体积由单条 18.7 KB 降到 316 B，查询数与 run 条数无关）；
- 运行时间线与服务端派生耗时（对未结束与被中断的运行明确返回空值，避免把进程宕机时长当成分析耗时）；
- 基于 `(started_at, id)` 行值比较的游标分页（每页一条 SQL、不需要 COUNT 总数查询、并发新增下不重不漏）+ 状态/时间过滤 + 可配置且带审计日志的历史保留策略；
- 权限与失败分支回归测试：越权查询与不存在 ID 的响应不可区分（避免存在性泄露）、过期令牌在三个入口一致 401 且零副作用、数据库写失败返回不含内部细节的安全错误并依赖启动回收机制收尾。

**仍不能写成"已实现"**：SSE 流式分析、真实监控 provider、Redis、MCP、多 Agent、自动修复、高并发、真实准确率、生产上线规模。

---

## 12. 给新会话的第一句话建议

> 读 `docs/项目交接文档-DeepSeek.md` 和 `docs/项目补充优化.md`，然后继续做 **P1-4-1 补齐设计文档要求的测试**。按约定：一次一项、实现+测试+推送齐了才打勾、不跳项、不用 `git add .`，每项都要做反证并写完成记录。

如果用户先要解决"自己测试受阻"，则改为：

> 读交接文档第 8 节与 5.2 第 1 条，先做"知识库下拉选择"这项新功能（需先在 `docs/项目补充优化.md` 里新增并编号，后端加一个代理端点以避免前端直连 DevAtlas 的 CORS 问题）。
