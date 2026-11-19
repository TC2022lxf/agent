# 测试策略、技术门禁与证据要求

状态：离线验证契约；核验日期：2026-11-19。来源：[pytest 配置](../../backend/pyproject.toml)、[前端命令](../../frontend/package.json)、[测试夹具](../../backend/tests/conftest.py)、[付费用例保护](../../backend/tests/test_live_gateway.py)。

## 验证分层

| 层 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| 后端 fake / in-memory 回归 | 规则、状态、API、权限、预算、版本与部分恢复约束 | 真实模型效果、真实网络重试、生产数据库和规模 |
| Vitest / jsdom | 组件、API 客户端、流式状态等已断言行为 | 真实浏览器布局/交互和完整服务链路 |
| typecheck / build | TypeScript 与打包可构建 | 产品可用性、性能、安全、无逻辑 bug |
| 生成参考/文档检查 | 当前覆盖、权限、链接、入口与旧引用 | 需求合理性、全文语义、外链可用性、人工体验 |
| 真实模型/供应商验证 | 指定 profile/输入/环境下的响应与质量 | 所有未来调用均正确；需要批准费用 |
| 浏览器/人工验收 | 用户可观察的流程、布局与产品预期 | 未操作场景或未经量化的性能保证 |

## 权威离线命令

PowerShell，从项目根目录进入 backend：

```powershell
cd backend
$env:GATEWAY="fake"
.\.venv\Scripts\python -m pytest -m "not live" -q
.\.venv\Scripts\python scripts/gen_docs.py --check
cd ..
.\backend\.venv\Scripts\python scripts/check_docs.py
```

生成资料需要更新时，在 backend 执行 `.\.venv\Scripts\python scripts/gen_docs.py`，然后重新 `--check`。生成命令不是测试通过的替代。

前端从根目录进入：

```powershell
cd frontend
npm ci
npm run typecheck
npm test
npm run build
```

Linux/CI 在 backend 先安装 `python -m pip install -e ".[dev]"`，将 Windows 虚拟环境命令替换为该环境的 `python`；前端命令相同。日常本地可复用依赖，但报告必须说明是否干净安装。

## 费用与数据隔离

**注册 live 标记不等于默认排除。** 直接运行 `pytest` 没有项目配置保证不调用真实供应商；即使测试会检查网关/key，也必须使用显式 `-m "not live"`。测试/CI 不带供应商 key，默认 fake 和独立内存数据。不得拿真实账户/上传文件做烟测。

需要 live 验证时单独获准，记录预算、profile、供应商、输入去敏、费用、超时与结果；不要把生产密钥写到报告。真实用户是否接受模型输出必须人工判断。

## 门禁与 CI

[工作流配置](../../.github/workflows/verify.yml)定义后端离线回归、生成/文档检查，以及前端锁文件安装、类型、测试和构建。配置存在不代表 GitHub 已执行成功；远程状态必须由实际 run 提供。

本轮没有锁定后端完整依赖图。Python 3.12 干净 CI 与本机已安装环境仍可能不同，相关差异需要新运行核验，不能复制本机绿色结果。

## 报告模板与验收责任

每次 `docs/releases/` 报告应包括：

1. 日期/时区、基线提交、未提交范围、环境/版本、安装方式及 fake/live 隔离。
2. 命令、cwd、退出码、实际通过/失败/排除数量及完整原始输出的本地位置或 CI run。
3. 失败/环境问题、处理方法、复测证据；不能靠删测试或更改口径变绿。
4. REQ/AC 与相关用例映射，人工复核步骤和缺陷。
5. 未执行项、接受风险的人、人工验收结论、是否批准发布。未执行不要写通过。

[产品验收](../product/acceptance.md)由负责人执行/确认；AI 技术验证报告只作为输入。[本轮报告](../releases/2026-11-19-baseline-verification.md)也遵循这个边界。
