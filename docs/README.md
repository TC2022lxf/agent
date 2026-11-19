# 文档地图：人和 Agent 的共享入口

状态：现状与协作基线；核验日期：2026-11-19。产品需求仍需所有者逐项确认，本文不是产品验收签署。

## 六个问题

| 问题 | 权威正文 |
| --- | --- |
| 这是什么，应该解决什么问题？ | [产品需求](product/requirements.md) |
| 现在能做什么，哪里还没完成？ | [能力清单](product/capabilities.md)、[探索与差距](exploration/current-state.md) |
| 为什么这样组织，实际如何运行？ | [系统](architecture/system.md)、[Agent runtime](architecture/agent-runtime.md)、[数据与协议](architecture/data-and-contracts.md) |
| 怎样运行和修改？ | [本地开发](development/local-development.md)、[扩展指南](development/extension-guide.md) |
| 怎样指引 AI、验证交付？ | [协作流程](../CONTRIBUTING.md)、[验收场景](product/acceptance.md)、[测试策略](quality/test-strategy.md)、[追踪矩阵](quality/traceability.md) |
| 怎样部署，证据在哪里？ | [运维](operations/runbook.md)、[本轮验证报告](releases/2026-11-19-baseline-verification.md) |

编程 Agent 还须先读 [AGENTS.md](../AGENTS.md)。人和 Agent 引用同一份正文，不维护互相冲突的两套知识。

## 权威来源与冲突处理

- **目标/意图**：人的明确确认和产品契约。代码不能自行确立需求优先级。
- **当前行为**：源码、配置、注册表；文档解释现状，不替代源码。
- **验证证据**：具体环境与变更身份下的实际命令、断言、人工观察；测试不是无限范围的正确性证明。
- **设计/计划**：`superpowers/specs` 与 `superpowers/plans` 记录这次文档工程及未来工作，不是产品事实。
- **参考资料**：[API](generated/api.md)、[Agents](generated/agents.md)、[Tools](generated/tools.md)、[Skills](generated/skills.md)、[Slots](generated/slots.md)、[Evaluators](generated/evaluators.md)来自代码生成，只读。
- **输入/原型**：fixtures 与 design 不拥有需求、权限或行为规则的最终解释权。

遇到冲突先写清“目标、实现、证据”的差别；不要默默改文档让其看起来都一致。旧人工资料已按批准清单从工作树移除，不另建 archive；恢复历史必须有明确目的，不能把旧约束重新当当前事实。

## 状态词

| 维度 | 允许状态 |
| --- | --- |
| 需求确认 | 待负责人确认 / 已确认 / 已否决 |
| 实现 | 已实现 / 部分实现 / 占位 / 计划 / 未判断 |
| 验证 | 自动化已验证 / 待真实模型验证 / 待浏览器验证 / 未验证 |
| 人工验收 | 未执行 / 通过 / 不通过（人及日期） |
| 发布 | 未批准 / 已批准（人及版本） |

“已实现”与“未验收”可以同时成立。编程 Agent 不得替负责人自动更新后两个维度。

## 更新方法

改行为时先找需求和 AC，改代码与测试，更新受影响正文/追踪，再生成资料并运行检查。文档检查不访问外链，不验证文档所有语义，也不能确认截图、真实模型效果与部署安全；这些必须由相应验证补充。
