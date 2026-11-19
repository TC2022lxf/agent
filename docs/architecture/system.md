# 系统架构与请求路径

状态：按源码整理的现状基线；核验日期：2026-11-19。来源：[应用工厂](../../backend/app/main.py)、[组合根](../../backend/app/container.py)、[前端壳](../../frontend/src/App.tsx)、[Worker](../../backend/app/runtime/worker.py)。

## 组件如何协作

```text
浏览器 React（导航/聊天/图片/Canvas/管理）
  └─ 同源 /api；本地由 Vite 代理至 FastAPI
       ├─ 声明式权限、CSRF、进程内限流
       ├─ API → UnitOfWork → 领域/服务 → SQLAlchemy 数据库
       ├─ 提交 utterance → 冻结预算 / queued Run
       │    └─ Worker → RunExecutor → LangGraphLoop
       │         ├─ Registry：Agent / Tool / Skill 权限与 schema
       │         ├─ Gateway：fake 或真实模型（经日志适配器）
       │         └─ 评估 / 版本提交 / 积分结算 / RunEvent
       └─ SSE + 产物/文件读取 → 浏览器展示

Canvas MCP stdio 进程 → 同一组服务 / 数据库 / 对象存储（不是浏览器代理）
```

组合根选择适配器。API 入队不应等待整轮模型执行；默认 `run_worker=inline` 启动 API 进程内线程，线程从数据库取 Run 执行。`off` 关闭自动 Worker，主要用于测试或显式接管执行；当前没有在本指南承诺一个现成的分布式 Worker 服务。

## 代码责任

| 区域 | 责任/不要做什么 |
| --- | --- |
| app/api | HTTP 声明、输入/错误/身份、序列化；不把模型 SDK 调用塞进路由 |
| app/services + persistence | 事务、任务/版本/账户/积分等协作规则和 ORM；通过 UoW 组织 |
| app/domain、evaluators、tools | 领域数据/规则、评估、工具 schema 与行为；不要越层直连数据库或供应商 |
| app/runtime | 单轮执行、上下文、工具调度、提交与结算；保证执行边界 |
| app/infrastructure | 模型、日志、对象存储适配；具体供应商在这里 |
| frontend/src/api、state、components、views | API 契约、导航/会话/任务状态、可交互工作台 |

层边界有[架构测试](../../backend/tests/test_architecture.py)约束。扩展方法见[扩展指南](../development/extension-guide.md)。

## 运行边界

- 本地默认 SQLite + 本地 blob 目录；配置 MySQL 可切换业务数据库，但 checkpoint 仍有本地文件策略。
- LangGraph checkpoint 与任务、Run、事件、对象文件是不同资料，恢复/备份必须一起考虑。
- 前端不是基于 URL 的完整路由系统，而以 NavState 切换视图；不能假设每个视图可独立深链。
- API 认证模块和核心模块都注册，参考[完整生成 API](../generated/api.md)。
- 限流在进程内，不是分布式全局限流；多实例调度/存储/锁与扩容没有被本轮证明。
- CORS 默认只允许本地前端地址；部署需要单独设计反向代理、Cookie 与 HTTPS。

这是一份现状图，不是未来架构承诺。数据不变量见[数据与契约](data-and-contracts.md)，失败和运行细节见[Agent runtime](agent-runtime.md)，部署约束见[运维手册](../operations/runbook.md)。
