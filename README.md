# Ecommerce AI：人与 Agent 共用的工作台

面向电商内容创作的协作应用：在同一任务中交流目标、生成与修改内容、查看版本和检查结果。包含通用对话、PDP 文案、图像和 Canvas 工作台。**定时自动化仍是占位，不是已交付能力。**

这个仓库本身也是人与编程 Agent 共用的 workspace：人通过文档定义工作并验证交付，Agent 依同一套契约实施，而不是维护另一套只有模型理解的说明。

## 从你的工作出发

| 我想做什么 | 从这里开始 |
| --- | --- |
| 理解产品、当前能力与限制 | [能力清单](docs/product/capabilities.md)、[候选需求](docs/product/requirements.md) |
| 给 AI 下任务并验收 | [协作流程](CONTRIBUTING.md)、[产品验收场景](docs/product/acceptance.md)、[需求追踪](docs/quality/traceability.md) |
| 启动、调试、修改代码 | [本地开发](docs/development/local-development.md)、[系统架构](docs/architecture/system.md) |
| 作为编程 Agent 开始工作 | [AGENTS.md](AGENTS.md)，再按任务阅读正文 |
| 查看本轮验证结果和待决问题 | [验证报告](docs/releases/2026-11-19-baseline-verification.md)、[探索与差距](docs/exploration/current-state.md) |
| 查找全部资料和权威来源 | [文档地图](docs/README.md) |

## 最短启动（Windows PowerShell）

需要 Python 3.12+、Node.js 22 / npm。以下命令从项目根目录开始；离线 fake 网关不需要模型密钥。

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
$env:GATEWAY="fake"
.\.venv\Scripts\python -m uvicorn app.main:create_app --factory --port 8000
```

另开终端，从项目根目录启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

打开 http://localhost:5173。默认开发身份不是生产登录方案；账户模式、配置和隔离要求见[开发指南](docs/development/local-development.md)。不应将开发服务直接暴露到公网。

## 仓库导航

- `backend/`：FastAPI、Agent runtime、领域与服务、测试和脚本。
- `frontend/`：React / TypeScript / Vite 工作台与组件测试。
- `skills/`：**产品运行时**技能及许可证，不是本机 Codex 设置。
- `fixtures/`：产品样例；`design/`：视觉原型。二者不是需求或验收的权威来源。
- `docs/`：共享产品、架构、开发、质量与运维契约。
- `scripts/`：workspace 维护工具；`.github/workflows/`：离线检查配置。

## 什么算完成

不是 AI 说“写好了”，也不是单看测试全绿。按[验收标准](docs/product/acceptance.md)检查用户目标，按[测试策略](docs/quality/test-strategy.md)复核技术证据，最后由人决定接受与发布。真实模型效果、性能、安全和产品人工验收未执行时必须显式保留。

状态：代码现状入口；核验日期：2026-11-19。本文不是产品验收签署。
