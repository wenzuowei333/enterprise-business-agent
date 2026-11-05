> 历史部署模板：主机、组织标识已替换。完整脱敏版请使用根目录快速启动；此模板未连接或验证任何真实服务器。

# 异常中心三期暗部署与运维手册

## 发布边界

三期先以暗部署运行，再开放受控的人工 AI 诊断。定时 AI、全量扫描、摘要和自动修复保持关闭。异常中心诊断的模型调用只允许由专用 AI Worker 执行，确定性 Worker 和 Scheduler 均不得持有模型密钥。Web 继续保留现有业务模块所需的环境配置，本轮不改变其既有 AI 调用契约。

## 当前生产基线

当前运行时身份以 `deploy/exception-release-baseline.env` 为唯一来源：

- `EXCEPTION_RELEASE_SOURCE_SNAPSHOT`：生产源码来源标记。
- `EXCEPTION_RUNTIME_ALEMBIC_REVISION`：Dark、manual-ready 和 manual 验证的当前单一数据库 head。
- `EXCEPTION_STAGE3_HISTORY_START/TARGET`：仅用于最初三期发布的隔离迁移演练。

本文中出现的 `20260728_0400 -> 20260729_0500` 仅描述历史迁移演练，绝不能用于要求已升级生产数据库降级。当前生产 Dark 验收必须使用基线文件中的运行时 revision。

| 服务 | 系统身份 | 状态目录 | 环境白名单 |
|---|---|---|---|
| `enterprise-business-agent-exception-worker.service` | `handmade-exception-worker` | `/var/lib/enterprise-business-agent-exception-worker` | `/etc/enterprise-business-agent/exception-worker.env` |
| `enterprise-business-agent-exception-ai-worker.service` | `handmade-exception-ai` | `/var/lib/enterprise-business-agent-exception-ai-worker` | `/etc/enterprise-business-agent/exception-ai-worker.env` |
| `enterprise-business-agent-exception-scheduler.service` | `handmade-exception-scheduler` | `/var/lib/enterprise-business-agent-exception-scheduler` | `/etc/enterprise-business-agent/exception-scheduler.env` |
| `enterprise-business-agent-exception-observer-metrics.service` | `root:handmade-exception-observer` | `/run/enterprise-business-agent-exception-observer-metrics` | `/etc/enterprise-business-agent/exception-observer-metrics.env` |
| `enterprise-business-agent-exception-observer.service` | `handmade-exception-observer` | `/var/lib/enterprise-business-agent-exception-release` | 无；只读取 root 生成的标量文件 |

四个非 root 账号均为无登录 shell 的独立系统身份。应用根目录固定为 `handmade-exception-code:0710`；三个 Worker/Scheduler 和 observer 通过 `SupplementaryGroups=handmade-exception-code` 仅获得目录穿越权，代码内容仍保持只读。三个业务状态目录保持 `0700`；观察状态目录为 `0750`，证据文件为 `0640`。

数据库健康、累计数据库活动和主服务 journal 5xx 只能由 root 标量指标助手采集。该助手单独加入 `systemd-journal`，读取 root-only 的 `exception-observer-metrics.env`，网络限制为 localhost，并把不含连接串、日志正文或业务证据的标量 JSON 写入 `/run/enterprise-business-agent-exception-observer-metrics/latest.json`。运行目录为 `0750`，标量文件固定为 `root:handmade-exception-observer:0640`。非 root observer 不加载任何 `EnvironmentFile`，不属于 `systemd-journal`，不能读取数据库凭据、主 `.env` 或 journal，也不能修改 root 标量文件。

root 持有的环境白名单权限均为 `0600`。`.env`、`runtime`、上传、附件、报告、备份、`output`、`outputs`、`.git` 等敏感路径同时由 `InaccessiblePaths` 隔离，唯一可写位置是各服务明确声明的状态目录、运行目录和私有临时目录。

暗部署期间，`enterprise-business-agent-exception-observer.timer` 每五分钟启动非 root observer；其 `Requires` 依赖会先运行 root 标量指标助手。observer 校验标量文件的属主、权限、发布时间、发布身份和 Alembic revision 后，才把样本追加到 `/var/lib/enterprise-business-agent-exception-release/dark-observation.json`。证据文件由 `handmade-exception-observer` 持有且权限为 `0640`，不包含密钥、连接串、journal 正文或业务证据。

主 `.env` 必须为 `0600`，且所属用户不能是上述四个服务账号。不要把 `.env` 内容、数据库连接串、JWT 或模型密钥写入日志、工单和聊天记录。

