# 0045 Evaluator-optimizer：把拒绝原因还给模型，并加三道闸

日期：2026-11-09

## 现象

`commit_output` 跑完规则评估器后，硬规则不过就把版本标成 `rejected`。然后：

- 给**用户**的话是 `_note_rejection` 写的（"这一版被规则拒绝：border white fraction 0.31…"）；
- 给**模型**的工具返回值是 `{"version_id": ..., "status": "ok"}`。

所以模型在整条链路上**一次都没见过那个数字**。它的下一步是"完成"，用户看到一张永远没
成为当前版本的图。花钱（20 积分）→ 被拒 → 用户再发一句 → 新一轮重新猜。

规则恰恰是可测量的：

```python
if white < cfg["background_border_fraction"]:
    problems.append(f"border white fraction {white:.2f}")
if occupancy < cfg["occupancy_min"]:
    problems.append(f"occupancy {occupancy:.2f} < {cfg['occupancy_min']}")
```

## 方案

`_commit_tail` 提交后调 `_after_commit(vid, slot)`：被拒则把结构化原因放进工具结果，
让模型**在同一轮**里修。

```json
{"version_id": "ver_…", "status": "rejected",
 "slot": "main_image",
 "problems": ["border white fraction 0.31", "occupancy 0.42 < 0.85"],
 "can_self_repair": true,
 "retries_left": 0}
```

### 三道闸（这是关键，否则就是无限重抽）

1. **次数**：`max_repairs = 1`。一个 Run 最多给一次修复机会。
2. **预算**：`_can_retry` 用剩余冻结额度比较一次绘制的成本；不够就不建议重试。
   重试的成本和第一次一样，超支冻结额比"让用户再问一次"更糟。
3. **可修性**：`_repairable` 只认 `border white fraction` 和 `occupancy`。
   `long side 800 < 1000` 是模型输出尺寸的属性，重画还是 800 —— 直接走用户提示路径。

三道闸都过了才 `retries_left: 1`；否则 `0`，并且 `_note_rejection` 立刻对用户说实话。

### 模型不说话时也有兜底

`finish_planning` 检查 `awaiting_repair`：给了修复机会、但这一轮结束时仍没有当前版本，
就由 Runtime 写出原因。这一条堵的是"模型拿到 rejected 后回一句'完成'"，那会让界面显示
成功而什么都没变。

## 与"确定性修复"的分工

`fix_image`（0046）能在**评估之前**把一部分拒绝变成通过：刷白背景、裁主体、按占比重排到
白底方图，PIL 几十毫秒，0 积分。所以正确的顺序是：

1. 模型自己先 `inspect_image` 看数字（预防）；
2. 发现要不过，先 `fix_image`（免费、确定）；
3. 还不过，才画第二张（付费、有不确定性）。

Evaluator-optimizer 是第 3 步的机制，不是第 2 步的替代。两者都在 `PLAN_CONTRACT` 里写明了。

## 验证

`tests/test_evaluator_optimizer.py`：
- 白边/占比可修、分辨率不可修；
- 混合问题只要有一条可修就值得试；
- `max_repairs` 默认 1；
- 预算检查确实读 `held` / `cost` / `max_calls`；
- 一条 400px 的图被判尺寸问题，给出的下一步里包含"提高输出分辨率"而不是重画。
