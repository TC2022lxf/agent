# Human + Agent Workspace 文档重建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 删除误导模型的旧人工资料，建立人和 Agent 共用、可指引工作也可验证交付的文档体系及其防漂移检查。

**Architecture:** 不调整业务架构。以现有源码、配置、注册表和测试重建现状；需求意图、实现事实、执行证据、人工验收分别记录。修复 API 文档生成、清理失效引用并引入离线 CI，形成“人定义目标—AI 执行—证据复核—人决定接受”的共享工作闭环。

**Tech Stack:** 中文 Markdown；Python 3.12+ / pytest / 标准库；现有 FastAPI 注册表及 OpenAPI；React / TypeScript / Vite / Vitest；GitHub Actions（Python 3.12、Node.js 22）。不新增产品运行时依赖。

**Spec:** [已批准设计](../specs/2026-11-19-workspace-documentation-rebuild-design.md)，特别包括第 1.1 节“人与 Agent 共用 workspace”。

**Status:** 2026-11-19 用户已批准 Native 执行；Task 1–6 已完成，Task 7 本地验证与报告已完成，独立审查尚未获得有效结论，最终审查步骤未完成。

## Global Constraints

- 工作范围：`D:/lxf/ai_agent`，不修改其上级目录或系统级 Codex 配置。
- 用户已批准设计及直接执行；按批准边界重建，不扩大业务范围。
- 仅删除设计列出的九个旧人工文档/附件；不建 archive，不重写 Git 历史，不自动提交、推送或创建 PR。
- 保留源码、测试、产品技能、fixtures、design、许可证、运行数据库、上传文件、真实本地配置及依赖锁文件。
- 只允许文档、说明性引用、文档工具/测试、`.env.example` 和离线 CI 的必要改动；不得改变业务 API、认证策略、计费、UI、Prompt、工具权限、数据库结构和运行时技能加载。
- 不修改默认 pytest 选择机制；所有官方离线命令显式带 `-m "not live"`，不调用真实供应商，不访问真实用户数据。
- AI 不得把实现事实当作已确认需求，不得自签产品验收，不得将测试未执行、付费验证未执行或远程 CI 未运行写成通过。
- 文档以中文为主；代码标识符和命令保留原名；生成表格不手改；关键结论给出代码/测试来源。
- 本轮之前的测试数字是历史观察；最终报告必须根据重建后的新执行填写，并记录基线提交及工作树变更范围。
- 新增检查器使用 Python 标准库，无需网络。CI 干净安装不得携带供应商密钥，明确承认后端未锁依赖的可重复性局限。

## Review Focus

1. 缺少整个认证路由或未来新增路由时，生成文档可能仍自洽却不完整：Task 3 的 OpenAPI 集合相等及删除一条生成行的失败测试钉住此问题。
2. `public` 字符串为真导致权限误标：Task 3 逐接口断言三种权限原值，并核验管理员与公开接口。
3. 中文/重复标题、编码后的路径及代码围栏里的示例容易误报断链：Task 4 的 Unicode、重复锚点、百分号路径与围栏负例覆盖。
4. 文档工具可能误读依赖/示例或把真实 Prompt 当注释改写：Task 4 验证扫描边界，Task 5 比较 Python 非 docstring AST 和前端注释外文本，保证说明性改动不改变业务语义。
5. 绿色技术检查可能被当作产品验收：Task 1 的状态与责任矩阵、Task 7 的人工交付检查确保人工验收/发布均留待人决定，不自动变更需求批准状态。

## 文件责任与任务依赖

| 任务 | 创建/修改范围 | 独立交付物 |
| --- | --- | --- |
| 1 | README、AGENTS、CONTRIBUTING、docs 入口、product 三份文档 | 人与 Agent 都能使用的产品与工作契约 |
| 2 | architecture 三份、development 两份、quality 两份、operations 一份、exploration 一份、`.env.example` | 可追溯的现状、扩展、验证与运维正文 |
| 3 | 后端生成器、新增生成器回归测试、六份 generated 资料 | 完整且权限正确的机器参考 |
| 4 | 根 scripts/check_docs.py、后端文档工具测试 | 可离线执行的结构/断链/失效引用检查 |
| 5 | 明确清单删除、backend/frontend 注释及说明性引用 | 工作树不再残留误导资料与悬空来源 |
| 6 | `.github/workflows/verify.yml`、必要测试说明 | 干净环境的离线验证门禁 |
| 7 | releases 新基线报告、追踪矩阵与状态修订 | 能复核而非自报成功的交付包 |