## 开关矩阵

| 场景 | `EXCEPTION_AI_ENABLED` | 人工 AI 策略 | 定时 AI | 全量扫描 | 摘要 | 动作 |
|---|---:|---:|---:|---:|---:|---:|
| 暗部署 | 关 | 关 | 关 | 关 | 关 | 关 |
| 人工就绪 | 开 | 关 | 关 | 关 | 关 | 关 |
| 人工灰度 | 开 | 开 | 关 | 关 | 关 | 关 |

暗部署推荐参数：

```text
EXCEPTION_CENTER_ENABLED=true
EXCEPTION_AI_ENABLED=false
EXCEPTION_SCHEDULE_ENABLED=false
EXCEPTION_ACTIONS_ENABLED=false
EXCEPTION_AI_CONCURRENCY=1
EXCEPTION_MANUAL_AI_DAILY_LIMIT=20
EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true
EXCEPTION_SCHEDULED_AI_DAILY_LIMIT=0
EXCEPTION_SCHEDULED_AI_BATCH_SIZE=20
EXCEPTION_EVIDENCE_MAX_BYTES=32768
EXCEPTION_EVIDENCE_MAX_TOKENS=8000
EXCEPTION_RUNTIME_HEARTBEAT_SECONDS=30
EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS=150
```

AI Worker 的 systemd `TimeoutStopSec=180`，应用优雅停机时间必须小于该值并保留至少 5 秒安全余量；生产推荐固定为 `150` 秒。

执行发布前 canary 时，主 `.env` 必须已经配置最终灰度要使用的 HTTPS Provider 地址、模型和密钥，同时保持 `EXCEPTION_AI_ENABLED=false`、`EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true`。canary 命令只对自身进程临时开启 AI；从 canary 成功到人工就绪之间不得更换 Provider 地址、模型或密钥。确需更换时，应把旧 canary 视为失效，重跑 canary 后建立新的 dark 基线并重新观察。

迁移不会覆盖数据库中既有的 `exception_policy.ai_concurrency`。暗部署允许保留任意有效正整数；进入人工灰度前必须通过策略 API 将并发明确设置为 `1`。

## 发布前完整备份

备份必须发生在代码同步和数据库升级之前。先把本版本的备份脚本单独上传到服务器临时目录并审阅，然后执行：

```bash
sudo bash /tmp/create-exception-release-backup.sh \
  /opt/enterprise-business-agent /var/backups/enterprise-business-agent-releases
```

脚本只输出备份目录、旧代码版本、旧 Alembic revision 和清单摘要。把输出目录保存为 `RELEASE_BACKUP_DIR`，并在同步代码前从 root-only 备份中固定以下三项发布身份；后续命令必须复用这些值，禁止在同步后重新计算或手工改写：

```bash
export RELEASE_BACKUP_DIR=/var/backups/enterprise-business-agent-releases/<UTC时间>-<PID>
sudo test -f "${RELEASE_BACKUP_DIR}/SHA256SUMS"
sudo sh -c "cd '${RELEASE_BACKUP_DIR}' && sha256sum --check --quiet SHA256SUMS"
sudo pg_restore --list "${RELEASE_BACKUP_DIR}/database/postgresql.dump" >/dev/null

export EXPECTED_PREVIOUS_SOURCE_REVISION="$(
  sudo awk -F= '$1 == "SOURCE_REVISION" { print substr($0, index($0, "=") + 1) }' \
    "${RELEASE_BACKUP_DIR}/release-backup.env"
)"
export EXPECTED_PREVIOUS_ALEMBIC_REVISION="$(
  sudo awk -F= '$1 == "DATABASE_ALEMBIC_REVISION" { print substr($0, index($0, "=") + 1) }' \
    "${RELEASE_BACKUP_DIR}/release-backup.env"
)"
export EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256="$(
  sudo sha256sum "${RELEASE_BACKUP_DIR}/SHA256SUMS" | awk '{ print $1 }'
)"

test -n "${EXPECTED_PREVIOUS_SOURCE_REVISION}"
test "${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" = "20260728_0400"
test "${#EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256}" -eq 64
```

这三个值不是密钥，可以进入受控发布记录，但必须来自同一份同步前备份。演练、生产迁移和 installer 会把它们与 `release-backup.env`、`database/alembic-revision.txt` 和 `SHA256SUMS` 的实际 SHA-256 逐项核对；任一不一致都阻断发布。

