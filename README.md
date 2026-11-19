# Ecommerce AI Agent

人和 Agent 协作的电商内容工作台，包含 FastAPI 后端、React 前端、Agent 技能、产品示例和设计资料。

## 项目结构

- `backend/`：Python 后端、Agent 运行时、API、脚本和测试。
- `frontend/`：React + TypeScript + Vite 前端及测试。
- `skills/`：项目使用的 Agent 技能及相关许可证。
- `fixtures/`：产品示例、图片及采集脚本。
- `docs/`：现有决策记录、实验记录和自动生成的接口资料。
- `design/`：设计稿和页面原型。
- `.env.example`：不含密钥的配置示例。

## 本地运行（Windows PowerShell）

需要 Python 3.12 或以上版本，以及支持项目 Vite 版本的 Node.js / npm。

在项目根目录按需复制配置：

```powershell
Copy-Item .env.example .env
```

启动后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn app.main:create_app --factory --port 8000
```

另开终端启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

浏览器打开 http://localhost:5173。默认 `GATEWAY=fake`，无需模型 API 密钥。使用真实模型时，在本地 `.env` 中配置服务地址、密钥和模型名称。

## 检查与测试

后端（在 `backend/` 内，使用已安装开发依赖的虚拟环境）：

```powershell
.\.venv\Scripts\python -m pytest -m "not live"
```

前端（在 `frontend/` 内）：

```powershell
npm run typecheck
npm test
npm run build
```

真实模型相关测试可能产生费用，不应在未确认配置时运行。

## 不纳入版本控制的内容

真实 `.env` 和密钥、虚拟环境、`node_modules`、构建产物、运行数据库、用户上传数据和缓存不上传。克隆后需要重新安装依赖；运行时数据会在本地生成。