依赖：1 → 2；3 在开始前复核现有注册与 API；4 在 1/2 的文档入口形成后实施；5 依赖 2/3/4；6 依赖 3/4/5；7 依赖全部任务。顺序执行即可，无须并行修改共享正文。

---

### Task 1: 建立人和 Agent 共用的产品与工作契约

**Files:**
- Modify: `README.md`
- Create: `AGENTS.md`, `CONTRIBUTING.md`, `docs/README.md`
- Create: `docs/product/requirements.md`, `docs/product/capabilities.md`, `docs/product/acceptance.md`

**Interfaces:**
- Consumes: 已批准设计；`backend/app/agents/builtin.py`、`frontend/src/App.tsx`、`frontend/src/views/SimpleViews.tsx`、现有测试。
- Produces: 稳定编号 `REQ-<DOMAIN>-NNN`、`AC-<DOMAIN>-NNN`；统一状态词及文档权威规则，供 Task 2/7 引用。

- [x] **Step 1: 从代码建立产品范围草表。** 覆盖 general/PDP/image/canvas、账户/权限、预算/积分、约束/版本、流式/失败恢复；automation 记为占位，不从菜单推导交付。每项记录代码来源、测试来源、实现状态、需求确认状态和未知问题。
- [x] **Step 2: 写需求与验收契约。** 每条需求含用户目标、范围/非目标、实现状态、确认状态；产品需求默认标为“根据现状反推，待产品负责人确认”，除非会话明确确认。每个验收场景含前置条件、操作、可观察预期、证据、fake/live/人工分类、人工结论栏；不填写伪造的签署。
- [x] **Step 3: 写三类阅读入口与共享闭环。** README 先回答“是什么/能做什么/怎么体验”，再链接产品验收、开发、Agent；`docs/README.md` 解释事实/意图/计划/证据的区别与权威来源。`AGENTS.md` 目标不超过 120 行，只写入口、边界、执行/证据要求；CONTRIBUTING 给人可执行的“提出变更→确认标准→实施→复核”流程。
- [x] **Step 4: 明确人的验收权与 AI 责任。** 人批准目标/范围/接受与发布；AI 提出影响、交付变更和复核证据。技术通过、人工验收、发布批准分列，不以本次设计批准替代产品需求确认。
- [x] **Step 5: 人工阅读验证。** 产品读者能只从 README 找到当前能力与验收；开发者能找到架构/命令入口；Agent 能找到边界。所有需求/验收编号唯一，正文有状态、核验日期和来源。不创建只填标题的空壳文档；暂未落地的跨任务链接在 Task 2 补齐后统一验证。

### Task 2: 按代码重建架构、开发、质量、探索与运维正文

