# Agent runtime：一轮工作如何被约束和记录

状态：代码现状，不是模型质量承诺；核验日期：2026-11-19。
来源：[执行器](../../backend/app/runtime/executor.py)、[LangGraph 适配](../../backend/app/runtime/langgraph_loop.py)、[上下文](../../backend/app/runtime/context.py)、[提交](../../backend/app/runtime/commit.py)、[工具运行器](../../backend/app/runtime/tool_runner.py)。

## 一轮生命周期

1. 用户 utterance 带任务和幂等键提交。API/服务检查归属、任务状态和余额，创建 Feedback/Run 并冻结预算，返回 queued。
2. Worker 领取，执行器装配任务、当前版本、约束、偏好、模型档案和历史。没有另一次前置模型分类作为每句输入的必经步骤。
3. 模型在循环中选工具、回答或提问；ToolRunner 根据 Agent 工具白名单、schema、预算和执行边界运行。
4. 工具输出经校验/评估，提交追加版本；拒绝结果不推进 current，不能把“调过工具”当成功产物。
5. 运行中记录工具/模型调用和事件。最终由执行器记录回答、状态与结算；浏览器通过 SSE 和权威任务数据展示。

详情与字段以源码为准，不复刻整个循环为另一套可漂移伪实现。

## Agent、工具与技能

[注册表](../../backend/app/agents/builtin.py)包含 PDP、image、canvas 专家和聚合 general。专家不能任意调用其他 Agent 工具；general 聚合工具与技能，但仍受任务槽位、写入范围和预算检查。工具输入 schema、成本和超时在[生成表](../generated/tools.md)查看。

[技能解析](../../backend/app/agents/skills.py)读取产品技能 Markdown 的 audience/description；[技能修订](../../backend/app/services/skill_edits.py)保留编辑版本，组合根会覆盖有效技能内容。`skills/` 中也有流程类技能，是否适合产品用户仍需产品决定；本轮不改变其内容或加载权限。

`Settings.skill_dir` 虽读取 `SKILL_DIR`，但当前组合根调用 `build_registry()` 未传该字段。不能宣传该变量已能切换实际技能来源；现状与待办见[探索](../exploration/current-state.md)。

## 上下文、记忆与视觉

任务状态块、最近结构化回合和摘要共同进入规划上下文；压缩参考已有真实 prompt token 数，缺少时回退估算。手工/自动压缩与产物版本不同，不能靠摘要替代版本历史。带 vision 能力的 profile 才发送图像；只给 object_key 不是让模型看见图片。

checkpoint 的 `thread_id` 是 Run ID，不是 Task ID。持久化用于本轮恢复，不充当全部跨轮产品记忆。内存数据库测试用内存 checkpoint；文件数据库策略见[运维](../operations/runbook.md)。

## 规则、评估与有限自修复

- `record_constraint` 起草 pending 规则，用户确认后才成为 effective。偏好 proposal 有自己的确认路径。
- 提问是本轮的终点行为，不能让重复 ask_question 持续耗尽循环。
- 评估拒绝信息回传工具结果，有限次数、预算和可修性检查共同决定是否允许自修复；不能无限付费重抽。
- 确定性图像修复与付费重画不同；不能把不支持的编辑操作解释为已经完成。

对应证据：[提问循环](../../backend/tests/test_ask_question_loop.py)、[评估修复](../../backend/tests/test_evaluator_optimizer.py)、[记忆与版本工具](../../backend/tests/test_version_tools.py)。fake 测试证明约束路径，不证明真实模型遵守每条意图。

## 失败、取消与结算

RunFailed（例如预算/步数）按已发生成本结算；未分类的平台错误走平台故障路径，积分处理按实现规则。WorkerStopped 可以重排队，但次数有上限；恢复的工具调用和版本不得重复提交。取消也区分 queued 和运行中，不承诺立即中断所有外部请求。

[运行时测试](../../backend/tests/test_langgraph_runtime.py)、[平台测试](../../backend/tests/test_platform.py)覆盖部分恢复/幂等行为；进程崩溃、跨机器故障和供应商请求真实重放还需专门演练。
