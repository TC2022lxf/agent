# 数据、协议与不可随意破坏的约束

状态：当前实现基线；核验日期：2026-11-19。
来源：[ORM](../../backend/app/persistence/models.py)、[协作服务](../../backend/app/services/collab.py)、[积分](../../backend/app/services/credits.py)、[声明与身份](../../backend/app/api/declare.py)、[前端契约](../../frontend/src/api/types.ts)。

## 领域关系

| 实体组 | 含义与关键关系 |
| --- | --- |
| Task / Product / Artifact / Version | 任务可绑定产品，持有按槽位或文件组织的产物；Version 保存内容与历史，current 是指针 |
| Feedback / Constraint / Evaluation | 输入与解释、待确认或有效规则、版本评估结果；评估拒绝与用户采纳是不同状态 |
| Run / RunEvent / ToolCall / LlmCall | 一轮执行、流式事件、工具及模型调用的可追踪记录，不把聊天文案当全部审计 |
| LedgerEntry / Balance / Topup | 追加积分账本、余额缓存、充值单；订单创建不等于入账 |
| User / Invite / Session / AuditLog | 账户、邀请、会话与管理审计，任务归属和角色限制访问 |
| Preference / PreferenceProposal / SkillRevision | 用户偏好及提案、产品技能修订；不覆盖原始代码当运行时编辑 |
| ModelProfile / AppSetting / ContextSummary | 模型能力、运营设置、历史摘要；不与真实模型效果证明混同 |

业务数据库之外还有对象字节和 checkpoint 文件。JSON 中的 object_key 指向存储，不保证只恢复数据库就能预览。字段类型和枚举以 ORM/前后端类型为准，不维护第二份完整字段列表。

## 业务不变量

1. 版本追加，不原地改写旧版本。恢复历史也创建新版本；不“回滚并删掉后来的历史”。
2. 评估被拒的版本不成为 current；目标槽位以外不能被顺手修改。
3. 服务检查 user/task 归属；Canvas base_version 过期要返回冲突，不能静默覆盖人的新编辑。
4. 约束确认前不生效；proposal、用户确认、版本通过三者不能混同。
5. utterance 必须带幂等键；重试不得重复扣费/追加相同产物，同任务活动 Run 受冲突限制。
6. 预算先冻结、实际结算/退款经账本；重复结算不能重复扣费。Topup pending 不入账，管理员确认后才增加积分。
7. SSE delta 为进度，终态回答和持久化事件/产物是复核依据；重连不能只靠内存 UI 片段重建事实。

自动化证据：[PDP](../../backend/tests/test_pdp_flow.py)、[Canvas](../../backend/tests/test_canvas.py)、[平台](../../backend/tests/test_platform.py)、[账户计费](../../backend/tests/test_auth_billing.py)。

## HTTP 与身份契约

[API 参考](../generated/api.md)按 method + path 列出 `public/user/admin` 与限流类别；不是完整请求/响应设计。运行中 `/openapi.json` 可查实际 schema；SSE 等流式内容及业务错误仍须结合[路由](../../backend/app/api/routes.py)、[认证路由](../../backend/app/api/auth_routes.py)与前端 API 读。

- `AUTH_MODE=dev` 允许开发身份头；不是生产鉴权。session 使用会话 cookie，cookie 鉴权写请求要求 CSRF 头。
- 管理员接口由声明层校验角色，不因前端隐藏按钮就安全。
- 错误采用 `error.code/message`；状态码包括认证/权限、余额不足、冲突和限流等，按具体声明与服务处理，不用“都返回 200”掩盖失败。
- RateLimiter 为单进程内存计数，多实例不共享。
- 本地浏览器通过 `/api` 代理；配置跨域/反向代理不能破坏 cookie、CSRF 或 SSE。

## 数据演进边界

[bootstrap](../../backend/app/persistence/bootstrap.py)创建缺表、补缺列，既有列类型变化/删除和可回滚迁移未被实现成版本化迁移系统。部署升级前必须先备份并在副本验证，不把启动成功当成迁移正确。恢复与未验证事项见[运维](../operations/runbook.md)。
