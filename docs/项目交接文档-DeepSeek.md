# Incident Agent 交接文档（DeepSeek 会话）

> **用途**：上下文压缩、会话切换或换模型后的**第一恢复入口**。新会话读完本文即可接手，不需要回溯历史对话。
>
> **最后更新**：2026-09-15（**P1-5-4 完成：统一 401 处理并区分网络故障**）。当前进度：**P1-5-4 已完成**（响应拦截器按 HTTP 状态码 + 统一错误契约的 `error_code` 清会话并带 `redirect` 跳登录页；后端不可达/超时/上游 5xx 只提示、保留 Token；前端测试 50 → **97 条**），此前 P1-5-3、P1-5-2、P1-5-1、P1-3 整组、P1-6-1、P1-4-1、P1-4-5 均已完成。**下一步 = P1-5-5**（历史抽屉筛选/重跑/失败状态细分）。准确数字请跑 §12.1 的三条命令。
>
> **提交锚点**：代码提交从 `f5af0d7` 一路到 **`b0400fe`**（P1-5-3），P1-5-4 的代码提交紧随其后（哈希见 `docs/项目补充优化.md` 的完成记录）；**准确 HEAD 请直接跑 `git log --oneline -5`（工作区应当是干净的）**，写死哈希会立刻过时。每一项的提交号都写在 `docs/项目补充优化.md` 的完成记录与 3.3 节里。
>
> **文档地图（新会话先看这张表）**：
>
> | 文档 | 作用 |
> | --- | --- |
> | `docs/项目交接文档-DeepSeek.md`（本文） | 恢复入口：背景、进度、环境、活体验证做法、已知坑、下一步。**只做导航，不写完成记录** |
> | `docs/项目补充优化.md` | **唯一的任务来源**：勾选表 + 完成记录 + 执行顺序；当前状态在第二节（2.1 看板 / 2.2 未完成项 / 2.3 勾选审计） |
> | `docs/测试对照-设计文档章节.md` | 测试 ↔ `docs/agent-mvp设计.md` 章节对照（含"测不了"的边界） |
> | `docs/agent-mvp设计.md` | 设计文档（§17 测试设计、§16 安全策略等，是所有测试的验收依据） |
>
> **下一步要做什么**：用户已定顺序 A → B → C，A、B 都已完成推送，C 的 **P1-5-1（`39f1fe2`）、P1-5-2（`730268d`）、P1-5-3（`b0400fe`）与 P1-5-4（响应拦截器统一 401，见 `docs/项目补充优化.md` 第五节）也已完成**；**当前 = C 的第五步 P1-5-5（历史抽屉使用详情接口：剩筛选交互、重跑一条历史、失败状态细分展示）**，之后 P1-5-6（422 `loc` 映射到字段）。未完成项与各自的缺口见 `docs/项目补充优化.md` 2.2 节。
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

**接手事实（本版核对于 2026-09-15 的 P1-5-4 提交）**：工作区干净、`local == origin`｜后端基线 **381 passed**、前端 **97 passed（11 个 `.spec.ts`）**｜清单 **已勾 35 / 未勾 13**｜**下一步 = P1-5-5**。提交数与 HEAD 会随文档提交变动，**新会话先跑 §12.1 的三条命令复核这些数字**。

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
- **GitHub Actions 的运行结果现在可以自己读**：**不要走开发机代理**去查 `api.github.com`（`HTTPS_PROXY` 指向 Clash，共享出口 IP 的匿名配额早已用尽 → 403）。用 `httpx.Client(trust_env=False)` 直连即可读到 run / job / step 的真实结论（探针 `tmp/gh_runs.py`）。另有两个更省事的信号：`https://github.com/3262253821/Incident-Agent/actions/workflows/ci.yml/badge.svg`（CDN 缓存约 5 分钟）与 `https://img.shields.io/github/actions/workflow/status/3262253821/Incident-Agent/ci.yml?branch=main`。**watch out**：workflow 文件解析失败时 GitHub 会造出一个 **0 job 的失败运行**，工作流名退化成 `.github/workflows/ci.yml`——看到这个形态先怀疑 YAML，而不是测试。

### 隐私处理（已生效并验证过）

`.gitignore` 已挡住：`resume/`（含姓名/电话/邮箱）、`tmp/`、`docs/复习规划.md`、`docs/项目复习笔记整理.md`、`*.tsbuildinfo`、`.env.local`、`.env.*.local`。`.env` 从未被跟踪，仓库里只有 `.env.example`。

---

## 3. 当前进度快照

| 指标 | 最初 | 现在 |
| --- | --- | --- |
| 提交数 | 0 | **随每轮往里走**（准确值以 `git rev-list --count HEAD` 为准） |
| 测试用例 | 18 passed | 后端 **381 passed, 0 warnings**；前端 **97 passed**（P1-5-3 建框架 50 条，P1-5-4 加到 97 条，vitest + jsdom） |
| 测试文件 | 4 个（用户原有） | 后端 **31 个**（另有 `tests/conftest.py` 做代理变量隔离）；前端 **11 个 `.spec.ts`**（`web/tests/`） |
| ruff（全仓） | 193 个错误 | **0** |
| 弃用/SQLAlchemy 警告 | 131 条 | **0** |
| 数据库迁移 | 1 个 | 3 个（新增 `370ee3c8987d` 中断标记列、`c78153d58823` 降级摘要列） |
| CI | 无 | **绿**（P1-5-4 的 run 见 `docs/项目补充优化.md`；前端 job 已含"运行单测"一步） |
| 清单完成度 | — | **已勾 35 项（含审计基线）/ 未勾 13 项** |

**唯一的任务源是 `docs/项目补充优化.md`**（勾选表 + 完成记录 + 执行顺序记录）。本文只做导航与背景。

---

