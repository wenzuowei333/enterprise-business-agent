# 企业库存异常诊断与可靠 AI 工作流

面向 AI Agent 开发实习的脱敏展示候选版。**当前完成阶段二：源码范围整理、隔离配置、模型迁移和可重建合成数据。完整应用闭环尚未验收。**

保留库存异常确定性规则与证据契约；租约/领取/回写源码作为 `reference/` 片段保留，供阶段三解耦接入。此阶段没有可启动的 ERP API 或前端。

## 本地初始化

要求 Python 3.12 与 Docker Compose。从本候选目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock
docker compose up -d postgres --wait
.venv/bin/python demo/bootstrap.py
```

也可使用 `uv venv --python 3.12`，再用 `uv pip install -r backend/requirements.lock` 安装。

仅重建合成文件（不连接数据库）：

```sh
.venv/bin/python demo/bootstrap.py --export-only
```

默认数据库为独立的 `inventory_demo`，本机端口 `25432`；所有发布端口绑定 `127.0.0.1`。应用不自动读取 `.env`；`.env.example` 仅说明演示配置。外部模型/对象存储凭据为空，未连接生产环境。

停止本候选服务：`docker compose stop`。需要重建本候选数据卷时可执行 `docker compose down -v` 后重新初始化，该命令会删除本候选演示数据。

容器初始化入口：`docker compose --profile tools run --rm seed`（镜像构建与容器入口需与本机路径的验证范围分别记录）。

## 验证与范围

`demo/bootstrap.py` 执行迁移、幂等样本初始化和 `demo.verify_data`。检查模型/迁移一致、样本数量、预期值和素材；不等于完整 API、权限集成、队列并发或生产成功率验收。

详见 `docs/redaction.md`、`docs/demo-data.md`、`docs/adaptations.md`、`docs/version-scope.md`。阶段二完成后的执行证据见整理目录总报告。

演示密码公开且只适用于本地隔离环境。尚未发布到 GitHub。
