# 0041 回合收尾：把工具结果和图片还给模型

日期：2026-11-09

## 现象

一次运行已经生成了图片（Version 已提交、画布右侧已显示），对话却：

1. 仍然显示「正在思考」；
2. 模型在收尾回复里问 "What image should I make, and what product is it for?"；
3. 用户下一句问「这是一个什么剃须刀，你描述一下外观」，模型回答「无法从当前版本读出颜色」。

三个现象分别对应三处断点，都不是模型笨。

## 三处断点

### 1. 收尾回复被丢掉了

LangGraph 的 `create_agent` 在工具执行后会再问模型一次。这个文件当时写的是：

```python
if self.session is not None and '"phase": "after_tools"' not in user:
    self.session.note_plan(data)
```

也就是说：**工具调用之后那次模型回复，从不写进 `answer`**。于是「这张图画了什么」这句话模型说了，
但用户看不到；时间线上这一轮只有 Version、没有一句话，前端只在 `answer` 事件里渲染文字，
屏幕上就只剩「正在思考」。

修：新增 `note_review`。收尾回复就是这一轮的答复，要写进 `answer`。
`ask_question` 之后的收尾（模型只会说「完成」）和被拒版本的收尾除外：前者这一轮的话是问题卡片，
后者 `_note_rejection` 已经说了真正的原因，不能被一句「完成」盖掉。

### 2. 收尾请求没有上下文

那次请求的 user 消息只有 `{"phase": "after_tools"}`。模型知道「某个工具跑完了」，但不知道：
用户要的是什么、哪个工具跑的、返回了什么、产生了哪个 Version。所以它的回复只能是泛泛的
「你想让我做什么图」。

修：`_review_context` 从图状态里取出这三样（本轮 item 文本、最近几条工具返回、本轮 Version id）
放进 user 消息。这些信息一直在 messages 里，只是没往下传。

### 3. 模型看不见图

payload 里给的是 `object_key`，对模型来说那是一串文件名，不是图。所以「这是什么颜色」真的答不出。

修：`_Session.images_for_planner` 在 profile 声明 `vision` 时，把任务当前版本的图片字节取出来
（最长边压到 1024px）随请求发过去。`chat_json` 增加可选 `images` 参数；不传时请求体仍是纯字符串，
对所有中转站保持兼容。没有 `vision` 的 profile 不发图——发了只是烧 token。

### 实测

`scripts/probe_review_context.py` 在真实供应商上跑两轮（同一任务）：

- 第一轮「做一张纯白背景主图」→ `generate_product_image` 出图，`answer` 有句子，
  没有多余的 `ask_question`，生成 3 条追问建议。
- 第二轮「这是一个什么剃须刀，你描述一下外观」→ 模型答出「三刀头旋转式，三个银色圆形刀网
  呈三角排列，机身深灰与黑色，手柄细长、腰部略收窄，正面有纹理面板和圆形电源键」。

修之前第二轮的回答是「只有图片文件信息，没有可查看的画面」。差别只在 profile 有没有
`vision`。

`scripts/probe_vision.py` 单独验证了当前绑定的规划模型（`deepseek-v4.1-flash-1017`）
确实能看图：给一张白底红圆，它答 `{"shape": "circle", "color": "red"}`。
所以 seed 里规划器的 capabilities 改成 `["plan", "vision"]`；已存在的档案由
`_repair_planner_vision` 补一次，之后以档案里的值为准（operator 可以再删掉）。

## 关于流式

「模型还在思考」有三个互不相干的来源，只有第三个和流式有关：

1. 收尾回复被丢掉（本节标题 1）——这一轮有产出却没有字，前端只能显示「思考中」。
2. 前端把已经产出的 Version 也一起藏到 `pending` 后面。
3. 主回复本身是最后一个 SSE 事件才到达的。

第 3 点现在也修了：`chat_json` 支持 `on_delta`，适配器走 `stream: true`，
`_Session.note_delta` 把 JSON 里 `content` 字符串的当前进度抽出来，
写成 `answer_delta` 事件（带的是「到目前为止的全文」，不是片段，所以重连和迟到订阅都拿到完整值）。
`answer` 仍然是 Run 结束时的权威记录。

「思考中」这个状态本身不该取消：模型确实在思考。问题是**思考完了的话没有送到屏幕上**。

## 为什么不写成「生成完就禁止再调工具」

考虑过在 runtime 里硬拦：本轮已经有 Version 就不许再调 `ask_question`。
否决。这会变成针对某个模型某次行为的固定化补丁：用户确实可能在一张图之后立刻想改另一张，
那需要继续调工具。真正的问题是**收尾那一步没有被告诉发生了什么**，把上下文补齐，模型就不会瞎问。
提示词里另外把 `ask_question` 的触发/禁止条件写清楚（`docs/04` 的 `<when_to_ask>`），
这也是约束，不是代码补丁。
