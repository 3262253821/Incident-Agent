# Incident Agent 测试用例

## 测试目标

验证 Incident Agent 的工具参数校验、工具结果、状态路由、失败降级、循环保护和最终报告结构。

说明：

- 单元测试和图路由测试不依赖真实模型 API；
- 真实模型演示用于人工检查，不作为稳定自动化测试；
- 测试轨迹中不得记录 API Key、完整敏感日志或密码。

| 编号 | 场景                   | 输入或模拟条件                                 | 预期工具/路径                                                          | 预期结果                                                                    |
| ---- | ---------------------- | ---------------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| T01  | 数据库故障正常分析     | `order-service 502 + mysql connection timeout` | `analyze_log`、`search_knowledge`、`get_service_status(order-service)` | 工具成功；获得日志、知识库和服务状态证据；可生成 `database` 类报告          |
| T02  | 超时但没有数据库关键词 | `payment-service timeout`                      | `analyze_log`、`get_service_status(payment-service)`                   | 不应无依据断定数据库故障；报告类别应为 `network`、`dependency` 或 `unknown` |
| T03  | 未知服务               | `gateway 返回 502，请检查 gateway`             | `get_service_status(gateway)`                                          | 工具返回 `UNKNOWN_SERVICE`；图进入 `degrade`；状态为 `degraded`             |
| T04  | 空日志参数             | `analyze_log("")`                              | `analyze_log`                                                          | 参数校验失败；返回统一失败结构和错误码                                      |
| T05  | 知识库无结果           | 查询不存在的故障关键词                         | `search_knowledge`                                                     | 工具成功但 `sources` 为空；报告应说明证据不足，不得编造引用                 |
| T06  | 检索工具异常           | 模拟 `search_knowledge` 抛出异常               | `search_knowledge`                                                     | 工具失败；State 记录错误；按当前严格策略进入 `degrade`                      |
| T07  | 服务状态工具超时       | 模拟 `get_service_status` 超时                 | `get_service_status`                                                   | 返回 `TIMEOUT` 或统一失败结构；图进入 `degrade`                             |
| T08  | 模型返回非法 JSON      | 模拟报告模型返回普通文本或 Markdown            | `report`                                                               | `json.loads()` 失败；状态为 `degraded`；错误说明“报告不是合法 JSON”         |
| T09  | 模型重复请求同一工具   | 模拟多轮重复调用相同工具和相同参数             | `agent → tools → observe → agent`                                      | 记录重复调用轨迹；后续可增加去重策略；不得无限循环                          |
| T10  | 达到最大循环次数       | 模拟模型连续请求工具超过 `MAX_ITERATIONS`      | `agent → limit → END`                                                  | 状态为 `max_iterations`；错误说明达到最大请求次数                           |

## 当前已观察到的失败案例

### F01：模型请求了未注册的 mysql 服务

现象：

```text
模型在同一轮调用了：
- analyze_log
- search_knowledge
- get_service_status(order-service)
- get_service_status(mysql)
```
