# 2026-11-19 文档重建验证报告

状态：文档重建、本地技术门禁和真实 Web/PDP 技术验收已完成；独立审查发现的 Critical 已修复，复审未发现阻断合并问题。**项目负责人已于 2026-11-19 确认最终产品验收通过并批准直接、最简合并；未执行能力仍保持未验证。**

## 1. 变更身份与环境

- 执行日期：2026-11-19，Asia/Shanghai；Windows / PowerShell。
- 基线提交：`c09f04ce5cab0243a30367ccb94d37a80ea6724d`。
- 分支：`codex/workspace-documentation-rebuild`。本报告记录审核前证据；项目负责人随后明确批准直接、最简合并，最终提交、远端 main 与 CI 状态以实际 Git/GitHub 结果为准。
- Python 3.13.9（复用 `backend/.venv`，非新建干净环境）；Node.js 22.14.0，npm 10.9.2。
- 后端 fake 门禁显式 `GATEWAY=fake`、`-m "not live"`；另经用户明确授权，使用隔离测试数据库、公开 Amazon 页面和已配置测试令牌执行一次性真实 Web/PDP 技术验收。没有使用真实用户数据，也没有读取或输出密钥。
- 前端使用锁文件重新执行 `npm ci --offline --no-audit --no-fund`，成功安装 179 个包；有一条既有 `whatwg-encoding@3.1.1` 弃用警告，不代表执行过依赖安全审计。
- 后端测试因沙箱临时目录/缓存权限限制，在获准的沙箱外执行；未通过删测试、关闭断言或调整选择机制规避问题。

## 2. 实际执行结果

以下命令使用项目虚拟环境解释器；PowerShell 完整写法及环境准备见[测试策略](../quality/test-strategy.md)。表内退出码均来自实际执行，不代表 GitHub 上运行过。

| 工作目录 | 命令 | 结果 | 退出码 |
| --- | --- | --- | --- |
| `backend/` | `python -m pytest -m "not live" -q`（`GATEWAY=fake`） | **346 passed, 7 deselected**，67.00 秒 | 0 |
| 项目根目录 | `python backend/scripts/gen_docs.py --check` | 六份生成资料与注册声明一致 | 0 |
| 项目根目录 | `python scripts/check_docs.py` | 必要入口、本地链接/锚点、自有代码失效引用检查通过 | 0 |
| `frontend/` | `npm ci --offline --no-audit --no-fund` | 179 packages，24 秒 | 0 |
| `frontend/` | `npm run typecheck` | TypeScript 类型检查通过 | 0 |
| `frontend/` | `npm test -- --run` | **14 test files / 112 tests passed**，8.28 秒 | 0 |
| `frontend/` | `npm run build` | Vite 生产构建完成 | 0 |
| 项目根目录 | `git -c core.autocrlf=false diff --check` | 已跟踪变更无空白错误 | 0 |

未将 7 个排除的 live 测试计入通过。前端组件测试及构建不等于真实模型质量或生产可用性证明。PDP 回归新增了 bullet 数量修复测试，以及外部 Task、不存在 Version、同 Task 错误 slot 的 base 边界测试；完整 fake 套件现为 346 passed；这不是产品能力新增 346 项。

### 真实模型与 Playwright 技术验收

| 场景 | 数据与操作 | 观察结果 | 证据 |
| --- | --- | --- | --- |
| Web 搜索/抓取 | General 任务搜索并抓取公开 Amazon ASIN `B004YAVF8I` | Run `run_1e59fb2ad90b` 为 `succeeded`；`web_search` 返回商品来源，`web_fetch` 对 Amazon PDP 返回 140 字符正文；成本 2 credits | [Web 结果](../releases/evidence/web-tool-results.json)、[截图](../releases/evidence/web-search-fetch.png) |
| PDP 首稿 | 使用公开商品事实生成标题、bullets、description、search terms | Run `run_6c18b7a037c9` 为 `succeeded`，成本 20 credits；四槽位完整；bullets 正好 5 条且非空；无既定禁用事实 | [PDP 结果](../releases/evidence/pdp-results.json)、[首稿截图](../releases/evidence/pdp-first-draft.png) |
| PDP 标题修订 | 只要求把标题精确改为 `Logitech M185 Wireless Mouse with USB Receiver` | Run `run_9ae5ab94d65b` 为 `succeeded`，成本 5 credits；标题产生新 Version；其它三个槽位 Version ID 与内容不变；旧标题仍可查询；版本历史可打开 | [PDP 结果](../releases/evidence/pdp-results.json)、[修订截图](../releases/evidence/pdp-title-revision.png)、[历史截图](../releases/evidence/pdp-version-history.png) |

本轮 live 技术验收合计 27 credits。首次真实 PDP 运行暴露了事件顺序和 bullets 数量问题；后续修复了模型请求约束、一次修复重试和空输出拒绝，并新增 `test_edit_listing_repairs_a_bullet_count_before_it_can_be_rejected`。独立复审前又修复了 planner 传入外部 Task Version ID 时的跨任务上下文风险，并要求显式 base 必须存在、属于当前 Task 且对应当前 slot，新增外部、未知和错 slot 三个回归用例。截图已由 Playwright 生成，但当前执行环境不能对图片做视觉读取，因此必须保留“待人工目视检查”，不能写成人工验收通过。

## 3. 文档工程证据

### 生成器与防漂移工具