**Files:**
- Create: `docs/architecture/system.md`, `docs/architecture/agent-runtime.md`, `docs/architecture/data-and-contracts.md`
- Create: `docs/development/local-development.md`, `docs/development/extension-guide.md`
- Create: `docs/quality/test-strategy.md`, `docs/quality/traceability.md`
- Create: `docs/operations/runbook.md`, `docs/exploration/current-state.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: Task 1 的编号/状态/职责；当前容器、配置、持久化、runtime、工具、前端 API、MCP 与测试代码。
- Produces: 唯一运行/测试命令正文；所有主干文档的来源索引；现状差距清单；Task 5 的旧引用→新正文映射。

- [x] **Step 1: 定向读取实现并建立证据索引。** 入口 `main.py/config.py/container.py`，Worker/执行器/LangGraph、上下文/版本提交/预算、ORM/bootstrap、auth/declaration、前端状态/API/SSE、Canvas MCP。记录用户行为到代码路径，不复制旧 ADR，也不从历史报告推断当前已验证。
- [x] **Step 2: 写系统与 runtime 设计。** 画一个能被人读懂的组件/请求流程；说明 API→队列/Worker→Run/工具→评估→版本→事件→UI、不同 Agent 及工具/技能权限、记忆压缩与失败恢复。把现有实现、保证边界与待验证边界分开。
- [x] **Step 3: 写数据与协议。** 使用 ORM/服务说明实体关系、状态与不变量、版本/幂等/预算/权限/CSRF/SSE；细目链接生成资料，不在多处复制完整端点表；人工充值确认不描述成已集成在线支付。
- [x] **Step 4: 写本地开发与扩展指南。** Windows PowerShell 作为主要命令；补充 CI/Linux 等价命令。Python 3.12+、Node.js 22；使用前端锁文件 `npm ci`。明确 `GATEWAY=fake`、真实模型额外授权、MCP 独立入口与运行环境。给新增 Agent/工具/技能/槽位/评估器的源码位置及必要测试，不改技能资产。
- [x] **Step 5: 写测试策略与追踪矩阵。** 命令显式 `pytest -m "not live"`，区分后端/组件/浏览器/供应商/人工；现有浏览器脚本不写成已自动纳入 CI。每条 REQ 映射 AC、实现、真实测试函数或前端用例和证据类型；没有覆盖即写“缺失/待补”，不是构造不存在的用例。
- [x] **Step 6: 写运维与配置。** 解释开发身份和 session 的切换、Secure Cookie/管理员初始化、CORS、数据库与 blob 存储的联合备份、启动补列的限制、手动恢复风险与发布前待验证项。在 `.env.example` 中说明 `AUTH_MODE/COOKIE_SECURE/ADMIN_NAME/ADMIN_KEY/SKILL_DIR`，保持默认离线可跑、不放凭据、不伪称默认配置可直接生产使用。
- [x] **Step 7: 写探索文档并校对正文。** 用“已观察事实/证据/未知问题/下一步验证/需人决定”组织，不保留旧故事。至少列出后端依赖未锁、真实模型效果、性能、安全审计、人工验收和远程 CI 尚待验证。按 Task 1 三类读者复读，并逐项核验矩阵引用的源码/测试确实存在。

### Task 3: 修复 API 参考的完整性与权限真实性

**Files:**
- Modify: `backend/scripts/gen_docs.py`
- Create: `backend/tests/test_documentation_generation.py`
- Regenerate: `docs/generated/api.md`, `agents.md`, `tools.md`, `skills.md`, `slots.md`, `evaluators.md`

**Interfaces:**
- Consumes: `app.api.routes.api.decls`、`app.api.auth_routes.router.decls`、`app.api.declare.Decl`；应用 OpenAPI。
- Produces: `collect_api_declarations(groups: Iterable[Iterable[Decl]]) -> tuple[Decl, ...]`，按 `(path, method)` 排序、重复 `(method, path)` 抛 `ValueError`；原 `api_md() -> str` 与命令行行为保持兼容。

- [x] **Step 1: 先写失败测试。** `test_api_reference_covers_every_openapi_operation`：用 fake/in-memory 容器创建应用，比较生成表格 `(method,path)` 集合与 `/api` OpenAPI 实际操作集合，忽略 HEAD/OPTIONS。`test_api_reference_preserves_auth_modes`：每行 auth 等于对应 Decl.auth，断言公开及管理员代表接口分别为 `public` 和 `admin`。不只断言固定数字 79。
- [x] **Step 2: 添加收集器边界测试。** `test_collect_api_declarations_rejects_duplicate_operation` 对同 method/path 的同值或冲突声明都断言 `ValueError`；`test_api_reference_detects_removed_auth_row` 删除生成结果中的 `/api/auth/login` 行后，集合校验必须不相等，证明校验能发现漏文档而非自洽即可。
- [x] **Step 3: 运行并确认失败。** 在 backend 执行 `.\.venv\Scripts\python -m pytest tests/test_documentation_generation.py -q -m "not live"`；期望明确暴露缺失认证端点、错误权限或尚未实现的收集器，而非环境异常。
- [x] **Step 4: 最小修复。** 收集两个路由模块并统一排序，权限直接渲染三种字符串；保持其他表格字段与注册表原样。生成模式确保输出目录可创建；`--check` 不写文件，缺失/过期结果返回 1。
- [x] **Step 5: 重新生成并验证。** 在 backend 运行 `python scripts/gen_docs.py`（使用项目虚拟环境解释器），再运行上述测试、`tests/test_architecture.py` 及 `python scripts/gen_docs.py --check`。期望全通过；人工复核没有手改注册表或虚构端点。

### Task 4: 建立离线文档与引用检查器

**Files:**
- Create: `scripts/check_docs.py`
- Create: `backend/tests/test_workspace_documentation.py`

**Interfaces:**
- Consumes: 项目根目录 Path；Task 1/2 文档职责清单；明确的旧资料清单。
- Produces: `Issue(path: str, line: int, message: str)`；`validate_workspace(root: Path) -> list[Issue]`；`main(argv: Sequence[str] | None = None) -> int`。
- CLI: `python scripts/check_docs.py [--root <path>]`；默认根目录由脚本路径确定，不依赖启动 cwd；成功打印摘要并返回 0，问题输出相对路径/行号并返回 1。

- [x] **Step 1: 先写结构与安全边界测试。** 临时最小 workspace 中验证缺失 README/AGENTS/主干文档、已删除旧文件仍存在时返回 Issue；验证从其他 cwd 调用结果相同。测试不依赖真实数据库、生产配置或外网。
- [x] **Step 2: 写断链与 Markdown 边界测试。** 覆盖行内/引用式链接与图片、缺失文件、相对链接、同文件/跨文件标题锚点、重复标题 `-1` 后缀、中文标题和百分号路径、源码 `#L数字`/`#L数字-L数字` 行范围；忽略围栏和行内代码中的演示链接、HTTP/mailto 外链而不发请求；拒绝越出工作区的本地文件链接。
- [x] **Step 3: 写失效引用与排除范围测试。** 对自有 Python 注释/docstring、TS/TSX/CSS 说明性注释中的 `docs/数字章节`、旧 `decisions/四位编号` 给出 Issue；不是对所有源代码字符串做替换。第三方依赖、构建/缓存、`.git`、运行数据、fixtures/design HTML、许可证不扫描。`docs/superpowers` 的删除清单/讨论文字不算失效引用，但其中真实 Markdown 链接照常检查；围栏代码中的夹具不误报。
- [x] **Step 4: 运行新测试确认 RED。** backend 执行 `.\.venv\Scripts\python -m pytest tests/test_workspace_documentation.py -q -m "not live"`；最初应因检查器不存在失败。
- [x] **Step 5: 实现最小标准库检查器，运行夹具测试 GREEN。** 不引入 Markdown/npm 包，不访问网络或密钥。将检查契约与支持的 Markdown 子集写入模块 docstring；无法识别的语法不能静默当作已验证的链接。对真实仓库运行此时允许报旧资料与引用错误，这些由 Task 5 消除，不跳过检查来伪造通过。

