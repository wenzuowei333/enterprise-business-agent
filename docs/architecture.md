# 架构与关键时序

目标是让一条库存异常从可见范围、证据准备、诊断执行到结果落库都保留可检查的约束。页面只是入口；权限、来源版本和 Worker 归属由服务端决定。

```mermaid
flowchart TB
  UI["浏览器工作台"] --> API["FastAPI<br/>登录 / SQL 权限 / 规则复检"]
  API --> DB[("PostgreSQL<br/>任务 / 证据 / 诊断 / 事件")]
  DB --> W["独立 Worker<br/>领取 / 心跳 / 执行代次"]
  W --> P["Mock Provider<br/>字段投影 / 结构化解释"]
  P --> F["结果复核<br/>Schema / 引用 / 权限 / 证据版本"]
  F --> DB
  API --> UI
```

部署仅有 API、Worker、PostgreSQL 三类业务进程；不依赖 Redis。19 张展示模型表不代表原 ERP 全部表。页面轮询任务状态；证据、诊断、事件和通知在本地持久化。统一 CI 额外用内部网络与固定服务入口隔离运行，依赖安装仍可联网。

```mermaid
sequenceDiagram
  participant U as 页面
  participant A as API
  participant D as PostgreSQL
  participant W as Worker
  participant P as Mock Provider
  U->>A: 诊断请求 + 证据版本
  A->>D: 权限 / 规则复检 / 活动任务去重
  A-->>U: job_id
  W->>D: admission 锁 + SKIP LOCKED 领取
  D-->>W: owner + attempts 代次 + lease
  W->>D: 复核上下文 / 预算预留
  Note over W,D: 提交事务，Provider 调用期间不持有锁
  W->>P: 投影后的证据
  P-->>W: 结构化解释
  W->>D: 重新加锁并复核归属 / 租约 / 证据 / 权限
  alt 仍持有执行权且结果有效
    W->>D: 原子保存诊断 / 任务终态 / 事件 / 通知
  else 租约丢失或上下文失效
    W->>D: 拒绝旧结果或取消任务
  end
  U->>A: 查询状态与结果
  A-->>U: 当前可见结果
```

主要入口：[SQL 范围](../backend/app/services/access_control_service.py#L27)、[领取](../backend/app/services/source_task_functions.py#L72)、[调用前后复核](../backend/app/services/exception_task_service.py#L120)、[原子保存](../backend/app/services/source_task_functions.py#L223)。

字段投影不等于模型绝不会出错；Schema 合法也不证明根因正确。证据不足允许形成“缺口”结果，必须人工核实。当前全局 mutation/admission 锁简化固定锁顺序，也限制吞吐；没有容量测试结论。

源领取/落库符号与展示适配分别列在 [适配说明](phase3-adaptations.md)。外部 LLM、通用工具目录和生产 ERP 全量界面不属于当前部署图。

可导出图：[架构 SVG](assets/architecture.svg) · [关键时序 SVG](assets/sequence.svg)。Mermaid 源码保留在本页，便于后续维护。