一份合格备份必须同时包含：

- 格式版本为 `2` 的 `release-backup.env`，包含创建时间、源版本、数据库 Alembic revision、归档大小和数据库备份大小。
- 排除 `.env`、虚拟环境、依赖缓存、构建缓存、运行数据、上传、附件、报告、备份、`output` 和 `outputs` 后的代码归档 `code.tar.gz`。
- `code.tar.gz` 默认不得超过 256 MiB；必须拒绝任意路径中的 `*.dump`、`*.sql`、`*.xlsx`、`*.xls`、`*.csv` 及其 gzip 变体，不得靠改名或移动目录绕过业务数据隔离。
- PostgreSQL custom-format 备份 `database/postgresql.dump`。
- 权限为 `0600` 的 `.env` 副本。
- 主服务、三个异常服务、root 标量指标助手、observer 及 timer 的 effective unit、fragment、drop-in 和状态记录。
- 覆盖上述所有文件的 `SHA256SUMS`。

installer 强制要求显式传入 `RELEASE_BACKUP_DIR` 和三项同步前身份值，并在任何主机写入前复核清单、数据库备份、代码归档及其绑定关系；不能用 installer 自身的快速回滚快照替代这份完整备份。

将冻结候选归档解压到独立临时目录。候选必须包含由发布流水线写入的 `SOURCE_REVISION`，且不得复用正在运行的应用目录：

```bash
export CANDIDATE_ROOT=/tmp/enterprise-business-agent-release
test -f "${CANDIDATE_ROOT}/SOURCE_REVISION"
export EXPECTED_TARGET_SOURCE_REVISION="$(tr -d '\r\n' < "${CANDIDATE_ROOT}/SOURCE_REVISION")"
test -n "${EXPECTED_TARGET_SOURCE_REVISION}"
test "$(readlink -f "${CANDIDATE_ROOT}")" != /opt/enterprise-business-agent
```

演练脚本使用候选目录中的迁移代码和显式指定的生产虚拟环境，但只连接它自己创建的回环隔离数据库；候选目录内不得创建 `.venv` 副本或指向生产环境的符号链接。脚本固定设置 `PYTHONDONTWRITEBYTECODE=1`，不得在冻结候选中留下 `__pycache__`、`.pyc` 或 `.pyo`；受控同步脚本会再次检查并拒绝任何含这些缓存的候选。若候选被其他检查工具污染，必须从已校验的冻结归档重新解压到新目录，不得手工挑选缓存后继续发布。备份元数据中的原应用路径必须继续严格等于 `/opt/enterprise-business-agent`。候选路径与备份记录路径是两个独立身份，不能为了通过校验而把候选提前同步进生产目录。

## 发布前只读门禁

安装脚本在第一次写入主机前依次完成以下检查：

1. 参数、发布文件、Python 运行时和主 `.env` 权限。
2. 主 `.env` 必填开关、重复键和人工模式模型配置。
3. 三个异常 source unit、root 标量指标助手、非 root observer 和 timer 的身份、专用代码组、状态目录、环境文件、敏感路径及网络隔离规则。
4. 主服务、应用健康接口和数据库健康接口。
5. Alembic revision、默认策略和暗部署开关的只读数据库审计。

以上任一检查失败时，不创建用户、不写 `/etc`、不安装 unit。预检通过后，脚本先快照应用根目录原 group/mode、旧 allowlist、unit 以及 enabled/active 状态，再创建专用代码组、把应用根目录设置为 `0710` 并生成 root-only 白名单。安装检查使用 `runuser -G handmade-exception-code` 模拟 unit 的补充组，必须同时证明能读取运行代码、不能写应用根目录且不能读取主 `.env`。切换时先停止异常服务和 observer，安全重启 Web 并等待应用与数据库健康接口恢复，然后才启动异常服务进行预验收；预验收通过后才 enable，随后执行最终验收。

从首次写入开始，installer 会注册失败补偿。它还会读取 Web 当前进程中的四个异常中心总开关，生成只用于回滚的主 `.env` 副本，并快照原观察目录的属主、组、权限和既有观察证据。unit 解析、Web 重启、异常服务启动、预验收、enable、observer 初始化或最终验收任一步失败时，立即停止相关服务，恢复应用根目录原 group/mode、主开关、旧 allowlist、unit、enabled/active 状态和观察证据；若运行前不存在观察目录或证据，则删除本次新建内容。随后执行 `daemon-reload` 并重新验证 Web 健康。首次安装没有旧 unit 时会删除新 unit 并保持 stopped/disabled；仅删除本次 installer 新建的服务用户及其同名组，绝不删除预先存在的系统身份。本次新建的专用代码组也会删除。脚本会输出每个 unit 的回滚结果和 root-only 快照目录；该目录包含密钥，不得复制到日志或工单。