### Task 5: 精确删除旧资料并修复失效说明

**Files:**
- Delete: 设计 §3 明列的九个文件；不扩大为递归删除 docs 或其他数据。
- Modify: `backend/app/`、`backend/scripts/`、`backend/tests/`、`frontend/src/`、`frontend/vite.config.ts` 中实际含失效引用的自有注释/说明。
- Modify: 必要的新正文交叉链接；不改产品 Prompt、技能内容或业务表达式。

**Interfaces:**
- Consumes: 新文档及 Task 2 映射、Task 4 Issue 列表。
- Produces: 旧路径不存在、主干引用有效、业务语义不变的工作树。

- [x] **Step 1: 重新核对 Git 状态与删除边界。** 每个候选解析为绝对路径并确认位于项目 docs 下、属于已批准清单、没有用户新增改动。只逐个 `Remove-Item -LiteralPath` 删除文件；如有新用户变动则保留并报告，不强删。
- [x] **Step 2: 更新引用，不复制旧叙述。** 按含义链接 system/runtime/contracts/test-strategy 等新正文；无法证明仍有效的“见旧设计”改成现有实现的简短说明，不给旧 ADR 换个新编号继续保留。说明性引用改动不得改变字符串中的业务约束。
- [x] **Step 3: 证明非行为改动。** 比较基线与变更后 Python AST，去除解释性 docstring 后应一致，允许的例外仅 Task 3 生成器/新工具及测试；前端检查注释外文本一致。任何业务字符串、SQL、表达式、Prompt、JSX 文案变化都视为范围外问题并还原。脚本/验证采用临时审查工具，不引入产品依赖。
- [x] **Step 4: 运行文档工具回归。** 运行 Task 3/4 测试、根目录 `python scripts/check_docs.py`、生成器 `--check`。期望 exit 0，九个旧文件不存在，未产生 archive，也没有新正文链接回旧位置。

### Task 6: 加入离线 CI 并统一验证说明

**Files:**
- Create: `.github/workflows/verify.yml`
- Modify: `backend/pyproject.toml` 的错误注释、`backend/tests/test_live_gateway.py` 的错误说明（不改选择机制/测试行为）。
- Modify: 新开发/质量文档中与实际 CI 对应的说明。

**Interfaces:**
- Consumes: Task 3/4 CLI 与 Task 2 命令；既有 frontend/package-lock.json。
- Produces: push/pull_request 可触发的验证工作流，`permissions: contents: read`，不设置供应商凭据、不部署、不发布。

