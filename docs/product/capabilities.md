# 当前能力与边界

状态：源码现状基线，不代表产品已验收；核验日期：2026-11-19。
来源：[注册表](../../backend/app/agents/builtin.py)、[界面入口](../../frontend/src/App.tsx)、[占位界面](../../frontend/src/views/SimpleViews.tsx)。技术验证结果以[新报告](../releases/2026-11-19-baseline-verification.md)为准。

| 能力 | 实现状态 | 代码入口 | 验证/限制 |
| --- | --- | --- | --- |
| General 多类产物对话 | 已实现 | 注册表 general、runtime | fake 回归不能证明真实模型会正确选择工具 |
| Amazon PDP 分槽位编辑 | 已实现 | edit_listing、collab | 真实模型和 Playwright 已覆盖首稿与仅标题修订的技术关键路径；项目负责人已确认本轮审核通过并批准合并；长期文案质量口径仍待明确；不负责向 Amazon 上架 |
| 图像生成/区域编辑/测量/修复/变体 | 已实现 | image_tools、version_tools | 实际供应商效果、输出尺寸和费用待验证；不支持操作会拒绝 |
| Canvas 结构化布局与人工编辑 | 已实现 | domain/canvas、canvas_edits、CanvasView | screen/module/theme 模型，不是任意白板或已发布网站 |
| Canvas MCP | 已实现 | app/mcp/canvas_server.py | 独立 stdio 本地进程，身份/权限和数据位置需明确配置 |
| HTML/Markdown/表格文件 | 已实现 | file_tools、FilePanel | 版本化内容；不能据此声称可执行任意本机代码 |
| Web 搜索/获取工具 | 已实现 | web_tools | 真实模型已调用 web_search/web_fetch 获取公开 Amazon ASIN `B004YAVF8I`；供应商稳定性、配额和外部事实完整性仍需持续验证 |
| 约束/偏好与版本追踪 | 已实现 | collab、preferences、commit | 草稿确认后生效，拒绝版本不成为当前 |
| 会话/邀请/管理/审计 | 已实现 | auth_routes、identity | 默认 dev 模式仅本地开发；未完成独立安全审计 |
| 积分冻结/结算/人工充值 | 已实现 | credits、billing | 人工确认，不是已接入真实支付 |
| SSE、工具卡片与追问 | 已实现 | timeline、streaming、chat | 自动化断言之外仍需浏览器和人判断交互 |
| 定时/无人值守自动化 | 占位 | LaterView | 明确不算已交付；没有后台定时作业承诺 |
| 上线运维与规模保证 | 未验证 | 本地服务/存储实现 | 备份演练、压测、恢复和远程 CI 待实际执行 |

## 2026-11-19 真实数据技术验收

在用户明确授权下，本轮额外使用隔离测试数据库和公开 Amazon 页面执行真实模型 + Playwright 技术验收。General 任务完成 `web_search` 与 `web_fetch`；PDP 任务完成首稿和仅标题修订，观察到 5 条非空 bullets、非目标槽位版本不变、旧标题可查询。证据见[本轮报告](../releases/2026-11-19-baseline-verification.md)和 `docs/releases/evidence/`。

这证明两条关键路径在本次环境下可运行。项目负责人已确认本轮审核通过并批准合并，但其它能力实测、长期稳定性、合规、安全与部署验收仍分别保留。

## 不应混淆

- 产品 Agent 技能与本机编程 Agent 的 Superpowers 不是同一配置层。
- `design/` 有视觉原型，不说明所有交互已实现。
- 有测试不说明需求正确；本页确认的是“存在什么”，[需求](requirements.md)与[验收](acceptance.md)决定“应该做什么/如何接受”。