## 迁移演练

必须在生产 custom-format 备份恢复出的隔离数据库执行。脚本使用唯一的本机回环 PostgreSQL 角色和数据库，按退出陷阱清理现场，不打印密码或数据库 URL：

```bash
sudo env \
  EXPECTED_PREVIOUS_SOURCE_REVISION="${EXPECTED_PREVIOUS_SOURCE_REVISION}" \
  EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" \
  EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256="${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256}" \
  EXPECTED_TARGET_SOURCE_REVISION="${EXPECTED_TARGET_SOURCE_REVISION}" \
  EXPECTED_BACKUP_APP_ROOT=/opt/enterprise-business-agent \
  REHEARSAL_PYTHON=/opt/enterprise-business-agent/.venv/bin/python \
  bash "${CANDIDATE_ROOT}/deploy/rehearse-exception-stage3-migration.sh" \
  "${RELEASE_BACKUP_DIR}" "${CANDIDATE_ROOT}"
```

脚本使用 `pg_restore --no-owner --no-acl`，先明确确认备份起点为 `20260728_0400`，再执行并逐步校验 `20260728_0400 → 20260729_0500 → 20260728_0400 → 20260729_0500`。演练失败、清理失败或起点不是 `20260728_0400` 时均阻断发布。

核对事项：

- 0400 基线和往返结果按案件、通知、诊断、诊断任务、后台任务、事件、策略分别输出行数与 SHA-256/MD5 摘要，不输出业务内容。
- 诊断任务和后台任务的状态、`completed_at`、租约持有者及到期时间在往返后必须保持一致；迁移前存在同案件、同证据版本的重复活跃诊断任务时必须先人工对账，迁移不得静默取消其中任一任务。
- 既有 `ai_concurrency` 在首次升级、降级和重新升级后不变。
- 降级到 `20260728_0400` 后，二期已有的 occurrence 与 feedback 字段仍然存在且数据不变。
- 通知的 occurrence、archive 状态及事件历史在往返后保持一致。
- 降级前已配置的三期策略开关及限额临时保存在 `settings_json.migration_20260729_0500_policy`。
- 重新升级后恢复这些值并清理临时快照，不覆盖其他 `settings_json` 内容。
- `source_batch_kind` 与 `source_batch_id` 成对存在并按来源完成回填，两个批次索引均存在。
- `uq_exception_diagnosis_job_active_case_evidence` 必须是带谓词的唯一索引，阻止同一案件/证据出现多个 queued 或 processing 任务。
- 生产降级不能替代数据库备份，也不能用于清理诊断历史。

## 暗部署

以下步骤假设“发布前完整备份”已在旧代码、旧数据库状态完成。代码同步动作必须位于备份和迁移演练之后。只能使用受控同步脚本，不得手工拼接 `rsync` 参数。脚本固定保护 `.env`、`.venv`、`runtime`、`uploads`、`attachments`、`reports`、`backups`、`output`、`outputs`、Android 签名配置和 keystore，以及线上 APK 下载目录；禁止使用 `--delete-excluded`。`/var/backups` 位于同步目标之外，也不得改动。

`dry-run` 会输出完整 itemized 计划，并在标准错误输出其 SHA-256。必须把标准输出保存为计划文件，逐条审阅所有 `*deleting` 记录，然后使用该文件的 SHA-256 执行 `apply`。`apply` 会立即重算计划；任何文件变化都会使摘要不匹配并阻断同步：

