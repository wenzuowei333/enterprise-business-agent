# 阶段三：源机制与展示适配

本阶段在独立目录和新分支开发，保留阶段二提交作为父基线。没有改写源仓库，也没有把新增展示实现当作原生产实现。

## 源函数复用

`source_task_functions.py` 的 `utcnow`、`ExceptionRuntimePolicy`、`load_exception_runtime_policy`、`_obsolete_diagnosis_detail`、`_notification_recipients`、`_store_diagnosis`，以及 `provider_contract.py` 的两个元数据契约来自锁定源代码。原符号、行号、摘要和结构比对见 `source-provenance-phase3.json`。

`claim_diagnosis_job` 保留源 admission advisory 锁、有效租约计数、开关/策略、手动优先、`FOR UPDATE SKIP LOCKED`、领取与代次递增；改动为允许短演示租约，并新增 job_claimed 轨迹。`_lock_owned_diagnosis_context` 保留持有者/有效租约/代次/案件锁，新增拒绝未传代次。两函数明确标为适配版本。

证据字段白名单、输入投影、Canonical refs、Pydantic Schema 与危险建议检测已在阶段二按符号闭包抽取，继续实际使用；Mock 同样经过验证。原 `_store_diagnosis` 同一事务提交诊断、任务终态、案件状态、事件和通知。

## 新建或重写的展示适配

| 模块 | 改动 |
|---|---|
| auth_service / DemoSession | 新精简 Cookie 登录、哈希 session token、数据库撤销、CSRF、实时账号状态；新增 session 表并单独迁移，不冒充原完整身份 API。 |
| access_control_service | 按本版 warehouse 约定，基于保留的身份表做默认拒绝、权限覆盖、用户范围优先与 SQL 过滤；仓库取原库存快照，不信任客户端或旧案件元数据。 |
| exception_center_service | 适配原建任务锁定/去重/复用语义；重新读取已提交批次和快照，版本冲突拒绝，不暴露修改库存 API。保留原活动任务部分唯一索引。 |
| exception_task_service | 新执行外层围绕源领取/锁定/落库函数协调 Provider、预算、取消、超时重试和事件，不是原整个后台服务的逐字移植。 |
| heartbeat | 必须 owner + 代次 + processing + 尚未过期才能续约；比源片段增加过期租约拒绝，避免迟到心跳复活。 |
| diagnosis_provider | 新 Mock 传输与真实截止时间包装，5 类固定响应；没有 HTTP 模型调用，也不虚构 token 用量。 |
| main.py / backend/web | 新精简 API 与 HTML/CSS/JS 页面；角色切换实际登录，后端独立授权，textContent 渲染来源文本。 |
| tests / fault injection | 新 PostgreSQL 集成与进程故障测试；CLI 有限延迟注入用于本地复现，不是原生产配置。 |

## 运行边界

Worker 调用前后都重新核实请求者权限、来源和证据。无权限、来源缺失/未提交、证据变化、已结束案件或取消请求会终止任务。失效结果只记录拒绝事件，不能覆盖新诊断或终态。

每次执行在策略行锁下按 UTC 当日事件保守预留一次额度。进程崩溃后接管是另一次执行；预留次数不等同于真实收费，本版没有付费调用。未实现生产费用对账、完整监控、调度扫描或通用 Agent 工具目录。

全局 mutation/admission 锁保证本版固定锁顺序，但限制吞吐；未做容量压测。租约检查不代表外部 API 的严格一次执行或计费。
