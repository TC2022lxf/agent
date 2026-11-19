# 2026-11-09 收尾上下文与视觉输入实测

对应 decisions/0041。目的：确认「出图后还在思考」和「模型说看不见图」不是模型能力问题。

环境：`GATEWAY=openai`，经 DMXAPI 中转。规划 `deepseek-v4.1-flash-1017`，
生图 `gemini-3.1-flash-lite-image`。

## 实验一：规划模型能不能看图

`scripts/probe_vision.py`：给一张 256×256 白底红圆，问形状和颜色。

```
probing vision on deepseek-v4.1-flash-1017
data: {'shape': 'circle', 'color': 'red'}
VISION OK
```

结论：能看。问题不在模型，在 `capabilities` 里没有 `vision`，所以运行时根本没发图。

## 实验二：修前 vs 修后，两轮对话

`scripts/probe_review_context.py`，同一任务连续两轮。

### 修前（planner capabilities = `["plan"]`）

```
--- turn 1: draw it
status: succeeded, versions: [...], steps: [generate_product_image]
answers: ["已生成纯白背景的电商主图，商品居中展示，无文字和水印。接下来可调整商品位置或局部细节。"]
follow_ups: ["把商品放大一些…", "优化商品边缘和材质细节…", "把图片尺寸改成800×800像素"]

--- turn 2: 这是一个什么剃须刀，你描述一下外观
answers: ["当前记录只有图片文件信息，没有可查看的画面，因此还无法判断剃须刀类型或描述外观。"]
asked: ["请上传这张剃须刀图片，让我根据实际画面描述它的类型和外观。"]
steps: [ask_question]
```

注意第一轮已经有 `answer`、没有多余提问，说明**收尾上下文那一处已经修好**；
但第二轮仍然答不出，因为它确实没收到图。

### 修后（planner capabilities = `["plan", "vision"]`）

```
--- turn 1: draw it
answers: ["已生成白底电商主图，剃须刀居中完整展示，无文字和水印。接下来可局部调整刀头细节或机身明暗。"]
asked: []
follow_ups: ["把刀头细节调清晰一点", "机身提亮一些，保留金属质感", "把主图改成正方形，剃须刀占画面八成"]

--- turn 2: 这是一个什么剃须刀，你描述一下外观
answers: ["从外观看，这是一款三刀头旋转式电动剃须刀：三个银色圆形刀网呈三角排列，
           机身以深灰和黑色为主，手柄细长、腰部略收窄，正面有纹理面板、圆形电源键和小圆点，
           底端可见接口，但图中没有可辨认的品牌或型号。…"]
asked: []
steps: []
```

## 结论

1. 收尾回复必须写进 `answer`。这一条与视觉无关，是「出图后还在思考」的主因。
2. 规划模型的 `capabilities` 要如实声明 `vision`，否则运行时按设计不发图。
   这一条不写进代码分支，写在模型档案里。
3. 两轮都没有出现「出图后又调 ask_question」：上一轮那个
   "What image should I make, and what product is it for?" 就是收尾请求只收到
   `{"phase": "after_tools"}` 的结果。补齐上下文后不再出现。
