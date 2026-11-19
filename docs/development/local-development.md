# 本地开发与安全验证环境

状态：源码对应的运行指南；核验日期：2026-11-19。来源：[项目依赖](../../backend/pyproject.toml)、[前端命令](../../frontend/package.json)、[配置](../../backend/app/config.py)、[代理](../../frontend/vite.config.ts)。

## 环境与首次安装

Python 3.12+，建议与 CI 的 3.12 对齐；Node.js 22 / npm。后端尚无锁文件，版本范围解析存在差异，不能承诺任意未来安装与本机完全相同。前端用 `npm ci` 遵循 package-lock。

从根目录开始（PowerShell）：

```powershell
# 仅首次复制；已有 .env 原样保留
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
$env:GATEWAY="fake"
.\.venv\Scripts\python -m uvicorn app.main:create_app --factory --port 8000
```

另一个终端从根目录运行：

```powershell
cd frontend
npm ci
npm run dev
```

前端 http://localhost:5173；后端 http://127.0.0.1:8000。`API_TARGET` 可调整 Vite 开发代理；改变浏览器源/CORS 需检查 Cookie。Linux 使用 `python3 -m venv .venv`、`.venv/bin/python` 替代 PowerShell 虚拟环境路径。

## 配置怎么生效

`load_dotenv` 从根 `.env` 再读 backend/.env，只补尚未存在的进程环境变量；进程已有值优先，后读文件不覆盖先前值。不要误以为改文件必定覆盖当前 shell。

- 默认 `GATEWAY=fake`、SQLite（从 backend 启动时位于 backend/data）与本地对象目录，不用供应商密钥。
- 需要不影响旧数据时设置独立 `DATABASE_URL`、`STORAGE_DIR`；不要用真实用户数据库验证。
- `MYSQL_HOST` 非空切换 MySQL，其余 MySQL 凭据从环境读；真实部署前见[运维](../operations/runbook.md)。
- `AUTH_MODE=dev` 是本机开发身份；`session` 才使用真实登录流程。管理员、邀请、Cookie 与 CSRF 不能靠随意加身份头验证。
- 模型 profile 也保存在库里，已有档案不等于每次启动都会完全被环境模型名覆盖；查看 profile 再判断配置是否生效。
- `SKILL_DIR` 字段已被解析，但组合根未用其切换注册表技能来源；当前技能仍从项目 `skills/` 加载，见[探索](../exploration/current-state.md)。

## 验证与付费边界

完整命令统一在[测试策略](../quality/test-strategy.md)。普通开发使用 fake 和 `-m "not live"`。没有显式排除时，配置了真实网关和 key 的环境可能触发付费测试。不要共享 `.env`、登录 key、会话或生产数据。

`scripts/smoke.py`、`verify_auth_ui.py` 等后端脚本针对运行中的服务/浏览器，不等于 pytest 自动执行的隔离用例。执行前读脚本，确认目标 URL、数据库、费用与额外工具依赖，本轮不默认运行它们。

## Canvas MCP

在 backend 的相同虚拟环境，以 `python -m app.mcp.canvas_server` 启动 stdio MCP。通过 `CANVAS_MCP_USER` 指定本地身份；默认开发身份不等于远程用户认证。必须确认它连接的数据库、文件路径与 HTTP 服务一致，尤其不要把开发客户端接入生产数据。服务范围与安全边界以[源码](../../backend/app/mcp/canvas_server.py)为准；本指南不要求修改本机 Codex 配置。

## 常见定位

先记录工作目录、环境变量优先级、实际 profile、版本与错误，再判断是配置还是产品缺陷。Windows pytest 临时目录权限错误与业务断言失败分开处理；使用获准的环境重跑，不删测试。后端数据、依赖、构建和缓存不纳入 Git。
