# 0044 删掉前置路由：一句话就是一次请求，规则是工具

日期：2026-11-09

## 决定

删除 `RunExecutor._interpret`（循环前的意图分类模型调用）。一句话进来就直接进入
ReAct 循环，成为**一条** Feedback。原来那四个标签各自变成循环里的一件真实事情：

| 旧标签 | 现在 |
| --- | --- |
| `parameter_patch` | 默认。循环照常选工具、写版本 |
| `new_constraint` | 工具 `record_constraint`，写入待确认草稿 |
| `question` | 工具 `ask_question`（本来就有） |
| `strategy_switch` | 不是一个分类，是模型选了不同的工具 |

跟着 Claude Code 的形态：一次 `while(tool_call)`，路由就是模型自己决定"调工具 / 说话 /
问人"。

## 为什么原来要前置

只有一个理由站得住：**在花钱的动作发生前先判断这句话的性质**。`new_constraint` 的语义是
"不能生成版本，只能起草一条规则"，而画一次图要 20 积分。放在循环里，就必须相信模型不会
一边记规则一边顺手把图画了。

其余两个理由都不成立：

- *拆分一句话成多条请求* —— 循环里模型可以连续发多个 tool_call，本来就是顺序执行的。
- *用便宜模型做路由* —— 代价是 40–50 秒的额外往返，排在用户看到任何产物之前。

而且前置的准确率不够，所以堆了一层规则补丁：`_PROTECT_SLOT`（"不要动"永远不是规则）、
`_repair`（UI 选中的 slot 覆盖模型）、`_normalize_interpretation`（模型回显中文标签）。
这些补丁本身说明：LLM 分类的边界不稳，而工具调用的边界由 schema 和执行路径保证。

## 代价，以及怎么补

**1. "起草规则 vs 出图"从硬边界变成模型自律。**

`record_constraint` 只写 `pending` 草稿，不写版本、不扣费、不碰当前版本。用户确认之前，
`constraints(task)["effective"]` 里没有它，所以下一轮的 `edit_listing` 拿到的是空规则集——
即使模型误判成规则，也只是"这一轮没出图"，不会产出违反未确认规则的东西。

**2. 一句话里的多条请求。**

`PLAN_CONTRACT` 明说一次回复可以有多个 `tool_calls`。`record_constraint` 排在第一个，
其余照旧执行。离线 gateway 的 `scripted_plan` 按子句拆分来镜像这个行为（真实模型不需要）。

**3. 时间线上不再有"识别到新约束"这条独立反馈。**

`_record_constraint` 记录成功后，把该轮 Feedback 的 `interpretation` 改成
`new_constraint` 并挂上 `rule`，所以时间线仍然显示约束卡片和确认按钮——只是这个标签现在
是**结果**，不是**事前判断**。

## 顺带修掉的两个真实缺陷

- `_note_rejection` 只对**用户**说话，工具返回值是 `{"status": "ok"}`，模型以为成功了。
  现在拒绝原因进入工具结果（见 0045）。
- `operation`（`product_scale` / `remove_bg` / `upscale`）原来由 interpret 模型给。
  它其实是个关键词判断，现在由 `_operation_of` 在 `executor` 里做，不再需要模型。

## 验证

- `tests/test_intent.py` 重写：输出请求不产生规则；`以后/每次` 产生 pending；
  一句话既能记规则也能改；偏好句子变成 proposal；Composer 的 preference chip 生效。
- `tests/test_platform.py`：`llm_calls` 里不再有 `interpret` alias；
  `step` 事件里不再有"正在分析意图"。