```bash
# 当前 shell 必须继续持有“发布前完整备份”步骤固定的四个值。
: "${RELEASE_BACKUP_DIR:?missing pre-sync backup directory}"
: "${EXPECTED_PREVIOUS_SOURCE_REVISION:?missing pre-sync source revision}"
: "${EXPECTED_PREVIOUS_ALEMBIC_REVISION:?missing pre-sync Alembic revision}"
: "${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256:?missing pre-sync manifest digest}"
export CANDIDATE_ROOT=/tmp/enterprise-business-agent-release
: "${EXPECTED_TARGET_SOURCE_REVISION:?missing approved candidate source revision}"

set -o pipefail
export SYNC_PLAN_PATH="$(sudo mktemp /tmp/enterprise-business-agent-sync-plan.XXXXXX)"
sudo test -f "${SYNC_PLAN_PATH}"
test "$(sudo stat -c '%U:%G:%a' "${SYNC_PLAN_PATH}")" = "root:root:600"
sudo env \
  EXPECTED_TARGET_SOURCE_REVISION="${EXPECTED_TARGET_SOURCE_REVISION}" \
  bash "${CANDIDATE_ROOT}/deploy/sync-exception-stage3-release.sh" \
  dry-run "${CANDIDATE_ROOT}" /opt/enterprise-business-agent | sudo tee "${SYNC_PLAN_PATH}"

# 逐条审阅输出，特别是所有 *deleting 记录。
sudo cat "${SYNC_PLAN_PATH}"
export EXPECTED_SYNC_PLAN_SHA256="$(sudo sha256sum "${SYNC_PLAN_PATH}" | awk '{ print $1 }')"
test "${#EXPECTED_SYNC_PLAN_SHA256}" -eq 64

sudo env \
  EXPECTED_TARGET_SOURCE_REVISION="${EXPECTED_TARGET_SOURCE_REVISION}" \
  EXPECTED_SYNC_PLAN_SHA256="${EXPECTED_SYNC_PLAN_SHA256}" \
  bash "${CANDIDATE_ROOT}/deploy/sync-exception-stage3-release.sh" \
  apply "${CANDIDATE_ROOT}" /opt/enterprise-business-agent

cd /opt/enterprise-business-agent
chmod 600 .env
sudo grep -qx 'EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true' .env

test "${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" = "20260728_0400"
sudo env \
  EXPECTED_PREVIOUS_SOURCE_REVISION="${EXPECTED_PREVIOUS_SOURCE_REVISION}" \
  EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" \
  EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256="${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256}" \
  EXPECTED_TARGET_SOURCE_REVISION="${EXPECTED_TARGET_SOURCE_REVISION}" \
  bash deploy/apply-exception-stage3-migration.sh \
  /opt/enterprise-business-agent "${RELEASE_BACKUP_DIR}"

sudo systemctl start enterprise-business-agent.service
curl -fsS http://127.0.0.1:8082/api/v1/health >/dev/null
curl -fsS http://127.0.0.1:8082/api/v1/health/db >/dev/null

# 必须在 dark 基线建立前执行一次真实 Provider/JSON 契约 canary。
# 临时覆盖只作用于本进程，不改变主 .env、Web、Worker 或数据库策略。
(
  set +x
  cd /opt/enterprise-business-agent
  sudo env \
    EXCEPTION_AI_ENABLED=true \
    PYTHONPATH=/opt/enterprise-business-agent/backend \
    /opt/enterprise-business-agent/.venv/bin/python \
    /opt/enterprise-business-agent/scripts/run_exception_provider_canary.py
)

# 只有 canary 返回 0 后才能建立新的 DARK_SINCE。
sudo env \
  RELEASE_BACKUP_DIR="${RELEASE_BACKUP_DIR}" \
  EXPECTED_PREVIOUS_SOURCE_REVISION="${EXPECTED_PREVIOUS_SOURCE_REVISION}" \
  EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" \
  EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256="${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256}" \
  bash deploy/install-exception-services.sh \
  /opt/enterprise-business-agent /etc/systemd/system dark
```

canary 使用固定的合成脱敏库存证据直接调用正式 `call_hermes_exception_diagnosis`，不创建或修改异常案件、诊断任务或任何业务记录。每次即将发生的 Provider HTTP 请求都会先在 `audit_log` 写入 `exception_provider_call_started`，成功后只保存发布 SHA、模型标识、Prompt/JSON 契约版本、根因代码、校验布尔值、usage 数量和请求 ID 摘要；提示词、证据正文、响应正文、Provider 请求 ID 原文和密钥均不落盘、不输出。schema、支持的根因、canonical evidence reference、安全建议或完整 usage 任一不合格时，命令写入安全失败码并以非零退出。

这次 canary 必须先于随后 installer 创建的 `DARK_SINCE`。暗观察的累计 Provider 调用包含案件调用和 canary 的每次 HTTP attempt，因此观察期间再次运行 canary 会使“暗部署开始后 AI 调用为 0”门禁失败。canary 默认最大年龄为 `172800` 秒，可通过 `PROVIDER_CANARY_MAX_AGE_SECONDS` 或验证命令的 `--provider-canary-max-age-seconds` 下调，生产上限为 7 天。若 canary 过期或需要重跑，必须先重跑 canary，再重新执行 dark installer 建立新基线并重新完成整个观察窗口，不能沿用旧观察证据。

