# 需求—验收—实现—测试—证据追踪

状态：现状追踪，不代表所有需求已确认；核验日期：2026-11-19。项目负责人已确认本轮审核通过并批准合并，所有产品 REQ 的逐项确认状态与未执行能力验收保持不变；PDP/Web 已增加一次性真实模型 + Playwright 技术观察。

人可沿此表核查 AI 的交付；Agent 必须更新受影响行，而不能只写“测试通过”。用例路径均为真实现有文件，具体函数可搜索下列名称；技术执行结果集中在[本轮报告](../releases/2026-11-19-baseline-verification.md)。

| REQ → AC | 实现来源 | 真实自动化证据（代表用例，不宣称完整覆盖） | 缺口/人工检查 |
| --- | --- | --- | --- |
| REQ-GEN-001 → AC-GEN-001 | [registry](../../backend/app/agents/builtin.py)、[file tools](../../backend/app/tools/file_tools.py) | [general 测试](../../backend/tests/test_general_task.py)：`test_same_task_can_hold_a_file_and_an_image`；[file 测试](../../backend/tests/test_file_artifacts.py)：`test_html_write_is_a_new_version_and_a_revision_does_not_overwrite` | 模型工具选择和浏览器产物体验待验 |
| REQ-PDP-001 → AC-PDP-001 | [collab](../../backend/app/services/collab.py)、[listing tool](../../backend/app/tools/edit_listing.py) | [PDP 测试](../../backend/tests/test_pdp_flow.py)：`test_feedback_creates_new_version_and_does_not_touch_other_slots`、`test_edit_listing_repairs_a_bullet_count_before_it_can_be_rejected`；[真实模型/Playwright 结果](../releases/evidence/pdp-results.json) | 本次技术关键路径已观察通过；项目负责人已确认本轮审核通过并批准合并；长期文案质量、逐图批注及产品阈值仍待后续明确 |
| REQ-IMG-001 → AC-IMG-001 | [image tools](../../backend/app/tools/image_tools.py) | [image flow](../../backend/tests/test_image_flow.py)：`test_standalone_image_edit_uses_edit_tool_and_bbox_prompt`、`test_product_scale_is_declined_not_faked` | fake 参数正确不等于真实局部编辑效果 |
| REQ-CAN-001 → AC-CAN-001 | [canvas edits](../../backend/app/services/canvas_edits.py)、[MCP](../../backend/app/mcp/canvas_server.py) | [canvas 测试](../../backend/tests/test_canvas.py)：`test_a_stale_base_is_refused`；[MCP 测试](../../backend/tests/test_canvas_mcp.py) | MCP 主机接入与浏览器拖动需独立演练 |
| REQ-RULE-001 → AC-RULE-001 | [collab](../../backend/app/services/collab.py)、[preferences](../../backend/app/services/preferences.py) | [PDP](../../backend/tests/test_pdp_flow.py)：`test_constraint_is_pending_until_confirmed_then_enforced`；[intent](../../backend/tests/test_intent.py)：`test_a_preference_sentence_becomes_a_proposal_not_a_rule` | 人确认文案与含糊意图尚需体验 |
| REQ-VER-001 → AC-VER-001 | [commit](../../backend/app/runtime/commit.py)、[version tools](../../backend/app/tools/version_tools.py) | [PDP](../../backend/tests/test_pdp_flow.py)：`test_hard_rule_failure_does_not_become_current`；[version tools 测试](../../backend/tests/test_version_tools.py)：`test_restoring_an_earlier_version_adds_a_new_one` | 界面恢复/可追溯性由人复核 |
| REQ-AUTH-001 → AC-AUTH-001 | [auth routes](../../backend/app/api/auth_routes.py)、[identity](../../backend/app/services/identity.py) | [auth billing](../../backend/tests/test_auth_billing.py)：`test_a_non_admin_cannot_reach_admin_routes`、`test_revoking_sessions_invalidates_the_cookie_immediately`、`test_cookie_writes_require_the_csrf_header`；[前端 Auth](../../frontend/src/Auth.test.tsx) | 生产 HTTPS/Cookie/安全审计未执行 |
| REQ-COST-001 → AC-COST-001 | [credits](../../backend/app/services/credits.py)、[billing](../../backend/app/services/billing.py) | [auth billing](../../backend/tests/test_auth_billing.py)：`test_a_topup_moves_no_money_until_it_is_confirmed`；[platform](../../backend/tests/test_platform.py)：`test_settling_the_same_run_twice_does_not_charge_twice`、`test_a_platform_fault_refunds_the_whole_hold` | 真实支付未集成，运营费用口径待确认 |
| REQ-RUN-001 → AC-RUN-001 | [executor](../../backend/app/runtime/executor.py)、[worker](../../backend/app/runtime/worker.py) | [platform](../../backend/tests/test_platform.py)：`test_idempotency_key_required_and_deduplicates`、`test_second_run_on_active_task_conflicts`、`test_cancel_queued_run_returns_hold`；[runtime](../../backend/tests/test_langgraph_runtime.py)：`test_resume_does_not_create_a_second_version` | 跨进程崩溃/供应商超时的真实恢复演练缺失 |
| REQ-UX-001 → AC-UX-001 | [timeline](../../backend/app/api/timeline.py)、[streaming](../../frontend/src/lib/streaming.ts) | [turn quality](../../backend/tests/test_turn_quality.py)：`test_reply_text_streams_before_the_run_ends`；[提问循环](../../backend/tests/test_ask_question_loop.py)：`test_a_question_ends_the_tool_loop_instead_of_exhausting_recursion`；[前端 App](../../frontend/src/App.test.tsx)；一次性 Playwright 截图见 `docs/releases/evidence/` | 浏览器重连、可访问性、视觉、实际等待体验和人工目视仍待验；一次性脚本未纳入 CI |

## 真实工具补充证据

- 真实 Web/Gateway：General Run `run_1e59fb2ad90b` 成功调用 `web_search` 和 `web_fetch`，公开 Amazon ASIN 为 `B004YAVF8I`；证据见[Web 结果](../releases/evidence/web-tool-results.json)。
- 真实 PDP：Run `run_6c18b7a037c9` 与 `run_9ae5ab94d65b` 均成功，标题精确修订且非目标槽位 Version 未变化；证据见[PDP 结果](../releases/evidence/pdp-results.json)。
- 这些是特定日期、模型、网络和输入下的一次性技术证据，不是所有模型、所有商品或长期稳定性的证明；项目负责人只对本轮合并审核作出通过决定。
## 文档工程自己的验收

生成器回归验证接口与权限覆盖；workspace 检查器验证入口/相对链接/锚点/旧资料引用。它们不验证以上产品承诺是否合理。新用例执行与人工检查记录在报告中；没有覆盖的真实模型、部署和人工事项保留为未验证。

## 变更时如何用

先读[REQ](../product/requirements.md)与[AC](../product/acceptance.md)；确定影响行、补缺失测试/人工步骤，再提交可复核证据。新需求需负责人确认，不因为矩阵填满就自动通过验收。
