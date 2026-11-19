# 0043 Tool 执行卡片：先有"开始了"，才有卡片

日期：2026-11-09

## 现象

一张图要画 3 分钟。这 3 分钟里，对话区只有一行「正在生成图片」，之后什么都不变；
Run 结束后才出现一个折叠的 `<details>`，写着「3 个步骤 · 消耗 35 积分」。

于是**正在跑的调用和卡死的运行，在屏幕上完全一样**。用户没有任何依据判断它是否还活着，
只能等。而工具到底传了什么参数、花了多少钱、产出了哪个版本，要等整轮结束才看得到。

这不是前端样式问题。数据在 `tool_calls` 表里是齐的，但：

1. 那一行是在工具**跑完之后**才写的（`_commit_tail` → `_persist`）；
2. 时间线 API 只挑了 `tool`/`slot`/`ok`/`duration_ms`/`cost` 几个字段，
   把 `input`、`output` 和 `tool_call_id` 都丢了。

## 方案：一个事件 + 一个 id

### 1. `tool_started` 事件，在工具执行前写

`_Session._announce_tool` 在 `self.tools.call(...)` **之前**发一条 `tool_started`，
带 `tool_call_id`、`tool`、`slot`、`cost`，以及裁剪过的参数（只留 `slot`/`path`/`query`/
`url`/`prompt`/`instruction`/`operation`，字符串超 80 字截断）。

这个事件是**唯一在工具飞行期间存在的信号**。它和之后写的 `tool_calls` 行用同一个
`tool_call_id`（`f"{run_id}:{name}:{identity}"`，本来就是确定性的），所以前端能 upsert
成同一张卡，而不是画两行。

写入去重：同一个 `tool_call_id` 只写一次。worker 重入同一 step 时不应再画一张卡。

### 2. 时间线放出卡片需要的东西

`timeline.py` 的 step 增加 `tool_call_id`、`input`（裁剪后）、`output`，并新增
`tool_started` 列表（给结果还没落库的调用，以及崩溃后留下的"开始了但没记录"）。

剪裁在 `_brief`：长字符串保留头部并注明总长度（`…（共 1200 字符）`），列表最多 20 项，
嵌套最深 3 层。**不静默丢弃**——读者要能看出这里被截断了。

### 3. 前端合并成一张卡

`toolCards(started, steps)` 按 `tool_call_id` 合并：

- 只有 `tool_started` → `running`（转圈，显示"正在生成图片"）
- 有记录 → `ok` / `error`，带上真实耗时、成本、错误、`version_id`
- 记录优先于公告：它才是有真实耗时和产出的那个

顺序按"第一次出现"排，所以卡片的时间顺序是调用顺序，不是记录写入顺序。

`ask_question` **不画卡**：它有 `HumanInputPanel`（可点击的选项），再画一张卡等于把
同一个问题显示两遍。

## 卡片长什么样

```
✓  write_file  notes.md                     完成 · 0.4s · 0 积分
   内容  # 剃须刀 · 三个卖点（初稿）
   产生版本 · ee2a41
   ▸ 参数与返回
```

头部只有一行。参数摘要（写文件的正文首行、生图的 prompt、搜索的 query）放在第二行，
因为那是读者真正想知道的一句话。完整入参和返回值在折叠区里——`write_file` 的正文
不该铺在对话里，但"它到底发了什么"必须是点一下就有的。

## 实测

`scripts/probe_tool_card.py`（真实供应商，一张图）：

```
   5.73  tool_started  generate_product_image slot=image cost=20
  14.75  version_created
```

卡片在 5.73s 出现，版本 14.75s 才产生：**等待期间有 9 秒卡片在场**。
公告的 `tool_call_id` 与时间线记录的完全一致，一张卡而不是两行。

## 顺带修掉的既有 bug

造数据时发现：真实模型在 `ask_question` 之后会继续发 tool_call，图里 `awaiting_user`
只让 `_handle` 返回一句「已向用户提问」，并没有阻止下一轮规划，于是循环到
`recursion_limit: 25` 抛 `GraphRecursionError`，整轮 `failed`（还退回了冻结积分）。

修在模型侧：一旦 `session.awaiting_user`，后续 plan 返回的 tool_calls 全部丢弃，
以文本收尾。提问是这一轮的终点动作，不是循环的中间状态。
回归测试 `tests/test_ask_question_loop.py` 用一个"每次都说 ask_question"的假规划器钉住它。

## 不做的

- **不把 tool 卡片做成审批**。`WriteScopeGuard` 和预算拒绝是"拒绝执行"，不是
  "执行前问一句"。审批是另一个决定，需要把成本、写入边界和用户意图一起呈现。
- **不给 `web_search` 做来源卡片**。现在只显示 query 和条数；引用列表是独立的一次改动。
- **不把 reasoning 塞进卡片**。`reasoning_content` 目前被适配器丢掉了，那是另一条链路
  （见 `gateway_openai._chat_stream`），补它要改 profile、`llm_calls` 和 UI 三处。