## 4. 已完成内容一览（35 项，每项都满足"实现 + 测试 + 推送"）

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
| P1-6-1 | 知识库由手填 ID 改为**登录后自动加载的下拉**；新增 Agent 只读代理端点 `GET /api/v1/knowledge-bases`（Token 原样转发、响应只下发 `id`/`name`/`description`、上游 401/404/5xx/超时归一化）；提交前字段级校验（空值不再变 `NaN`）。**清单外新增项**（已在 `docs/项目补充优化.md` 补编号） | `cdbd7db` |
| P1-4-1 | 补齐设计文档要求的测试：新增 3 个测试文件 45 条（输入边界、统一工具结果协议、§17.2 案例 2/3/5/6/7/9 + 大输入）；修掉"**纯空白标题/内容能进模型**"的真实缺口（`str_strip_whitespace`）；25 个既有测试文件补 `设计文档章节：…`，新增 `docs/测试对照-设计文档章节.md` 做十条案例逐条对照 | `9d29fc9` |
| P1-4-5 | 让 CI **真的变绿**：第一次读真实运行结果就发现它一直是红的。修掉 ① 无 `.env` 时 20 个测试文件在收集阶段即失败（backend job 显式提供 `INCIDENT_DATABASE_URL`）；② 两条用例静默依赖开发机真实 MySQL（`test_error_handling` 补 `get_db` 覆盖、`test_model_config` 显式设 URL）；③ 自己引入的 YAML 引号缺陷（表现为 0 job 的失败运行）。新增 `tests/test_ci_workflow.py`（P1-5-3 又加 1 条变 7 条）守住 workflow 定义。run `34930276951` 两个 job 全绿 | `470817e`、`8eea1fb` |
| P1-5-1 | 前端 7 个压行文件展开为常规排版（`styles.css` 59 → 1052 行，另有 6 个 Vue 组件）+ 排版守门测试；用编译产物证明零行为差异（生产构建产物与改动前逐字节相同） | `39f1fe2` |
| P1-5-2 | 前后端类型统一：先修根因——`POST /analyze` 与 `GET /runs/{id}` 改用同一份步骤投影（此前 5 条步骤在两个接口上有 4 种形状、泄漏 `_started_at`/`ok`/`attempts` 等内部字段、且缺 `step_index`）；再按真实契约重写 `web/src/types/api.ts`，并用 OpenAPI schema + 真实载荷双向比对 17 个 TS 接口接入 CI | `730268d` |
| P1-5-3 | 前端测试与可访问性：引入 Vitest + `@vue/test-utils` + jsdom（50 条 / 6 个文件，`npm run test` 进 CI），把此前只有 `tmp/` 手跑脚本的时间工具纳入回归；补 `role=dialog`+ESC+焦点陷阱与焦点归还、`aria-live` 播报、`role=alert`/`aria-busy`、`:focus-visible`、`prefers-reduced-motion`；顺带修掉"ESC 监听器装在 `await` 之后导致抽屉刚打开关不掉"的真实缺陷 | `b0400fe` |
| P1-5-4 | 统一 401 处理并区分网络故障：`web/src/api/client.ts` 加响应拦截器，判据从"错误文案 `includes('401')`"改为 **HTTP 状态码 + 后端统一契约的 `error_code`**（修掉了"文案变成中文 detail 后永远不会登出"的静默失效）；`restore()` 区分"401/403 清会话"与"连不上/超时/上游 5xx 只提示、保留 Token"；跳登录页时带上 `redirect`（并用 `safeRedirect` 挡住开放重定向）；前端测试 50 → **97 条**（含真实 axios 实例与真实 store 的链路测试） | 见 `docs/项目补充优化.md` |

详细完成记录（改了什么文件、怎么验证、反证结果、是否影响迁移/API/前端、简历可用事实）都在 `docs/项目补充优化.md` 对应条目下。

---

## 5. 还差什么

### 5.1 清单内未完成（13 项）

| 分组 | 条目 | 现状与说明 |
| --- | --- | --- |
| 测试与工程化 | ~~P1-4-1 补齐设计文档要求的测试~~ / ~~P1-4-5 增加 CI~~ | **都已完成**（见第 4 节）：P1-4-1 补 45 条测试 + 章节记账；P1-4-5 CI 变绿并已读真实运行结果。测试与工程化这一组已清空 |
| 前端质量（2 项） | ~~P1-5-1 拆分多语句单行代码~~ | **已完成**（`39f1fe2`）：核对后发现实际有 **7 个**文件压行（审计只点了 2 个），已全部展开并加排版守门测试 |
| | ~~P1-5-2 前后端类型统一~~ | **已完成**（`730268d`）：核对后发现问题比清单写的更严重——两个接口的步骤形状不同（analyze 5 条步骤 4 种形状、泄漏内部字段、缺 `step_index`），已统一为一份投影；17 个手写 TS 类型进入 CI 双向比对 |
| | ~~P1-5-3 前端测试与可访问性~~ | **已完成**（`b0400fe`）：核对后确认审计原文的 5 处"0 处"全部属实；已引入 Vitest（50 条进 CI）并补 `role=dialog`/ESC/焦点管理、`aria-live`、`:focus-visible`、`prefers-reduced-motion` |
| | ~~P1-5-4 统一 401 处理~~ | **已完成**（2026-09-15，提交见 `docs/项目补充优化.md`）：判据由"错误文案 `includes('401')`"改为 HTTP 状态码 + `error_code`（原判据在真实响应上永不命中），后端不可达/超时/上游 5xx 只提示不登出，跳登录页带 `redirect`。前端测试 50 → 97 条 |
| | P1-5-5 历史抽屉使用详情接口 | **已被 P1-3-1 / P1-3-3 部分完成**（点开拉详情、"加载更多"已通）；剩下筛选交互、重跑、失败状态细分展示 |
| | P1-5-6 前置校验与字段级提示 | **P1-6-1 已完成"知识库为空在提交前拦下"这一半**；剩下 422 数组错误按 `loc` 映射到字段、不同失败状态的细分展示 |
| 产品增强（7 项） | P2-1 SSE 流式分析 / P2-2 部分成功继续报告 / P2-3 固定评测集与回归基线 / P2-4 Token 与成本观测 / P2-5 真实服务状态 provider / P2-6 前端 Playwright E2E / P2-7 Docker 部署复现 | 都未开始做。注意 P2-4 里"耗时"部分已由 P1-3-2 完成，剩 token usage 与成本 |
| 明确不做（4 项） | Redis 缓存、MCP/多 Agent/自动修复、Kafka/K8s/微服务拆分、Reranker/LLM-as-judge | 没有真实需求前不动 |

### 5.2 清单外但仍然欠着的（按"影响用户"排序）