canary 同样计入香港自然日的 Provider 总调用额度。默认每日上限为 20；若当日 canary 实际发出一次 HTTP 请求，则当日最多只剩 19 次人工业务诊断。Provider 不支持 `response_format` 而触发兼容回退时，每次 HTTP attempt 都分别计数。

`apply-exception-stage3-migration.sh` 把生产起点固定为 `20260728_0400`，并再次核对备份中的 Alembic revision；它只接受已批准的旧/新代码版本对和备份清单摘要。包装器在迁移前停止所有已安装的确定性 Worker、AI Worker 和 Scheduler，要求诊断任务与后台任务均不存在 `processing` 状态或有效租约，升级至 `20260729_0500` 后再验证 revision。无论成功或失败，只恢复迁移前实际处于 active 的已安装服务；未安装的 AI Worker 等 unit 不会导致发布误失败。

installer 会记录重启前的 UTC 时间，以 root 初始化观察基线后交给非 root observer，并通过 root 标量指标助手和 observer 写入首个样本，再启用五分钟 timer。基线同时绑定当前部署代码/配置的 SHA-256 身份和目标 Alembic revision；观察期间任一可执行发布文件变化都会使最终门禁失败，必须重新初始化并重新观察。

暗部署必须同时满足连续不少于 8 小时、任意样本间隔不超过 15 分钟，并完整覆盖至少一个 `Asia/Hong_Kong` 周一至周五 `09:00–17:00` 工作窗口。夜间连续 8 小时不能代替工作时段验证；若当天在工作窗口之后开始暗部署，可跨夜保留观察，但最终必须等到下一个实际工作日 17:00 后。停机、重启或采样失败造成的缺口不能用事后补写替代。

观察期结束后读取证据文件中的基线时间并执行最终暗部署门禁：

```bash
DARK_SINCE="$(sudo /opt/enterprise-business-agent/.venv/bin/python -c \
  'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["deployed_at"])' \
  /var/lib/enterprise-business-agent-exception-release/dark-observation.json)"
sudo bash deploy/verify-exception-stage3.sh \
  --mode dark \
  --dark-since "${DARK_SINCE}" \
  --observation-file /var/lib/enterprise-business-agent-exception-release/dark-observation.json \
  --require-observation \
  --observation-min-hours 8 \
  --observation-max-gap-seconds 900
```

验收必须同时通过：

- 三个异常服务、root 标量指标助手、observer/timer 的隔离契约和三个心跳有效。
- 非 AI 账号不能读取主 `.env`。
- 四个服务账号均不能写代码目录。
- 非 AI 进程环境不含非空 `JWT_SECRET`、`INITIAL_ADMIN_*` 或 `HERMES_*`。
- 四个白名单均为 `root:root`、`0600`，且非 AI 白名单没有白名单外字段。
- 非 root observer 没有数据库环境或 journal 权限，只能读取且不能修改 `root:handmade-exception-observer:0640` 的最新标量文件。
- 暗部署开始后 AI 调用数和新增诊断任务数均为 `0`。
- 每个观察样本的 Web/DB 健康、三个服务心跳均有效，累计数据库活动、应用 5xx、重复任务和过期租约均满足暗部署门禁。
- 证据覆盖完整 8 小时，首个、末个及相邻样本间隔均不超过 15 分钟。
- 证据连续覆盖至少一个香港时区周一至周五 `09:00–17:00` 工作窗口，且发布身份和目标 revision 与基线完全一致。

## 切换人工灰度

人工灰度必须按以下顺序执行，不能颠倒：

1. 确认连续 8 小时且覆盖完整工作窗口的 dark 验收通过，定时 AI、全量扫描、摘要和动作均关闭。
2. 停止 observer timer。随后只把主 `.env` 的 `EXCEPTION_AI_ENABLED` 设置为 `true`，保持 canary 已验证的 HTTPS Provider 地址、模型、密钥和 `EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true` 不变；必须继续保持 schedule 和 actions 关闭。停止 observer 到完成 `manual-ready` 不得超过 15 分钟。
3. 此时数据库策略中的 `manual_ai_enabled` 必须仍为 `false`。运行 `manual-ready` installer。installer 会先强制启动一次 observer；其依赖的 root 标量指标助手重新统计整个暗部署期的数据库活动和 journal 5xx，形成最后一个样本。最后样本必须成功且距门禁执行时间不超过 60 秒，随后才会验证完整观察证据、空队列、无过期租约、无定时任务/调用、剩余人工预算，以及最近一次 canary 是否为同一发布 SHA、同一模型、同一 Prompt/JSON 契约、在当前 `DARK_SINCE` 前成功且未过期。只有这些条件全部满足，才启动已配置但不能领取任务的 AI Worker。不得用 timer 停止前的旧样本代替这次强制采样，也不得在现有 dark 窗口中临时重跑 canary。

