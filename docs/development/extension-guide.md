# 如何安全扩展项目

状态：开发指导，按现有组织；核验日期：2026-11-19。
来源：[注册表](../../backend/app/agents/registry.py)、[内置注册](../../backend/app/agents/builtin.py)、[架构测试](../../backend/tests/test_architecture.py)、[协作流程](../../CONTRIBUTING.md)。

## 开始顺序

明确用户目标 → 找到/新增待确认 REQ 与 AC → 查当前源码和用例 → 提计划与影响 → 补失败测试 → 最小实现 → 更新文档与追踪 → 技术验证 → 人工验收。新功能不能仅靠“把一个类放进去”判定完成。

| 扩展对象 | 必查位置 | 需要证明什么 |
| --- | --- | --- |
| Agent | agents/registry、builtin、prompts；前端入口/任务种类 | 注册、工具和技能 audience 正确；不能越权；新增 UI 与既有任务兼容 |
| Tool | tools、ports、ToolRunner、runtime 提交路径 | 输入/输出 schema、成本/超时、权限、失败、作用范围与幂等；供应商 I/O 仍在 infrastructure |
| Skill | skills 下产品 Markdown、agents/skills、注册/修订服务 | description/audience 可解析、专家隔离、通用聚合；许可证保留；不混入本机 Agent 设置 |
| Slot/产物种类 | domain/slots、版本提交、任务 views、前端类型/预览 | 任务允许范围、版本/评估/current 不变量；不只加一处字符串 |
| Evaluator | evaluators、builtin 注册、commit | 描述与 can_reject、可复现规则、拒绝不推进 current；重试成本边界 |
| API | api 声明路由、auth_routes、main、前端 client/types | 声明权限/限流、归属、CSRF、错误、请求/响应、生成覆盖与 OpenAPI 一致 |
| UI | views/components、state、api/types | 真状态而非假成功、加载/失败/空态、SSE/回连、键盘/浏览器体验 |

## 更新契约

保持[数据不变量](../architecture/data-and-contracts.md)；细读[运行时](../architecture/agent-runtime.md)。不要在 tools/domain 直接连数据库或供应商 SDK。修改协议时同步前后端类型和测试；修改 profile 能力不等于真实供应商已支持。

API/注册表变动后运行生成器而不是手改表格，完整步骤见[测试策略](../quality/test-strategy.md)。追踪矩阵链接到真实实现和测试，不用“待补”掩盖完成标准；未覆盖项必须明确列风险。

## 交付给人的材料

给出 REQ/AC、影响范围、diff、实际门禁结果、模型/浏览器等未验证项、可复现的人工步骤。新设计与计划可放 docs/superpowers 并标注状态；当前正文必须同步更新，不能要求人从十份计划猜现在的系统。