1. **~~知识库下拉选择~~ → 已完成，编号 P1-6-1（见第 4 节与 `docs/项目补充优化.md` 第 3.3 节）。** 前端不再写死 `knowledgeBaseId = ref(3)`：登录后 `GET /api/v1/knowledge-bases` 自动加载可选知识库并默认选中第一项（`devatlas-demo` 只有 ID **4** 那一个库，实测返回 `[{"id":4,...}]`）。
2. **真实端到端从未跑通**：已做过的活体验证覆盖真实 MySQL、真实 DevAtlas 鉴权、真实 HTTP、真实过期 JWT、真实 MySQL 删除（savepoint 回滚），但**分析与检索本身是打桩的**——真实 DeepSeek 模型返回 + 真实 `/search` 检索这条链路一次都没跑过。P1-5-2 又确认了一次这条边界：`POST /analyze` 的**运行时**步骤载荷是用真实服务函数 + 真实落库往返验证的，**没有**跑真实 HTTP 的 analyze（要点它就得先有真实模型返回）。
3. **~~GitHub Actions 结果未确认~~ → 已解决（2026-09-15，P1-4-5）**：run `34930276951` 两个 job 全绿。之前"API 一直 403"的真正原因是查询走了开发机代理（Clash 共享出口 IP，匿名配额用尽）；用 `httpx.Client(trust_env=False)` 直连 `api.github.com` 就能读 run/job/step。
4. **~~前端零自动化测试~~ → 已解决（2026-09-15，P1-5-3 建框架、P1-5-4 扩充）**：`web/tests/` 下 **97 条** vitest 用例（**11 个文件**）覆盖 store（含 `restore()` 的五种分支）、模态抽屉的 ESC/焦点管理、播报、表单错误语义、HTTP 客户端与响应拦截器、路由守卫与 `redirect` 过滤、入口装配，并用 postcss 解析真实 `styles.css` 守住焦点环与减动效果；`npm run test` 已进 CI 前端 job。**仍然欠着的**是**浏览器级**验证——jsdom 不评估 `:focus-visible` 的匹配语义，也不等于屏幕阅读器实际播报，真实导航（地址栏真的变成 `/login?redirect=…`）也没跑；真实点击与真实渲染引擎属 **P2-6 Playwright**。
5. **两笔已知未修的小债**：① `report`/`degraded_summary` 是 JSON 列，"没有报告"可能落成 SQL `NULL` 或 JSON 字面量 `null`（真实 MySQL 8.0.41 上实测 `report IS NULL` 为 0 而 `JSON_TYPE(report)` 为 `'NULL'`），将来用 SQL 过滤"有报告"会踩；② 保留策略默认 `INCIDENT_RUN_RETENTION_DAYS=0`（关闭），**从未在真实默认配置下开启运行过**，只在测试与一次"savepoint 内执行后回滚"的真实 MySQL 验证里跑过。

### 5.3 下一步顺序（用户已定：A → B → C）

- **A（已完成）**："知识库下拉选择" → 编号 **P1-6-1**，后端代理端点 + 前端登录后自动加载的下拉，已实现/测试/活体验证/反证/推送。
- **B（已完成）**：**P1-4-1**（补 45 条测试 + 章节记账）与 **P1-4-5**（CI 变绿：run `34930276951` 两个 job 全绿）。
- **C（进行中）**：**P1-5-1 已完成**（`39f1fe2`：7 个压行文件展开 + 排版守门测试）、**P1-5-2 已完成**（`730268d`：步骤契约统一 + CI 类型比对）、**P1-5-3 已完成**（`b0400fe`：Vitest 50 条进 CI + 键盘可达/焦点管理/播报/减动效果）、**P1-5-4 已完成**（统一 401 处理并区分网络故障：响应拦截器按状态码清会话 + `redirect` 回跳，后端不可达只提示不退出；前端测试 97 条）；**下一步 P1-5-5**（历史抽屉的筛选交互、重跑、失败状态细分展示），之后 P1-5-6（422 `loc` 映射到字段）。

用户明确指定按这个顺序推进；**仍然遵守"一次一项、做完等指示"**，不要连做两项。

**P1-5-5 开工前要知道的事**（已回代码核对，不是凭记忆）：

- 现状：`listRuns` 摘要 + 点开拉详情 + "加载更多" + 相对时间与耗时**已经可用**（P1-3-1/P1-3-3）；仍缺**筛选交互**（状态/时间区间）、**用同一参数重跑**、**失败状态细分展示**（`web/src/constants/status.ts` 已区分 6 种状态并单独处理 `INTERRUPTED`，所以细分展示主要是把它用在抽屉里）。
- 查询参数已经就绪：`web/src/api/runs.ts` 的 `listRuns(params: RunHistoryQuery)` 支持 `status[]`/`started_after`/`started_before`/`cursor`/`limit`，并且用 `paramsSerializer: { indexes: null }` 处理了"数组参数必须写成重复键"（FastAPI `Query(list[str])` 只认重复键）；`stores/incident.ts::loadHistory(params)` 已经把它透传下去——筛选用不着改后端。
- **"重跑"有一个真实约束**：`RunResponse`/`RunSummary`（`app/incident_agent/schemas/incident.py`）里**没有 `content`（原始日志）也没有 `top_k`**——设计文档 §12.1 本来就只存摘要。所以"用相同参数重跑"只能做到"带上 `title`/`knowledge_base_id` 回到表单"，日志正文得让用户重新粘贴；**想要真正的"一键重跑"就必须先加后端字段/接口**（那属于 API 契约变更，按项目约定要先在 `docs/项目补充优化.md` 写明再做）。
- 历史列表**故意没有 `total`**（用 `next_cursor` 判断是否还有下一页），所以"总数/页码"式的交互做不了，也不需要。

---

## 6. 新会话照这个走的流程