- [生成器回归](../../backend/tests/test_documentation_generation.py)：先观察 7 个失败，再实现修复；与既有架构测试合跑 28 passed。最终完整套件包含这 7 个回归用例。
- API 参考覆盖当前应用 **79 个操作**（核心 55、认证/账号/管理/计费 24），比较实际 OpenAPI 集合，而非仅写死数量；权限保持 `public/user/admin` 原值。测试比较时规范化路径转换器，不改声明 URL 或业务路由。
- [workspace 检查器回归](../../backend/tests/test_workspace_documentation.py)：先观察缺少模块的 RED，再实现标准库检查器，46 passed。覆盖缺失入口、旧文件残留、链接/锚点与扫描边界；不联网检查外链，不宣称覆盖完整 Markdown 语法。
- [.github 工作流](../../.github/workflows/verify.yml)已用本机已有 YAML 解析器静态检查触发器、只读权限、fake 环境、显式 marker 和工作目录。**未推送，GitHub Actions 未执行**。

### 清理与非行为核对

- 按批准清单逐个删除 **9 个**旧人工文档/附件，不留 archive 副本，不改 Git 历史。没有删除运行数据、产品技能、fixtures、design、许可证或依赖锁文件。
- 旧引用清理通过 Python token/AST 和前端注释边界定位，不对产品 Prompt 或业务字符串批量替换。
- 65 个原有 Python 文件移除解释性 docstring 后 AST 与基线一致；19 个前端/配置文件注释外文本与基线一致。生成器与新增检查器/回归测试为本轮明确允许的功能性文档工具改动。
- `SKILL_DIR` 虽已进入设置，但组合根没有传入 registry；只记录为 [OPEN-08](../exploration/current-state.md)，没有借整理文档改变运行时。

## 4. 三条阅读路径演练（AI 结构核对，非人签收）

| 读者 | 从入口可定位的路径 | 核对结果 |
| --- | --- | --- |
| 产品负责人 | [README](../../README.md) → [能力清单](../product/capabilities.md) → [需求](../product/requirements.md) → [验收](../product/acceptance.md) | 能区分现有能力、占位功能和待确认目标；10 条 REQ / 10 条 AC 编号唯一；没有将重建方案批准冒充产品需求批准 |
| 开发者 | README → [系统架构](../architecture/system.md) → [本地开发](../development/local-development.md) → [测试策略](../quality/test-strategy.md) | 能找到代码分层、命令、fake/live 边界及扩展位置；测试用例名称已对照源码存在 |
| Agent | [AGENTS](../../AGENTS.md) → [贡献流程](../../CONTRIBUTING.md) → [追踪矩阵](../quality/traceability.md) → 本报告 | 能沿需求—AC—实现—测试—证据追踪，知道哪些决定须由人作出；不把绿灯写成人工验收或发布批准 |

抽样闭环：`REQ-COST-001` → `AC-COST-001` → `credits.py` / `billing.py` → `test_a_topup_moves_no_money_until_it_is_confirmed` 等真实用例 → 本轮 fake 套件结果。此链证明代码与断言可追溯；真实支付未集成、费用产品口径仍需人决定。其余领域的对应关系见追踪矩阵。

## 5. 独立审查

独立审查已给出首次实质结论：`backend/app/runtime/langgraph_loop.py` 的 `_fill_listing_context` 可能直接读取并发送其他 Task 的 Version 内容，属于合并前必须关闭的 Critical。现已新增显式 base 的 Task/slot 归属校验，在任何模型调用前拒绝不存在、跨 Task 或错 slot 的 Version，并记录零成本 ToolCall error；回归测试覆盖外部 Task Version 与未知 Version。该 Critical 已修复；原独立审查者复审确认 Critical 关闭，未发现阻断合并的问题。审查者建议的同 Task 错 slot 回归和文件末尾换行也已补齐。复审运行了 `tests/test_pdp_flow.py`（17 passed）及文档检查，但不替代作者运行的 full backend suite、远程 CI、live/browser 测试或产品人工验收。

作者收尾核对另发现启动示例仅以注释提示不覆盖 `.env`；现已在 README 与开发指南加入 `Test-Path` 守卫，并用隔离目录中的虚拟值验证首次复制及再次执行时保留现有值，没有读取或修改真实 `.env`。这属于文档命令安全性核对，不是独立审查结论。

## 6. 未验证与人的下一步

- 项目负责人已确认本轮最终产品验收结论为通过，并批准直接、最简合并；所有逆向整理的 REQ 仍保留逐项确认状态，未执行的能力验收不能据此写成通过。AI 没有自签产品验收。
- 已完成一次真实 Web/PDP 模型与浏览器技术验收；仍未执行图像真实效果、其它 Agent 质量、性能/负载、安全审计、生产迁移/恢复、备份还原或部署演练。
- 未执行 Python 3.12 的干净后端安装；本轮复用了 Python 3.13 环境。CI 指定 Python 3.12，后端依赖尚未锁定，未来干净安装与远程运行仍可能暴露差异。
- 默认开发身份、管理员初始化回退、固定本地 CORS、进程内限流及缺少完整数据库迁移等现状见[探索清单](../exploration/current-state.md)与[运维边界](../operations/runbook.md)，本轮未修复这些产品/运维问题。
- 四张截图已作为共享证据保留；本次会话没有逐图人工批注，且一次性 Playwright 脚本尚未纳入 CI。项目负责人仍对后续产品标准和未覆盖能力保留验收权。

## 7. 人工审核决定

项目负责人已确认本轮最终产品验收结论为**通过**，并授权直接、最简合并。完整记录见[人工审核记录](2026-11-19-human-review-record.md)。

## 8. 本地原始证据

可提交的共享证据位于 `docs/releases/evidence/`：Web/PDP 截图与脱敏 JSON 结果。原始运行目录 `.superpowers/sdd/2026-11-19-workspace-documentation-rebuild/live-evidence/` 仍保留数据库、日志和模型调用卷宗，但该目录被忽略，不随 Git 发布；其他克隆需按本报告复跑，不应把缺少本机日志误当为远程 CI 已验证。
