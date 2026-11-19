# 产品验收：用观察结果验证交付

状态：候选验收契约，待产品负责人逐项确认；真实模型 + Playwright 技术观察已执行。项目负责人已于 2026-11-19 确认本轮审核结论为通过并批准合并；未执行能力的验收状态保持不变。核验日期：2026-11-19。
来源：[候选需求](requirements.md)、[现有测试索引](../quality/traceability.md)。AI 可整理证据，不能在本页代签“通过”。

## 使用前提

先由人确认需求范围与下面的预期结果，再让 AI 实施；然后由人按步骤验证。使用独立测试数据库/文件目录、已知测试账户与足够测试积分。默认 fake 用于确定性流程；live 场景需另外批准费用和输入数据，不能对生产数据试验。2026-11-19 用户已明确授权一次真实模型与公开 Amazon 数据技术验收，详见下方观察记录。

## 验收场景

| 编号/需求 | 前置条件与操作 | 可观察预期 | 验证类型与证据 |
| --- | --- | --- | --- |
| AC-GEN-001 / REQ-GEN-001 | 新建 General 任务；写一份 Markdown，再在同一任务生成图片；读回前一文件 | 两类产物共存、历史与对话不丢失；文件内容可读 | fake 流程自动化 + 浏览器人工；任务/版本、截图 |
| AC-PDP-001 / REQ-PDP-001 | 建 PDP 并生成首稿；记录各槽位；只修改标题 | 标题产生新版本，非目标槽位不变；旧标题可查 | fake 回归 + 真实模型/Playwright 技术观察；前后版本 ID/内容、[PDP 结果](../releases/evidence/pdp-results.json)与截图；项目负责人已确认本轮审核通过并批准合并 |
| AC-IMG-001 / REQ-IMG-001 | 使用测试图片；圈选区域要求修改，再提出一个不支持的操作 | 选择正确基准和区域；不支持时明确拒绝、不伪造成功 | fake 验参数；真实效果需 live + 人工，当前未执行 |
| AC-CAN-001 / REQ-CAN-001 | 创建布局；修改一个模块；用旧 base_version 重放编辑 | 新版本保留非目标内容；旧基准请求被拒绝，不能覆盖新布局 | API/MCP 回归 + 浏览器人工；版本差异/冲突结果 |
| AC-RULE-001 / REQ-RULE-001 | 提交“以后每次…”规则；确认前后分别检查有效约束 | 先为 pending，确认后 effective；不因口头承诺就生效 | fake 回归；状态/API 与后续行为 |
| AC-VER-001 / REQ-VER-001 | 产生一个规则拒绝版本；恢复一个历史版本 | 拒绝不推进 current；恢复新增版本，历史仍在 | fake 回归；current 指针、版本链与评估 |
| AC-AUTH-001 / REQ-AUTH-001 | session 模式独立测试；用普通用户访问 admin，撤销会话再访问 | 普通用户被拒；失效会话不能继续用；cookie 写须 CSRF | 隔离 API/前端回归 + 人工；响应/会话，不记录密钥 |
| AC-COST-001 / REQ-COST-001 | 记录余额；创建充值但不确认；执行/失败一个 Run；最后由管理员确认充值 | 未确认不入账；冻结/结算/退款与账本一致；确认才入账且不重复 | 隔离回归；ledger、余额、Run，不使用真实付款 |
| AC-RUN-001 / REQ-RUN-001 | 相同幂等键重复提交；运行时再提交冲突请求；执行取消与恢复用例 | 不重复付费/版本；冲突可解释；终态/退款和恢复记录可追踪 | fake 回归；run/tool/version ID、终态与异常结果 |
| AC-UX-001 / REQ-UX-001 | 发起生成并观察进度；触发提问并回答；检查最终回答和产物 | 工具与文本可见；提问不会无限循环；最终记录与产物一致 | SSE/组件回归 + 浏览器人工；事件、界面截图 |

每项技术证据和尚缺的覆盖见[追踪矩阵](../quality/traceability.md)。没有执行的 live/浏览器项必须保留“未执行”，不能借 fake 结果填通过。

## 2026-11-19 真实数据技术观察（不是人工签收）

用户已明确授权使用 `backend/.env` 中配置的测试令牌；本轮只使用公开 Amazon 页面和隔离测试数据库，没有读取或输出密钥。应用账本记录 Web Run 2 credits、PDP 首稿 20 credits、标题修订 5 credits，合计 27 credits。

| AC/支撑 | 输入与操作 | 实际观察 | 证据 | 结论边界 |
| --- | --- | --- | --- | --- |
| AC-PDP-001 | 用公开 Amazon ASIN `B004YAVF8I` 准备 PDP；真实模型生成首稿；随后只要求把标题精确改为 `Logitech M185 Wireless Mouse with USB Receiver` | 首稿 Run `run_6c18b7a037c9`、标题修订 Run `run_9ae5ab94d65b` 均为 `succeeded`；四个槽位完整；bullets 正好 5 条且非空；无既定禁用事实；其它三个槽位 Version ID 不变；旧标题仍可查询；版本历史可打开 | [PDP 结果](../releases/evidence/pdp-results.json)、[首稿截图](../releases/evidence/pdp-first-draft.png)、[修订截图](../releases/evidence/pdp-title-revision.png)、[历史截图](../releases/evidence/pdp-version-history.png) | 技术关键路径通过；项目负责人已确认本轮审核通过并批准合并；长期文案质量与逐图人工批注仍未形成独立记录 |
| AC-PDP-001 / Web 支撑 | 同一公开商品执行联网搜索与 Amazon 页面抓取 | `web_search` 返回 Amazon 商品来源；`web_fetch` 对 `https://www.amazon.com/dp/B004YAVF8I` 返回 140 字符正文；Run `run_1e59fb2ad90b` 为 `succeeded` | [Web 结果](../releases/evidence/web-tool-results.json)、[Web 截图](../releases/evidence/web-search-fetch.png) | 证明本次网关联通和基本抽取；不证明长期稳定性、完整页面解析或外部事实完整性 |

## 人工验收记录

```text
需求/AC：本轮 workspace 文档重建、PDP 安全修复及 Web/PDP 技术证据审核
验收人、日期、代码/变更身份、环境：项目负责人，2026-11-19，Windows / PowerShell，分支 codex/workspace-documentation-rebuild
输入与步骤（去敏）：审核文档主干、REQ/AC、Critical 修复、346 项后端 fake 回归、112 项前端测试与真实 Web/PDP 证据
实际观察、证据位置：docs/releases/2026-11-19-baseline-verification.md 与 docs/releases/evidence/
结论：通过
缺陷、限制和复测条件：未执行能力继续按追踪矩阵保留；GitHub Actions 需由实际推送后的 run 证明
是否允许发布及负责人决定：允许直接、最简合并；本次不扩展为其它能力的验收结论
```

完整记录见[人工审核记录](../releases/2026-11-19-human-review-record.md)。

## 完成判定

技术门禁通过仅说明可进入人工验收；模型输出质量、产品预期与最终接受由人判断。具体性能/质量/成本阈值尚未确认，不能临时编一个数字并宣布达标。文档工程完成与产品所有场景验收通过是两件事。