```text
1. 读 docs/项目交接文档-DeepSeek.md（本文）和 docs/项目补充优化.md，
   按用户指定的 A → B → C 顺序推进：A（P1-6-1）、B（P1-4-1、P1-4-5）与
   C 的前三步（**P1-5-1 `39f1fe2`、P1-5-2 `730268d`、P1-5-3 `b0400fe`**）都已完成，
   下一步是 **P1-5-5（历史抽屉的筛选交互、重跑、失败状态细分展示）**

2. 读该条目下面列出的「涉及文件」，先读代码再动手，不要凭记忆假设接口
   —— 涉及 DevAtlas 接口时必须读 E:\RagKnowledgeSystem\backend 的真实代码

3. 实现改动，然后按顺序验证：
     py -m pytest tests -q            # 必须全绿（当前基线 381 passed）
     py -m ruff check .               # 全仓必须 0（CI 也跑这条）
     py -m compileall -q app migrations tests
     py -m alembic check              # 只在动了 models/ 时才需要（需本机 MySQL）
     cd web; npm run build            # 只在动了前端时才需要
     cd web; npm run test             # 前端单测（97 条 / 11 个文件；动了 web/ 就必须跑）

   新增测试时同时更新 docs/测试对照-设计文档章节.md，并在模块 docstring 里
   写明「设计文档章节：§x.y」（P1-4-1 建立的记账约定；前端测试见该文档第 6 节）。

4. 做「反证」：把修复临时回退成旧行为，确认相关测试确实会失败，再恢复
   —— 这是本项目每项完成记录里都有的固定动作，也是能写进简历的证据
   —— 实操：先 Copy-Item 备份到 tmp/，改坏，跑测试看失败，再 Copy-Item 恢复
   —— 小心：**备份要用绝对路径，且每次实验前重新备份**。P1-5-3 踩过坑：第一次
      实验留下的旧备份在后续批次里被当成"当前状态"恢复，把已经修好的文件覆盖回去了。

5. 更新 docs/项目补充优化.md：打勾 + 写完成记录（改了什么文件、怎么验证、
   反证结果、测试结果、是否影响迁移/API/前端、简历可用事实）

6. 提交（逐文件 git add，不用 git add .），message 说明做了什么并附验证结果
   —— 较长/含中文的 message 写到 tmp/msg.txt 再 git commit -F tmp/msg.txt

7. 推送；若失败先查梯子，再重试；推送后核对 local == origin
   —— 之后再补一个"docs: record the <编号> commit hash"的小提交（本项目的惯例）

8. 推送后读一次真实 CI 结果（两个 job 都要绿）——别用徽章等缓存，直接查 API：
     py tmp\gh_runs.py                 # httpx.Client(trust_env=False) 直连 api.github.com
   —— 后端 job 会跑 ruff / pytest / compileall / alembic heads，前端 job 会跑
      npm ci + npm run build + npm run test；它同时是"干净环境可跑"的唯一证明。
   —— 碰过 .github/workflows/ci.yml 时必须先本地解析一次 YAML，否则会得到
      一个 0 job 的失败运行（tests/test_ci_workflow.py 也会拦住这种情况）。
```

### 一条反复验证过的经验

**写测试 ≠ 功能完整；本地通过只证明本地。** 本项目已经出现三次"本地全绿但真实环境有问题"：降级摘要只存在响应里没入库、列表接口 N+1 与体积膨胀、**CI 从挂上那天起一直红**（无 `.env` 时测试在收集阶段就失败）。三次都是**把真实环境跑起来看真实输出**才发现的。因此对"当次响应 / 历史回查""真实方言行为""干净环境能否跑"这类问题，务必做一次活体验证（方法见第 8 节与第 9 节第 10–13 条）。

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

# 前端（开发服务器）
cd E:\IncidentAgent\web; npm run dev -- --host 127.0.0.1 --port 5174

# 前端验证与测试（不需要启动任何服务；P1-5-3 起 npm run test 是必跑项）
cd E:\IncidentAgent\web; npm run test      # vitest run，jsdom，97 条 / 11 个文件
cd E:\IncidentAgent\web; npm run build     # vue-tsc -b && vite build
```

### 7.2 ⚠️ 代理环境变量（新会话必读）

这台机器的环境里有 `HTTP_PROXY`/`HTTPS_PROXY`（Clash，`127.0.0.1:7897`）以及

```text
NO_PROXY=localhost,127.0.0.1,::1,[::1]
```

`[::1]` 这个写法会让 `httpx.Client` 在**构造阶段**就抛 `InvalidURL: Invalid port: ':1]'`（httpx 把它拼成 `all://*[::1]` 模式）。后果与处理：

- **pytest**：会让 23 条测试在任何断言之前失败 → 已由 `tests/conftest.py` 在会话开始时清掉代理变量修好，现在应当是 **381 passed**（前端 97 条用 jsdom，不碰网络）；
- **真实服务**：所有 DevAtlas 调用（登录、知识库授权、检索）都会 500（已复现 `exception_type: InvalidURL`）→ 用 `tmp/run_agent_clean.py` 启动（它在 Python 里 pop 掉代理变量再 `uvicorn.run`）；
- **注意**：在这个 shell 里 `$env:NO_PROXY=...` 对子进程**无效**（每层子进程都会被重新注入），必须由 Python 进程自己 pop。

### 7.3 依赖与环境复现

- `requirements-lock.txt`（62 个精确版本）+ `requirements-dev.txt`（pytest、ruff）是复现环境的正确入口；`requirements.txt` 是**经实测校准的下限**（`openai>=3.0`、`langchain-core>=1.0`、`langchain-openai>=1.0`、`langgraph>=1.0`、`httpx>=0.28`），旧下限（0.3/0.27）会把干净环境装成另一个大版本。
- 本机关键的实测版本：openai 3.13.0、langchain-core 1.6.3、langchain-openai 1.6.2、langgraph 1.2.11、fastapi 0.141.1、SQLAlchemy 2.0.52、pydantic 2.13.5、alembic 1.20.0、httpx 0.28.1、pytest 9.1.1、ruff 0.16.5。
- `.env`（不提交）需要：`INCIDENT_DB_*`、`DEVATLAS_BASE_URL`、`DEEPSEEK_API_KEY`。可选变量与默认值见 `.env.example`（含 `INCIDENT_RUN_RETENTION_DAYS=0`）。
- **测试不需要 MySQL**：后端 381 条测试全部使用 SQLite 内存库，可离线运行（前端 97 条用 jsdom，连数据库都不需要）；只有 `alembic check` 需要本机 MySQL。**但两件事要注意**：① 缺少 `INCIDENT_DATABASE_URL` 时连 `import app.main` 都会抛 `RuntimeError`（配置强校验），所以干净环境（含 CI）必须提供一个数据库 URL（CI 用 `sqlite+pysqlite:///:memory:`）；② 每个 API 测试都要自己覆盖 `get_db`，否则会走开发机 `.env` 指向的真实 MySQL（见第 9 节第 10/11 条）。