- [x] **Step 1: 配置后端 job。** Ubuntu + checkout/setup-python（3.12），从 backend 安装 `python -m pip install -e ".[dev]"`，运行 `python -m pytest -m "not live" -q`、生成器 `--check`、根文档检查。环境显式 `GATEWAY=fake`；不得加载生产 `.env` 或接入真实数据库。
- [x] **Step 2: 配置前端 job。** Node.js 22，working-directory frontend，依次 `npm ci`、`npm run typecheck`、`npm test`、`npm run build`。超时和依赖缓存可由实施者设定；不因缺少供应商密钥跳过技术检查。
- [x] **Step 3: 修正付费测试说明。** 只修正文中“已默认排除”的不实表述，明确直接 `pytest` 不由本项目配置保证排除 live；官方安全命令显式带 marker。`live`、`serial` 注册和实际测试不变。
- [x] **Step 4: 验证工作流与命令一致。** 用可用解析器解析 YAML，若环境无 YAML 包则不为此安装产品依赖，使用可用工具并明确静态检查边界；逐条核对 cwd、解释器、路径和输出检查。若干净环境依赖安装需要网络，按权限流程请求批准；不能把静态检查标成 GitHub 运行通过。

### Task 7: 新执行证据、人工复核与交付

**Files:**
- Create: `docs/releases/2026-11-19-baseline-verification.md`
- Update: `docs/quality/traceability.md`, `docs/exploration/current-state.md`、各新文档状态、本文进度。

**Interfaces:**
- Consumes: 全部新实现及新执行结果。
- Produces: 人能复跑、追溯和决定是否接受的验证报告；不生成假签名、假 tag 或假 CI 成功。

- [x] **Step 1: 记录运行环境与变更身份。** 日期/时区、OS、Python/Node/npm、基线提交、未提交范围、fake/live 隔离和是否干净安装；不在报告暴露绝对用户机密路径或环境密钥。
- [x] **Step 2: 执行完整本地门禁。** 后端离线全套、生成器 `--check`、文档检查；前端类型/测试/build。按实际结果填数量、失败/排除、退出码、命令、限制。遇权限错误先定位再按要求申请沙箱外重跑，不能把环境错误算作产品缺陷或自行删用例。
- [x] **Step 3: 人类可读性验收演练。** 从 README 分别走产品、开发、Agent 三条路径；定位一条需求、一项现状差距、一个源文件、一条真实测试、一个验收步骤和对应证据。将文档结构验收记录与产品人工验收分开，后者保持“待负责人执行/确认”。
- [x] **Step 4: 检查追踪与内容边界。** 每条需求有 AC 和实现/测试来源或显式缺口；报告中真实模型、安全/性能、GitHub CI、产品人工验收与发布未经执行不得写通过。确认没有旧材料副本、空文档冒充交付、重复且冲突的规范、删除范围外文件或密钥进入 diff。
- [ ] **Step 5: 最终审查与交付。** 审查 git diff/status；计划执行采用 Native 时在此做一次独立代码/文档审查，采用 Subagent-driven 时依相应技能逐任务审查并做整体验证。修复审查问题后重跑受影响门禁；报告完成/未完成/未验证，不自动提交或推送。

## 计划自检

- 设计覆盖：清理边界→Task 5；共享 workspace 与阅读规则→Task 1/2；生成器→Task 3；防漂移→Task 4/6；新证据与验收责任→Task 7。未发现无任务承接的设计要求。
- 接口一致：Task 3 的收集器只供 API 生成及测试；Task 4 的 CLI/返回码供 Task 5/6/7，所有检查从脚本位置确定根目录。
- Review Focus 五项均在所属任务中明确验证，人工产品验收不由自动化替代。
- 纯文档按来源核对和读者演练验证；可执行工具采用 RED/GREEN，不把写完文件等同验证通过。
- 本计划仅固定有影响的文件职责、边界、接口与断言，具体正文、图示、检查器内部实现及 CI 分组留给实施者，不添加产品功能。

## 执行方式记录

推荐 Native：由当前会话逐任务实施，保持主干文档、追踪编号和共享契约的一致性，最后安排一次独立整体审查。任务共享上下文较多，逐任务切换多个实现者会增加接口与表述协调成本。

用户也可选择 Subagent-driven：每任务独立实现/审查后再进入下一任务。无论选择哪种，都执行同一设计、验证门禁和人工验收边界。

用户已确认并要求直接执行；实际采用 Native：主会话连续实施，最后一次独立整体审查。上述推荐与替代方式保留为决策背景，不是新的待批准事项。
