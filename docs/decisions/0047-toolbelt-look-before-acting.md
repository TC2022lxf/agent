# 0047 工具箱：先能看见，才谈得上改对

日期：2026-11-09

## 新增的七个工具

| 工具 | 积分 | 解决什么 |
| --- | --- | --- |
| `list_versions` | 0 | 版本历史在库里但没有工具能读，"用回第 2 版"只能重画 |
| `restore_version` | 0 | 回退写成一版**新**版本，不删历史、不调 vendor |
| `inspect_image` | 0 | 规则评测算出的数字只给用户看，模型从没见过 |
| `fix_image` | 0 | 白边/占比这两条规则可以用 PIL 修，不必花 15–20 积分重画 |
| `image_variants` | 15 | 图片任务要"三个方向"时，原来只能连画三张不相关的图 |
| `write_todos` | 0 | 多步任务用户只看到一行 step，不知道还剩什么 |
| `request_upload` | 0 | 需要图片时，`ask_question` 只给文本框，用户无法附图 |

`record_constraint` 见 0044。

## 两条设计约束

**1. 工具不碰数据库。** `list_versions` / `restore_version` / `inspect_image` / `fix_image`
需要的历史与 blob 由 `_Session._version_extras()` 收集后通过 `ToolContext.extras` 传入。
这是 `tools/base.py` 的既有契约，没有为新工具破例。

**2. 度量只有一份实现。** `app/domain/image_metrics.py` 同时服务于评估器、`inspect_image`
和 `fix_image`。三个地方各写一遍 `white_fraction` 的公式，必然漂移；而"模型被告知 0.31、
评估器算出 0.33"这种不一致比没有数字更糟。

## `fix_image` 的边界

它只做三件确定性的事：刷白背景（从四角 flood fill，只吃接近角落颜色的像素）、裁到主体、
按占比重排到白底方图（需要时补足最小边长）。它**不会**改变商品长什么样——
那是 `edit_product_image` 的事。

它也不假装能救所有图：一张背景复杂的实景照片，背景刷不白，`notes.improved` 就是 false，
模型应该去重画或请用户上传。报告里同时给出 before/after 两套数字。

## `image_variants` 的提交

一次调用画 2–4 张，每一张各自成为一个 Version（`params.variant_of` 指向同一个基版本），
第一张成为当前版本，并写一条 `variants_created` 事件。它们在一个事务里提交，避免出现
"画了三张只存了一张"的半成品。

## 验证

`tests/test_version_tools.py`（7 项）：测量值与评估器一致、措辞一致；
修复后白边/占比/最小边长同时达标且是方图；回合行带工具与状态；
状态块报告规则与版本；真实 token 触发压缩。
`tests/test_evaluator_optimizer.py`（5 项）：可修性判断与三道闸。