### 7.4 前端测试与验证方式（P1-5-3 起有正式框架）

```powershell
cd E:\IncidentAgent\web; npm run test      # vitest run，jsdom 环境，97 条 / 11 个文件
cd E:\IncidentAgent\web; npm run build     # vue-tsc -b && vite build
```

- 配置在 `web/vitest.config.ts`（与生产 `vite.config.ts` 分开：不想让 jsdom 进生产依赖图）；用例在 `web/tests/*.spec.ts`，`helpers.ts` 提供 `makeRun()` 与 `resetDom()`。
- **不要再往 `tmp/check_time_helpers.ts` 加用例**：那 14 条已搬进 `web/tests/time.spec.ts`（`tmp/` 里那份不再维护）。
- 想验证"真实渲染产物"时，可用随 vue 一起装的 `@vue/server-renderer` 做 SSR 探针（P1-5-3 就这么确认了 `role="dialog"`/`aria-live` 确实出现在产物里）；探针脚本放 `tmp/`，不进仓库。
- 浏览器级行为（`:focus-visible` 的匹配语义、真实点击、屏幕阅读器实际播报）**仍然没有**自动化手段，属 P2-6 Playwright。

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
| `tmp/live_kb_catalog.py` | 真实登录后打 `GET /api/v1/knowledge-bases`，并与 DevAtlas 直连结果逐字段对比（P1-6-1） |
| `tmp/gh_runs.py` | `trust_env=False` 直连 GitHub API，读 CI 的 run/job/step 真实结论（P1-4-5） |
| `tmp/p153_probe/p153-live.spec.ts` | 用 `@vue/server-renderer` 真实 SSR 渲染组件，检查无障碍属性出现在产物 HTML 里（P1-5-3；输出在 `tmp/p153_probe_output.txt`） |
| `tmp/backup_agent_runs_before_p042.sql`、`tmp/backup_before_degraded_summary.sql` | 改数据前留的 MySQL 备份（当时的安全网） |

> `tmp/` 里还有一堆 `*_backup.py` 是各次反证前的文件备份，`commit_msg_*.txt` / `msg_*.txt` 是提交信息草稿，`annotate_*.py`、`trim_checklist.py`、`probe_*.py` 是一次性脚本——都可以随时删，不影响任何东西。

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

（这是 2026-09-15 的快照；P1-5-3 只动前端，**没有改过任何数据**，所以这段仍然有效。真要用之前先跑一次 `tmp/live_p133_mysql.py` 之类的探针确认。）

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
10. **`import app.main` 在没有数据库配置时会抛 `RuntimeError`**：`core/config.py` 在缺少 `INCIDENT_DATABASE_URL` 时强制要求 `INCIDENT_DB_USER/_PASSWORD/_NAME`（快失败是有意的）。代价是**任何"干净检出"都必须提供其中一个**：CI 的 backend job 因此显式设 `INCIDENT_DATABASE_URL`；写测试时也别指望开发机的 `.env`。
11. **测试里的 `get_db` 必须自己覆盖**：开发机的 `.env` 指向真实 MySQL，漏覆盖时用例会"因为机器上恰好有表"而通过（`test_error_handling` 就踩过：干净检出里 404 变 500）。新写 API 测试时先问一句"这条请求会不会真的查库"。
12. **workflow 的 YAML 对冒号很敏感**：`KEY: sqlite+pysqlite:///:memory:` 这种**以冒号结尾的裸标量**会让整个文件解析失败。GitHub 的表现是产出一个 **0 job 的失败运行**、工作流名退化成 `.github/workflows/ci.yml`——看到这个形态先怀疑 YAML 而不是测试。`tests/test_ci_workflow.py` 已把"workflow 能解析且关键步骤在"变成回归测试。
13. **查 GitHub Actions 结果别走代理**：`api.github.com` 走 Clash 出口会被共享 IP 的匿名配额限流（403）。`httpx.Client(trust_env=False)` 直连即可（`tmp/gh_runs.py`）。
14. **Vue 模板的空白是有语义的，"换行"与"空格"不等价**（P1-5-1 实测；编辑任何 `.vue` 模板前先读这条）：`whitespace: 'condense'` 下，**元素与元素之间**新增的换行会被整段删除（安全），但**紧贴文本或插值**的换行会被并进文本、变成一个空格——`<label>用户名<input/></label>` 拆成三行后文本会变成 `" 用户名 "`，渲染凭空多出空格。规律：拆行只在元素边界做；混合内容（文本/插值与元素相邻）必须留在同一行；一行太长时只拆"最内层标签的属性"（标签内部的空白无意义）。P1-5-1 用 `@vue/compiler-sfc` 的 `compileTemplate` 产物逐字节比对验证过这些规则，探针在 `tmp/p151_probe.mjs`（`tmp/` 不提交）。
15. **别把 `ts.createPrinter()` 当成"空白无关的规范化"**（P1-5-1 走过这段弯路）：TypeScript 的 printer 对**未变换的解析节点**会直接回写原始源码片段，换行与缩进照样留在输出里——看起来比较过了，其实什么都没规范化（第一次就是这么被骗过的）。要比对脚本层语义，用 AST 叶子 **token 流**（忽略显式分号与尾随逗号即可；字符串内部空格仍逐字比对，注释单独比对）。
16. **`app.openapi()` 就是真实服务外发的契约**（P1-5-2 实测）：真实启动服务后 HTTP 拉 `/openapi.json`，13 个受约束组件与进程内 `app.openapi()` 逐字节相等，所以类型契约测试不必起服务。但 `RunResponse.steps`/`observations` 在后端是 JSON dict，OpenAPI 里只有 `array<object>`——这类"后端没有 Pydantic 模型"的载荷必须用**真实数据**比对（P1-5-2 的做法：跑真实 Graph + `append_steps` 落库往返）。
17. **前端测试的 jsdom 陷阱**（P1-5-3 实测）：① `import.meta.url` 在 vitest 里会被改写成 http 形式，`fileURLToPath(import.meta.url)` 直接抛 `The URL must be of scheme file`——测试里定位文件用 `process.cwd()`（测试的 cwd 是 `web/`）；② `wrapper.get()` 找不到元素时抛的是 `Target cannot be null or undefined`，`emitted('test')` 返回 `undefined` 时 `.toHaveLength()` 也抛同一句话——**看到这句话先怀疑"元素/事件不存在"，而不是断言写法**；③ jsdom 不会因为 `trigger('click')` 就去设置 `document.activeElement`（真实浏览器会），测焦点时必须显式 `element.focus()`。
18. **PowerShell 5.1 读脚本按 ANSI，中文会乱码成语法错误**（P1-5-3 实测）：用文件工具写出的 `.ps1` 是 UTF-8 **无 BOM**，`powershell -File` 会按 GBK 解码，中文注释/字符串变成乱码后连引号都配不上（报一堆"哈希文本不完整/意外的标记"）。**给脚本加 UTF-8 BOM** 即可：
    ```powershell
    $t=[System.IO.File]::ReadAllText((Resolve-Path $p), [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText((Resolve-Path $p), $t, [System.Text.UTF8Encoding]::new($true))
    ```
    另外：`.NET` 静态调用（`[System.IO.File]::ReadAllBytes`）会把**进程的当前目录重置成 PowerShell 的启动目录**，之后所有相对路径都会指错——脚本里一律传绝对路径。用 `Get-Content` 看 UTF-8 文件也会花屏（见第 9 条），要读内容用文件工具。
