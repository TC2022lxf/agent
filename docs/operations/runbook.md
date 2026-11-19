# 运行、部署与恢复边界

状态：代码现状与部署检查单；不是经过演练的生产运维保证。核验日期：2026-11-19。
来源：[配置](../../backend/app/config.py)、[启动/管理员初始化](../../backend/app/main.py)、[UoW](../../backend/app/services/uow.py)、[数据库 bootstrap](../../backend/app/persistence/bootstrap.py)、[对象存储](../../backend/app/infrastructure/storage.py)、[checkpoint](../../backend/app/runtime/langgraph_loop.py)。

## 先确定部署目标

目前提供本地开发路径，没有一套已验证的容器、多实例、生产监控或发布自动化方案。上线前由人确认域名/TLS、身份模式、数据库/文件位置、模型预算和运营负责人。定时自动化/真实支付不在已交付范围。

## 身份与配置检查

- 生产不得沿用开发身份；评估 `AUTH_MODE=session`，拒绝依赖开发头绕过登录。
- HTTPS 下配置 Secure Cookie 并验证会话、CSRF、退出/吊销和跨域行为；`COOKIE_SECURE=true` 在无 HTTPS 本地测试下可能导致 cookie 不回传。
- 管理员 `ADMIN_NAME/ADMIN_KEY` 必须受控。当前 bootstrap 在没给管理员 key 时有不安全的默认值回退；不得用它上线，也不要把 key 写入文档/日志。
- 注册依赖邀请，首次管理员/邀请码初始化要在受控环境核验；日志可能含一次性邀请码，应限制访问。
- 当前 CORS 为固定本地白名单；没有一个已经实现的环境变量可任意改白名单。生产代理与源变更需单独评审/测试，不靠臆造配置项。
- 默认地址、初始积分和运营预算不是生产 SLA；密钥通过本地/部署秘密管理，不进入 Git。

## 数据、文件和 checkpoint

从 backend 目录启动时默认业务库是 `data/app.db`，对象数据在 `data/blobs`。SQLite 使用 WAL。LangGraph 对文件 SQLite 按数据库父目录存 `checkpoints.sqlite`；非此路径情形回退到当前目录 `data/checkpoints.sqlite`，因此切 MySQL 不意味着 checkpoint 自动存入 MySQL。

`RUN_WORKER=inline` 为 API 进程内线程；`off` 不会自己启动另一个 Worker。当前进程内限流与本地文件不构成多实例保证。

## 备份与恢复（执行前须另行确认）

以下是操作流程要求，不是已经执行的演练记录，也不是可以对生产直接运行的删除命令。

1. 记录代码/依赖版本、配置名（不含密钥）、数据库与 blob/checkpoint 的实际绝对位置及存储容量。
2. 选择维护窗口，停止新任务并确认运行中 Run 的处理；避免复制一半数据库与另一时刻文件造成失配。
3. 对 SQLite 使用一致性备份机制处理数据库及 WAL；不要假设热拷贝一个 `.db` 必定完整。MySQL 使用该部署经验证的一致性备份流程。
4. 同时保存对象存储与 checkpoint；备份访问权限、加密/保留和去敏由负责人决定。
5. 在独立目录/库恢复副本，用匹配代码和配置验证账户、余额/账本、任务/版本、文件预览与恢复执行。绝不覆盖原库试验。
6. 记录恢复耗时、数据缺口和批准者；满足人确认的恢复目标后才算演练通过。

数据库启动只会建缺表、补缺列；不能回滚类型变更或自动还原数据。发布回滚必须同时考虑代码与数据兼容，不只切换 Git 提交。

## 发布前与故障处理

先完成[技术门禁](../quality/test-strategy.md)和[产品验收](../product/acceptance.md)，检查真实 profile/供应商效果和成本、HTTPS/CORS/CSRF、备份恢复、失败取消及幂等。性能目标、容量、告警和灾备尚无验证基线，不能据“本地可运行”宣布生产就绪。

故障优先记录 trace/run ID、错误码、时间、操作与去敏日志；辨别余额/预算、供应商、配置、存储或平台故障，再按授权恢复。不在生产反复重放可能付费的请求；不打印模型 key、登录 key、会话或用户内容。当前待办见[探索](../exploration/current-state.md)。