```bash
sudo systemctl stop enterprise-business-agent-exception-observer.timer
sudo systemctl disable enterprise-business-agent-exception-observer.timer

sudo env \
  RELEASE_BACKUP_DIR="${RELEASE_BACKUP_DIR}" \
  EXPECTED_PREVIOUS_SOURCE_REVISION="${EXPECTED_PREVIOUS_SOURCE_REVISION}" \
  EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" \
  EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256="${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256}" \
  bash /opt/enterprise-business-agent/deploy/install-exception-services.sh \
  /opt/enterprise-business-agent /etc/systemd/system manual-ready
```

4. 通过正式策略 API 的部分更新 `PATCH` 只开启 `manual_ai_enabled`。策略更新使用 `updated_at` 做并发版本校验，因此必须先读取当前策略，再把最新版本作为 `expected_updated_at` 一并提交。不得直接改数据库，也不得用部分 `PUT` 覆盖整份策略。API 会把 `false → true` 的服务器时间和前后值写入 `audit_log`：

```bash
(
  set +x
  set -euo pipefail
  POLICY_URL='http://127.0.0.1:8082/api/v1/exception-policies'
  PYTHON='/opt/enterprise-business-agent/.venv/bin/python'

  POLICY_UPDATED_AT="$(
    curl -fsS \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      "${POLICY_URL}" |
      "${PYTHON}" -c 'import json, sys
value = json.load(sys.stdin).get("updated_at")
if not isinstance(value, str) or not value:
    raise SystemExit("policy response missing updated_at")
sys.stdout.write(value)'
  )"

  POLICY_UPDATED_AT="${POLICY_UPDATED_AT}" "${PYTHON}" -c 'import json, os, sys
json.dump(
    {"expected_updated_at": os.environ["POLICY_UPDATED_AT"], "manual_ai_enabled": True},
    sys.stdout,
    separators=(",", ":"),
)' |
    curl -fsS -X PATCH \
      -H "Authorization: Bearer ${ACCESS_TOKEN}" \
      -H 'Content-Type: application/json' \
      --data-binary @- \
      "${POLICY_URL}" \
      >/dev/null
)
```

该流程不打印策略响应、访问令牌或版本值，也不把响应写入磁盘。若 `PATCH` 返回 `409 exception_policy_version_conflict`，说明读取后已有其他管理员修改策略；必须从 `GET` 开始完整重试，不得复用旧的 `POLICY_UPDATED_AT`。

5. 在允许任何用户点击“智能诊断”之前执行最终 `manual` 门禁。门禁从服务器 `audit_log` 中读取最近一次 `manual_ai_enabled: false → true` 的权威时间，确认此后没有新任务和模型调用、当前队列为空、租约正常、定时能力关闭且人工预算仍有余额。`--transition-since` 仅可作为可选交叉核对标记，不能改变统计基线：

```bash
sudo bash /opt/enterprise-business-agent/deploy/verify-exception-stage3.sh \
  --mode manual \
  --observation-file /var/lib/enterprise-business-agent-exception-release/dark-observation.json \
  --require-observation \
  --observation-min-hours 8 \
  --observation-max-gap-seconds 900
```

只有上述命令成功后才能通知灰度用户。任何一步失败都要先停止 AI Worker，并通过相同的“重新 `GET` 最新 `updated_at`，再携带 `expected_updated_at` 执行 `PATCH`”流程把 `manual_ai_enabled` 恢复为 `false`；不得直接执行 SQL、手改 `/etc/enterprise-business-agent` 白名单或发送部分 PUT。

完成 20 个跨业务域灰度案例后，要求模型调用不超过每日 20 次、定时调用为 0、敏感字段外发为 0、重复调用为 0、业务数据写入为 0。

## Docker Compose 等价隔离

Compose 不再向三个异常服务注入整份 `.env`：