19. **反证的备份要用绝对路径、且每批实验前重新备份**（P1-5-3 踩的坑）：第一次失败的实验跑给 `tmp/p153_backup/` 留下了一份**早于最新修改**的备份，第二批实验用 `-replace` 拼出的相对路径既非绝对、文件名也不对，于是"恢复"实际上什么都没做（`Copy-Item` 报 `Cannot find path`，`$ErrorActionPreference='Stop'` 也没拦住非终止错误）。后果是 E1 的改动（把 `addEventListener` 换成注释）留在了工作区，差点被当成"已恢复"。**核对方式**：每个实验恢复后立刻比 `Get-FileHash`，并保留"恢复后逐字节一致"的输出。
20. **P1-5-4 相关（已完成，这里保留"下一项会踩的地方"与两个新坑）**：① `apiErrorMessage()` 里 `error.code === 'ECONNABORTED'` 判的是 axios 的超时码，但**同一个错误上 `error.response` 才是 HTTP 状态**——想按状态码分流必须看 `error.response?.status` 与后端统一契约里的 `error_code`（`UNAUTHORIZED`）。P1-5-4 之前 `IncidentWorkspaceView.submit()` 用的是 `apiErrorMessage(failure).includes('401')`，**这条判断在真实响应上永远不会命中**（`apiErrorMessage` 优先返回中文 `detail`），也就是"令牌过期后前端根本不会退出登录态"；现在判据只有一处：响应拦截器里的 `isAuthFailure()`（状态码 + `error_code` 交叉核对）。② `auth.restore()` 曾经 **catch 一切就 `signOut()`**；现在是"401/403 清会话，连不上/超时/上游 5xx 只提示并保留 Token"。③ 401 之后仍会跳登录页——`router.beforeEach` 只检查 `localStorage` 里有没有 token，所以**清 Token 的副作用就是"下一次导航会被拦到登录页"**；跳转由 `src/main.ts` 注册的处理函数做（`client.ts` 有意不 import router/store，避免模块成环）。④ **新坑：jsdom/vitest 里给 axios 换自定义 `adapter` 时，4xx 会被当成成功响应**——自定义 adapter 的返回值不再经过 axios 内部的 `settle()`（那是 adapter 自己的职责），必须自己抛 `AxiosError(msg, code, config, request, response)`。第一版 `apiClient.spec.ts` 就是因此全绿假象。⑤ **新坑：反证脚本的 `Get-FileHash` 只能证明"恢复后 == 备份"，证明不了"备份本身就是坏文件"**——P1-5-4 的批量脚本第一版在备份**之前**就先改坏了一次，于是"备份"里存的是坏文件，后续实验叠加上去导致 `client.ts` 出现两行 `return false`，而脚本的哈希校验全过。教训：改坏前**先全部备份**、每个实验只做互不重叠的替换，恢复后再**读一次实现**核对（这里是 `git diff` + 全量测试）。

---

## 10. 尚未验证 / 已知功能边界（如实列出，不要当成已完成）

1. **真实模型返回与真实检索未跑通**（见 5.2 第 2 条）：已验证的是真实 DB、真实鉴权、真实 HTTP、真实过期令牌；**分析链路仍靠 FakeModel/MockRagGateway**。
2. **~~CI 在 GitHub 上的运行结果未确认~~ → 已确认（2026-09-15）**：run `34930276951` 两个 job 全绿，P1-4-5 已勾选；此后每一项推送后都读了真实结果（P1-5-1：`34932240446`；P1-5-2：`34941997248`、`34942094169`；**P1-5-3：`34944164842`**），**都全绿**。顺带发现并修掉了三类"只在开发机上通过"的缺陷（无 `.env` 时收集阶段失败、两条用例依赖真实 MySQL、workflow 里的 YAML 引号），其中第一条正是 CI 一直红的原因。P1-5-3 那次尤其值得记：**"运行单测"这一步一次通过**，说明这 50 条用例在干净环境（Ubuntu + Node 22 + `npm ci`，没有本机 `node_modules`）里也装得上、跑得动——如果只在本地跑过，`package-lock.json` 少了平台相关包这类问题要等到别人拉下来才暴露。
3. **前端仍没有浏览器级自动化测试**（P1-5-3 补了组件级、P1-5-4 补了 HTTP/路由/入口级）：现在有 `vue-tsc` + `vite build` + **97 条 vitest/jsdom 用例**（`npm run test` 进 CI），加上 P1-5-1/P1-5-2 留下的两个 **Python 侧**守门测试（排版、类型契约）。**但 jsdom 不是浏览器**：`:focus-visible` 的匹配语义、真实点击与真实渲染、屏幕阅读器实际播报、P1-5-4 的"地址栏真的变成 `/login?redirect=…`"都没有自动化手段，属 P2-6 Playwright。
4. **保留策略从未在真实默认配置下开启运行过**（默认关闭）。
5. **已知功能边界**（有意设计，不是漏项）：`138-0013-8000` 这类带分隔符的手机号不会被脱敏命中；`AgentStep.arguments_summary` 等的原始文本不入库（只存长度/计数）；历史列表不返回 `total`（用游标判断是否还有下一页）。
6. **测试侧的已知边界**（P1-4-1 记账时确认，详见 `docs/测试对照-设计文档章节.md` 第 5 节）：① 设计文档 §17.2 案例 7 写的是"服务状态工具超时"，但 `get_service_status` 是进程内 mock、没有 I/O，所以**不可复现**，现用检索超时（`RAG_TIMEOUT`）覆盖其意图，真实 provider 属 P2-5；② `analyze_log` 的 `MAX_MATCHED_TEXT = 120` 在现有 4 个正则下**不可达**（最长命中 11 字符），属防御性代码、无法构造用例。
7. **P1-5-3 自己留下的边界**：① 焦点陷阱只处理 Tab/Shift+Tab，没有用 `inert`/`aria-hidden` 把抽屉背后的内容整体摘出可访问性树（`aria-modal="true"` 已表达模态语义）；② 测试只断言"可访问性契约正确"（角色/名称/live region/焦点位置），**不证明屏幕阅读器真的念对了**——那需要真实的辅助技术，不在自动化范围内。

