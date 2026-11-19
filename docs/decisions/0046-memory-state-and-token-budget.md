# 0046 记忆：状态块 + 结构化回合 + 真实 token 触发

日期：2026-11-09

## 问题

跨 Run 的记忆只有一条通道：`runtime/context.py` 把历史回合渲染成中文行文本。三个具体缺陷：

1. **压缩触发用字符估算。** `len(text) // 3` 只数历史，不数 system prompt、`PLAN_CONTRACT`、
   `payload.view`（当前版本全文）和图片。一个带大文件的任务，可能实际已经 90% 窗口而估算说 40%。
   而真实数字就在库里：`llm_calls.tokens_in` 每轮都存着。
2. **结构丢了。** 工具调用、工具结果、被拒原因全部压成"助手：…"一句。于是"上一次主图被拒
   是因为边缘不够白"这条信息，下一轮完全不存在——而这正是 evaluator-optimizer 需要的。
3. **视觉只有当前版本。** `images_for_planner` 只取当前版本；用户说"上一版和这一版比一下"时，
   模型没有上一版可看。

## 决定

### 不换成 thread-scoped checkpoint

`create_agent` 的 checkpointer 存的是 **super-step 快照**，不是"消息历史存储"。
把 `thread_id` 从 `run_id` 改成 `task_id` 会同时打坏三件事：

- 第二次 `invoke` 变成"续跑同一线程"，新 payload 会**追加**在上一轮所有消息之后，要靠
  `RemoveMessage` 裁剪才可控；
- 崩溃恢复（`WorkerStopped` → requeue）会拿到整个 Task 的历史状态，而不是这一个 Run 的；
- 每轮一张全量快照，库体积随轮数平方增长。

真正值钱的是**结构化历史**，而它的渲染器在我们手里，不在 checkpointer 手里。所以在原基础上
优化，`thread_id = ctx.run_id` 保持不变。

### 四件改动

**1. 压缩用真实 token。** `should_compact` 取 `max(transcript 估算, 上次 plan 调用的 tokens_in)`。
只有第一次（还没有任何调用）和压缩之后才依赖估算。

**2. `TurnLine` 结构化。** 新增 `ToolLine(name, slot, status, detail)`；`render()` 多一行
`调用：edit_product_image(main_image) rejected: border white fraction 0.31`。
被拒版本的状态从 `Version.status` 反查，不是从文本猜。

**3. 视觉带上被编辑的基版本。** `LoopContext.target_version_id` 来自用户在 UI 里点选的那个版本；
`images_for_planner` 先取它，再取当前版本，上限 3 张。

**4. 每轮注入 `task_state` 块。** 由数据库实时生成，**不进压缩**：

```
当前状态（每轮由系统重新生成，不是对话内容）：
目标：…
类型：pdp
当前版本：title v2、main_image v1
已生效规则：标题不要超过 20 个字符
待确认规则（尚未生效，不要当成约束）：…
上一次被拒：main_image — border white fraction 0.31
```

摘要是一次有损改写，会被重新生成，也可能漏掉用户仍在依赖的约束；这个块不会。它回答的是
"这个任务现在的状态"——事实，不是对话。

## 验证

`tests/test_version_tools.py`：
- `TurnLine.tools` 里能看到 `edit_listing(title)`，`render()` 含"调用："；
- `task_state` 标出当前版本，且待确认规则明确写着"尚未生效"；
- `_last_prompt_tokens` 在 900k/1M 时越过 0.7 阈值（字符估算会判为不需要压缩）。