- 三个异常服务中仅 AI Worker 接收 `HERMES_*`；确定性 Worker 和 Scheduler 的模型端点及密钥被清空。Web 容器继续使用现有 `.env`，避免影响 CRM 等既有 AI 功能。
- 三个异常服务使用不同的非 root UID。
- 三个异常服务共享环境显式设置 `PYTHONPATH=/app`，因此从 `/var/lib/...` 工作目录启动仍能导入 `app`。
- 根文件系统只读，删除全部 Linux capabilities，并启用 `no-new-privileges`。
- 每个服务只拥有独立的内存临时状态目录和 `/tmp`。

上线前使用静默模式检查渲染结果，成功时不输出可能含密钥的配置：

```bash
docker compose config --quiet
```

运行后应在容器内只检查变量名，不打印变量值。

## 熔断与回滚

manual → dark 必须按以下顺序执行：

1. 紧急故障时立即执行 `sudo systemctl stop enterprise-business-agent-exception-ai-worker.service`，先停止新的模型调用；常规切换也可先停 AI Worker。
2. 通过正式策略 `PATCH` API 将 `manual_ai_enabled=false`，同时确认 `scheduled_ai_enabled=false`、`full_scan_enabled=false`、`digest_enabled=false`。API 不可用时保持 AI Worker 停止，不得使用 SQL 绕过审计。
3. 在主 `.env` 设置 `EXCEPTION_AI_ENABLED=false`，保持 schedule 和 actions 关闭。
4. 执行 dark installer。它会重启 Web、刷新三个服务白名单，并创建新的 UTC 观察基线：

```bash
sudo env \
  RELEASE_BACKUP_DIR="${RELEASE_BACKUP_DIR}" \
  EXPECTED_PREVIOUS_SOURCE_REVISION="${EXPECTED_PREVIOUS_SOURCE_REVISION}" \
  EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" \
  EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256="${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256}" \
  bash /opt/enterprise-business-agent/deploy/install-exception-services.sh \
  /opt/enterprise-business-agent /etc/systemd/system dark
```

任何发布步骤失败时 installer 会自动补偿。补偿会恢复运行前观察目录的属主、组、权限和既有 `dark-observation.json`；运行前没有这些对象时则删除本次新建的观察证据。它还会按逆序删除且仅删除本次运行创建的服务用户及其同名组，预先存在的系统身份必须保留。看到 `ROLLBACK complete` 后，按输出的快照目录核对恢复状态；看到 `ROLLBACK incomplete` 时必须保持 AI Worker 停止，并按快照中的 `service-state.txt`、`observation/root-metadata.txt` 和观察证据副本人工恢复，未查明原因前不得再次开放 manual。保留案件、证据、诊断、任务和事件历史。

代码回滚优先保留 `20260729_0500` 的加法结构；只有旧代码明确不兼容时才在变更审批后恢复数据库。旧 allowlist、unit、应用根目录 group/mode、服务状态和观察证据保存在 installer 输出的 `/var/backups/enterprise-business-agent-systemd/<UTC时间>-<PID>/`。首次安装回滚没有旧 unit，正确结果是新 unit 被删除、专用代码组及本次新建的服务身份被删除，应用根目录与观察目录恢复原 metadata，三个异常服务、root 标量指标助手、observer 和 timer 保持 stopped/disabled。

完整灾难恢复必须使用发布前备份，且按以下顺序操作：

1. 停止 Web、三个异常服务和 observer timer，确认没有运行中的导入或修复动作。
2. 在备份目录执行 `sha256sum --check SHA256SUMS` 和 `pg_restore --list database/postgresql.dump`。
3. 把 `code.tar.gz` 解压到独立暂存目录，核对归档根目录和版本后，再使用标准代码发布流程同步；不得直接在运行目录上解压。
4. 使用 `environment/application.env` 恢复 `.env` 时固定 `root` 或原应用用户持有、权限 `0600`。
5. unit 的 `.fragment`、`.dropin-*.conf` 和 `.effective` 用于恢复与比对；安装物理 fragment/drop-in 后执行 `systemctl daemon-reload`。
6. 只有代码与 `20260729_0500` 不兼容且获得数据库恢复批准时，才把 custom-format dump 恢复到新建的隔离数据库，完成一致性检查后切换连接；禁止对现有生产库直接执行带 `--clean` 的覆盖恢复。
7. 重启 Web 后依次验证 `/api/v1/health`、`/api/v1/health/db`、Alembic revision 和异常开关，再决定是否恢复确定性 Worker。AI Worker 必须保持停止，直至重新完成暗部署观察。