---

## 11. 简历可用事实

**可以写**：LangGraph 条件路由与循环上限、统一 `ToolResult` 协议与错误码归一化、Pydantic 双层校验（工具入参 + 最终报告）、`owner_user_id` 级运行记录隔离、JWT 只在请求内转发不落库、MockRagGateway/FakeModel 确定性测试体系、跨 MySQL/DevAtlas 的边界错误归一化、知识库归属强制预校验、敏感数据落库前脱敏、零证据语义、证据来源服务端溯源核验、确定性降级摘要、模型超时与请求预算治理、中断记录回收、结构化日志与步骤轨迹、不可信内容定界、报告容错与受限修复、全仓 lint 门禁与 CI、统一错误响应契约（`request_id` 关联响应与日志）。

P1-3 整组新增可写：

- 历史列表用一条聚合 SQL 消除 N+1 并改为摘要契约（实测列表体积由单条 18.7 KB 降到 316 B，查询数与 run 条数无关）；
- 运行时间线与服务端派生耗时（对未结束与被中断的运行明确返回空值，避免把进程宕机时长当成分析耗时）；
- 基于 `(started_at, id)` 行值比较的游标分页（每页一条 SQL、不需要 COUNT 总数查询、并发新增下不重不漏）+ 状态/时间过滤 + 可配置且带审计日志的历史保留策略；
- 权限与失败分支回归测试：越权查询与不存在 ID 的响应不可区分（避免存在性泄露）、过期令牌在三个入口一致 401 且零副作用、数据库写失败返回不含内部细节的安全错误并依赖启动回收机制收尾。

P1-6-1 新增可写：

- 只读代理端点收敛跨服务契约：浏览器不直连上游知识库服务（避免跨域与凭据落地），Agent 原样转发用户 Token、只下发 `id`/`name`/`description`（不下发 owner 与时间戳），并把上游 401/404/5xx/超时/非法载荷归一化为统一错误契约；配套 11 条离线测试 + 真实 DevAtlas 活体验证（代理结果与直连结果裁剪后逐字段相等）。

P1-4-1 新增可写：

- 按设计文档的测试分层补齐边界与失败分支用例：统一工具结果协议的非法形状归一化（7 种形状 → 可诊断的失败观察、不泄露原始载荷）、输入上限的包含边界（恰好等于上限通过、+1 拒绝）、大输入下的有界输出与不回显、并把十条验收案例逐条落到可执行断言；同时建立"测试 ↔ 设计文档章节"的对照记账（每个测试文件标注章节、新增 `docs/测试对照-设计文档章节.md`）。过程中还发现并修掉一个真实缺口：纯空白标题/内容当时能进模型。

P1-4-5 新增可写：

- 让 CI 从"看起来配好了"变成"真的有拦截力"：读真实运行结果后定位并修掉三类环境耦合缺陷——无 `.env` 的干净检出中导入即失败（配置强校验）、两条用例静默依赖开发机数据库、workflow 定义因 YAML 引号问题整体失效（表现为 0 job 的运行）；并为 workflow 定义补了回归测试。

P1-5-1 新增可写：

- 把前端压行代码按常规格式展开（含 2950 字符的单行样式表：59 行 → 1052 行），并用**编译产物**证明纯排版改动零行为差异——CSS 比 postcss AST、script 比 TypeScript token 流、模板比 `compileTemplate` 的 render 代码（模板空白有语义，必须先量出 `whitespace:'condense'` 的规律再动手：元素之间的换行会被删除、贴着文本/插值的换行会多出空格），最终生产构建产物与改动前逐字节相同；同时补上四条排版守门规则让回归能被 CI 拦截（含 `@import url(...)` 内分号误报的修正）。

P1-5-2 新增可写：

- 把"手写前端类型与后端契约的漂移"变成 CI 门禁：先用探针量出真实载荷，发现根因不是缺几个字段，而是 `POST /analyze` 与 `GET /runs/{id}` 对同一次运行的 5 条步骤返回了 **4 种形状**（泄漏内部耗时起点 `_started_at` 与 `ok`/`attempts`，且缺 `step_index`，而前端正拿它当列表 key）；于是抽出唯一的步骤投影让两个接口同形状，再以 OpenAPI schema + 真实载荷（真实 Graph + 落库往返）双向比对 17 个手写 TS 接口（字段集合 / 可空性 / 枚举 / 可选性），零新依赖接入 CI。

P1-5-3 新增可写：

- 为前端补上自动化测试与无障碍支持：引入 Vitest + `@vue/test-utils` + jsdom 并接入 CI（50 条用例覆盖 store 状态机、模态抽屉的 ESC/焦点陷阱/焦点归还、表单错误播报与 `aria-live`），把此前只靠手跑脚本验证的时间工具纳入回归；用 postcss 解析真实样式表守住 `:focus-visible` 与 `prefers-reduced-motion`，并用 `@vue/server-renderer` 的 SSR 产物验证无障碍属性确实出现在渲染结果里；过程中发现并修掉一个真实缺陷——ESC 监听器注册在 `await` 之后，导致对话框刚打开时关不掉。

P1-5-4 新增可写：

- 把前端的会话失效处理从"靠错误文案 `includes('401')` 判断"改为"按 HTTP 状态码 + 统一错误契约的 `error_code` 统一拦截"：先量出原判据在真实响应上**永远不会命中**（`apiErrorMessage()` 优先返回后端中文 `detail`，所以令牌过期后前端根本不会退出登录态），再让响应拦截器成为唯一判据，并区分 `401/403`（清会话、带 `redirect` 跳登录页回跳）与"后端不可达 / 请求超时 / 上游 5xx"（只提示、保留令牌，网络抖动不踢人）；`redirect` 是地址栏输入，用白名单过滤挡住 `//evil.example` 这类协议相对地址（开放重定向）。测试侧用**真实 axios 实例 + 真实 auth store** 跑通同一条链路（而不是 mock 掉 axios），因此当场发现"自定义 adapter 的响应不再经过 axios 的 `settle()`，4xx 会被当成功响应"这个只在测试替身里存在的陷阱；最后用 5 个反证实验逐个证明测试真的会红，其中"删掉状态码判断"那个反证当场抓出了自己测试里的假绿（补了一条"状态码优先"的用例才抓到），并用真实服务验证了"DevAtlas 停机 → 503 + DEPENDENCY_UNAVAILABLE"与"真实过期令牌 → 401 + UNAUTHORIZED"确实是两类。

**仍不能写成"已实现"**：SSE 流式分析、真实监控 provider、Redis、MCP、多 Agent、自动修复、高并发、真实准确率、生产上线规模。

---

## 12. 给新会话的第一句话建议

> 读 `docs/项目交接文档-DeepSeek.md` 和 `docs/项目补充优化.md`，用户已定顺序 **A → B → C**：A（P1-6-1 知识库下拉选择）、B（P1-4-1 补测试、P1-4-5 CI 变绿并确认）与 **C 的前四步 P1-5-1（7 个前端文件压行拆分，`39f1fe2`）、P1-5-2（前后端类型统一 + 步骤契约只有一份，`730268d`）、P1-5-3（Vitest 50 条进 CI + 键盘可达，`b0400fe`）、P1-5-4（响应拦截器统一 401 + 区分网络故障，前端测试 97 条）** 都已完成推送（P1-5-4 的 CI run 见 `docs/项目补充优化.md` 的完成记录）。下一步是 **C 的第五步：P1-5-5 历史抽屉使用详情接口**（剩筛选交互、用同一参数重跑、失败状态细分展示；注意列表接口本来就是摘要 + 游标、"重跑"缺 `content`/`top_k` 字段的约束见交接文档 §5.3），然后 P1-5-6（422 `loc` 映射到字段）。按约定：一次一项、实现+测试+推送齐了才打勾、不跳项、不用 `git add .`，每项都要做反证并写完成记录（反证脚本照 `tmp/p154_counterexamples.ps1` 的结构：先全部备份、再逐个改坏、恢复后比 `Get-FileHash` **并读一次实现**）。

### 12.1 新会话开场建议跑的三条命令（30 秒内确认接手状态）

```powershell
cd E:\IncidentAgent; git log --oneline -5; git status --short   # 工作区应当干净
cd E:\IncidentAgent; py -m pytest tests -q                      # 期望 381 passed
cd E:\IncidentAgent\web; npm run test                            # 期望 11 files / 97 passed
```

三条都对得上，就说明本文档描述的状态与代码一致，可以直接从 §5.3 的 P1-5-5 开始；对不上就先按 §9 的坑逐条排查，不要直接动手改代码。

### 12.2 `tmp/` 里的东西怎么用（新会话可直接改，都不提交）

`tmp/` 被 `.gitignore` 挡住，是历次任务的**探针与证据**，新会话可以随意复用/删除，不影响仓库：

| 类别 | 例子 | 说明 |
| --- | --- | --- |
| 活体验证探针 | `run_agent_clean.py`、`live_*.py`、`gh_runs.py` | 见 §8 的表；这是本项目最有价值的验证手段 |
| P1-5-4 的活体验证探针 | `p154_live_401_contract.py`（真实 401/503 契约）、`p154_live_auth_flow.py`（真实登录/过期令牌/上游不可达）、`p154_run_devatlas.py`（清代理变量后启动 DevAtlas） | 三个都是"起真实服务再读真实响应"，`tmp/` 不提交；下一个动鉴权/错误契约的项直接改这三个 |
| P1-5-3 的反证脚本 | `p153_break.ps1`（按 `-Index` 跑单个实验）、`p153_counterexamples.ps1`（批量）、`p153_backup2/`（那一刻的备份） | 结构：逐文件备份 → 改坏 → 跑测试 → 恢复 → 比 `Get-FileHash` |
| P1-5-4 的反证脚本 | `p154_counterexamples.ps1`（5 个实验 + 恢复后哈希核对）、`p154_backup/` | **比 P1-5-3 那份多两条纪律**：① 改坏**之前**先把所有文件备份完；② 恢复后除哈希外还要读一次实现（`git diff`）——哈希只能证明"恢复后 == 备份"，证明不了"备份没坏"（P1-5-4 在这里踩过） |
| P1-5-3 的 SSR 探针 | `p153_probe/p153-live.spec.ts`、`p153_probe_output.txt` | 真实渲染产物里核对无障碍属性的证据 |
| 一次性脚本与草稿 | `annotate_*.py`、`trim_checklist.py`、`probe_*.py`、`msg_*.txt`、`commit_msg_*.txt` | 都可以随时删 |
| 数据安全网 | `backup_agent_runs_before_p042.sql`、`backup_before_degraded_summary.sql` | 改真实 MySQL 数据前留的备份 |

`tmp/check_time_helpers.ts` 已**作废**（它的 14 条用例搬进了 `web/tests/time.spec.ts`），不要再往它里面加用例。
