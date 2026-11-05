#!/usr/bin/env bash
set -euo pipefail

MODE="dark"
APP_ROOT="/opt/enterprise-business-agent"
API_BASE="http://127.0.0.1:8082"
EXPECTED_REVISION=""
HEARTBEAT_MAX_AGE="120"
SKIP_SYSTEMD="false"
PREFLIGHT="false"
DARK_SINCE=""
TRANSITION_SINCE=""
ALLOW_DISABLED_EXCEPTION_SERVICES="false"
CODE_GROUP="handmade-exception-code"
OBSERVATION_FILE="/var/lib/enterprise-business-agent-exception-release/dark-observation.json"
INITIALIZE_OBSERVATION="false"
RECORD_OBSERVATION="false"
REQUIRE_OBSERVATION="false"
OBSERVATION_MIN_HOURS="8"
OBSERVATION_MAX_GAP_SECONDS="900"
OBSERVATION_LATEST_MAX_AGE_SECONDS="900"
PROVIDER_CANARY_MAX_AGE_SECONDS="${PROVIDER_CANARY_MAX_AGE_SECONDS:-172800}"
HTTP_5XX_COUNT=""
PRODUCTION_OBSERVATION_MIN_HOURS=8
PRODUCTION_OBSERVATION_MAX_GAP_SECONDS=900

usage() {
  cat <<'EOF'
Usage: verify-exception-stage3.sh [options]

Options:
  --mode dark|manual-ready|manual
                              Expected rollout mode (default: dark)
  --app-root PATH             Application root (default: /opt/enterprise-business-agent)
  --api-base URL              Internal health endpoint base
  --expected-revision VALUE   Required Alembic revision
  --heartbeat-max-age SEC     Maximum runtime heartbeat age
  --dark-since ISO8601        Assert zero model calls since dark deployment started
  --transition-since ISO8601  Optional operator marker; server policy audit remains authoritative
  --observation-file PATH     Root-only persistent dark-observation evidence
  --initialize-observation    Create a fresh observation baseline
  --record-observation        Append one health/queue/lease sample
  --require-observation       Enforce minimum duration and continuous clean samples
  --observation-min-hours N   Required observation duration; production minimum is 8
  --observation-max-gap-seconds SEC
                              Maximum gap between samples (default: 900)
  --observation-latest-max-age-seconds SEC
                              Maximum age of the final sample at this gate
  --provider-canary-max-age-seconds SEC
                              Maximum age of the matching pre-dark provider canary
  --http-5xx-count N          Cumulative application 5xx count for a recorded sample
  --skip-systemd              Skip systemd and HTTP checks (database audit only)
  --preflight                 Check config, migration, and policy before startup
  --allow-disabled-exception-services
                              Require exception services active but not yet enabled
  -h, --help                  Show this help

The command is read-only unless observation initialization or recording is explicitly
requested. It never prints environment values or credentials.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:?missing value for --mode}"
      shift 2
      ;;
    --app-root)
      APP_ROOT="${2:?missing value for --app-root}"
      shift 2
      ;;
    --api-base)
      API_BASE="${2:?missing value for --api-base}"
      shift 2
      ;;
    --expected-revision)
      EXPECTED_REVISION="${2:?missing value for --expected-revision}"
      shift 2
      ;;
    --heartbeat-max-age)
      HEARTBEAT_MAX_AGE="${2:?missing value for --heartbeat-max-age}"
      shift 2
      ;;
    --dark-since)
      DARK_SINCE="${2:?missing value for --dark-since}"
      shift 2
      ;;
    --transition-since)
      TRANSITION_SINCE="${2:?missing value for --transition-since}"
      shift 2
      ;;
    --observation-file)
      OBSERVATION_FILE="${2:?missing value for --observation-file}"
      shift 2
      ;;
    --initialize-observation)
      INITIALIZE_OBSERVATION="true"
      shift
      ;;
    --record-observation)
      RECORD_OBSERVATION="true"
      shift
      ;;
    --require-observation)
      REQUIRE_OBSERVATION="true"
      shift
      ;;
    --observation-min-hours)
      OBSERVATION_MIN_HOURS="${2:?missing value for --observation-min-hours}"
      shift 2
      ;;
    --observation-max-gap-seconds)
      OBSERVATION_MAX_GAP_SECONDS="${2:?missing value for --observation-max-gap-seconds}"
      shift 2
      ;;
    --observation-latest-max-age-seconds)
      OBSERVATION_LATEST_MAX_AGE_SECONDS="${2:?missing value for --observation-latest-max-age-seconds}"
      shift 2
      ;;
    --provider-canary-max-age-seconds)
      PROVIDER_CANARY_MAX_AGE_SECONDS="${2:?missing value for --provider-canary-max-age-seconds}"
      shift 2
      ;;
    --http-5xx-count)
      HTTP_5XX_COUNT="${2:?missing value for --http-5xx-count}"
      shift 2
      ;;
    --skip-systemd)
      SKIP_SYSTEMD="true"
      shift
      ;;
    --preflight)
      PREFLIGHT="true"
      SKIP_SYSTEMD="true"
      shift
      ;;
    --allow-disabled-exception-services)
      ALLOW_DISABLED_EXCEPTION_SERVICES="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "${MODE}" != "dark" && "${MODE}" != "manual-ready" && "${MODE}" != "manual" ]]; then
  echo "--mode must be dark, manual-ready, or manual" >&2
  exit 2
fi
if ! [[ "${HEARTBEAT_MAX_AGE}" =~ ^[0-9]+$ ]] || (( HEARTBEAT_MAX_AGE < 30 )); then
  echo "--heartbeat-max-age must be an integer of at least 30" >&2
  exit 2
fi
if ! [[ "${OBSERVATION_MIN_HOURS}" =~ ^[0-9]+([.][0-9]+)?$ ]] \
  || ! awk -v value="${OBSERVATION_MIN_HOURS}" -v minimum="${PRODUCTION_OBSERVATION_MIN_HOURS}" \
    'BEGIN { exit !(value >= minimum) }'; then
  echo "--observation-min-hours cannot be lower than ${PRODUCTION_OBSERVATION_MIN_HOURS} in production" >&2
  exit 2
fi
if ! [[ "${OBSERVATION_MAX_GAP_SECONDS}" =~ ^[0-9]+$ ]] \
  || (( OBSERVATION_MAX_GAP_SECONDS < 60 \
    || OBSERVATION_MAX_GAP_SECONDS > PRODUCTION_OBSERVATION_MAX_GAP_SECONDS )); then
  echo "--observation-max-gap-seconds must be between 60 and ${PRODUCTION_OBSERVATION_MAX_GAP_SECONDS}" >&2
  exit 2
fi
if ! [[ "${OBSERVATION_LATEST_MAX_AGE_SECONDS}" =~ ^[0-9]+$ ]] \
  || (( OBSERVATION_LATEST_MAX_AGE_SECONDS < 1 \
    || OBSERVATION_LATEST_MAX_AGE_SECONDS > OBSERVATION_MAX_GAP_SECONDS )); then
  echo "--observation-latest-max-age-seconds must be between 1 and the gap limit" >&2
  exit 2
fi
if ! [[ "${PROVIDER_CANARY_MAX_AGE_SECONDS}" =~ ^[1-9][0-9]*$ ]] \
  || (( PROVIDER_CANARY_MAX_AGE_SECONDS > 604800 )); then
  echo "--provider-canary-max-age-seconds must be between 1 and 604800" >&2
  exit 2
fi
if [[ "${INITIALIZE_OBSERVATION}" == "true" && "${RECORD_OBSERVATION}" == "true" ]]; then
  echo "--initialize-observation and --record-observation are mutually exclusive" >&2
  exit 2
fi
if [[ "${RECORD_OBSERVATION}" == "true" ]] \
  && { ! [[ "${HTTP_5XX_COUNT}" =~ ^[0-9]+$ ]]; }; then
  echo "--record-observation requires a non-negative --http-5xx-count" >&2
  exit 2
fi
if [[ "${MODE}" == "manual-ready" || "${MODE}" == "manual" ]]; then
  REQUIRE_OBSERVATION="true"
fi

APP_ROOT="$(cd "${APP_ROOT}" && pwd -P)"
ENV_FILE="${APP_ROOT}/.env"
PYTHON="${APP_ROOT}/.venv/bin/python"
RUNTIME_AUDIT="${APP_ROOT}/scripts/verify_exception_stage3_runtime.py"
NON_AI_ENV="${APP_ROOT}/deploy/exception-non-ai.env"
ENV_ROOT="/etc/enterprise-business-agent"
BASELINE_FILE="${APP_ROOT}/deploy/exception-release-baseline.env"

baseline_value() {
  local key="$1"
  awk -F= -v expected_key="${key}" '
    $0 !~ /^[[:space:]]*#/ && $1 == expected_key && !found {
      print substr($0, index($0, "=") + 1)
      found = 1
    }
    END { if (!found) exit 1 }
  ' "${BASELINE_FILE}"
}

if [[ ! -f "${BASELINE_FILE}" ]]; then
  echo "Exception release baseline is missing." >&2
  exit 1
fi
BASELINE_SOURCE_REVISION="$(baseline_value EXCEPTION_RELEASE_SOURCE_SNAPSHOT)" \
  || { echo "Exception release baseline source is missing." >&2; exit 1; }
BASELINE_RUNTIME_REVISION="$(baseline_value EXCEPTION_RUNTIME_ALEMBIC_REVISION)" \
  || { echo "Exception release baseline Alembic revision is missing." >&2; exit 1; }
if ! [[ "${BASELINE_SOURCE_REVISION}" =~ ^[A-Za-z0-9._/-]{1,128}$ ]] \
  || ! [[ "${BASELINE_RUNTIME_REVISION}" =~ ^[A-Za-z0-9_]{1,128}$ ]]; then
  echo "Exception release baseline has an invalid identity." >&2
  exit 1
fi
EXPECTED_REVISION="${EXPECTED_REVISION:-${BASELINE_RUNTIME_REVISION}}"

failures=0
pass() { printf '[PASS] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1" >&2; failures=$((failures + 1)); }

if [[ ! -f "${APP_ROOT}/SOURCE_REVISION" ]]; then
  fail "release source marker exists"
elif [[ "$(tr -d '\r\n' < "${APP_ROOT}/SOURCE_REVISION")" == "${BASELINE_SOURCE_REVISION}" ]]; then
  pass "release source marker matches the managed baseline"
else
  fail "release source marker matches the managed baseline"
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  fail "environment file exists"
else
  mode_bits="$(stat -c '%a' "${ENV_FILE}")"
  if [[ "${mode_bits}" == "600" ]]; then
    pass "environment file uses owner-only mode 600"
  else
    fail "environment file must use owner-only mode 600"
  fi
fi

app_root_group="$(stat -c '%G' "${APP_ROOT}")"
app_root_mode="$(stat -c '%a' "${APP_ROOT}")"
if [[ "${app_root_group}" == "${CODE_GROUP}" && "${app_root_mode}" == "710" ]]; then
  pass "application root is traversable only by the dedicated code group"
else
  fail "application root must be ${CODE_GROUP}:0710"
fi

if [[ -x "${PYTHON}" ]]; then
  pass "application virtualenv Python exists"
else
  fail "application virtualenv Python exists"
fi
if [[ -f "${RUNTIME_AUDIT}" ]]; then
  pass "runtime audit script exists"
else
  fail "runtime audit script exists"
fi
if [[ -f "${NON_AI_ENV}" ]] \
  && [[ "$(awk -F= '$1 == "HERMES_API_KEY" {print substr($0, index($0, "=") + 1)}' "${NON_AI_ENV}")" == "" ]] \
  && grep --quiet '^HERMES_API_KEY=$' "${NON_AI_ENV}" \
  && grep --quiet '^HERMES_API_BASE_URL=$' "${NON_AI_ENV}"; then
  pass "non-AI credential override is present"
else
  fail "non-AI credential override must clear provider endpoint and key"
fi

declare -A expected_users=(
  [enterprise-business-agent-exception-worker.service]=handmade-exception-worker
  [enterprise-business-agent-exception-ai-worker.service]=handmade-exception-ai
  [enterprise-business-agent-exception-scheduler.service]=handmade-exception-scheduler
)
declare -A expected_states=(
  [enterprise-business-agent-exception-worker.service]=enterprise-business-agent-exception-worker
  [enterprise-business-agent-exception-ai-worker.service]=enterprise-business-agent-exception-ai-worker
  [enterprise-business-agent-exception-scheduler.service]=enterprise-business-agent-exception-scheduler
)
declare -A expected_env_files=(
  [enterprise-business-agent-exception-worker.service]="${ENV_ROOT}/exception-worker.env"
  [enterprise-business-agent-exception-ai-worker.service]="${ENV_ROOT}/exception-ai-worker.env"
  [enterprise-business-agent-exception-scheduler.service]="${ENV_ROOT}/exception-scheduler.env"
  [enterprise-business-agent-exception-observer-metrics.service]="${ENV_ROOT}/exception-observer-metrics.env"
)
common_allowed='^(ENVIRONMENT|DATABASE_URL|EXCEPTION_CENTER_ENABLED|EXCEPTION_AI_ENABLED|EXCEPTION_SCHEDULE_ENABLED|EXCEPTION_ACTIONS_ENABLED|EXCEPTION_AI_MAX_RETRIES|EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS|EXCEPTION_AI_CONCURRENCY|EXCEPTION_AI_DAILY_LIMIT|EXCEPTION_AI_SCHEDULED_BATCH_SIZE|EXCEPTION_MANUAL_AI_DAILY_LIMIT|EXCEPTION_SCHEDULED_AI_DAILY_LIMIT|EXCEPTION_SCHEDULED_AI_BATCH_SIZE|EXCEPTION_AI_CIRCUIT_FAILURE_THRESHOLD|EXCEPTION_AI_CIRCUIT_COOLDOWN_SECONDS|EXCEPTION_EVIDENCE_MAX_BYTES|EXCEPTION_EVIDENCE_MAX_TOKENS|EXCEPTION_JOB_LEASE_SECONDS|EXCEPTION_WORKER_POLL_SECONDS|EXCEPTION_WORKER_HEARTBEAT_SECONDS|EXCEPTION_RUNTIME_HEARTBEAT_SECONDS|EXCEPTION_JOB_MAX_ATTEMPTS|EXCEPTION_SCHEDULE_TIMEZONE)$'

verify_service_environment_file() {
  local unit="$1"
  local path="${expected_env_files[${unit}]}"
  local key
  local invalid=0
  local required_key
  declare -A seen=()
  if [[ ! -f "${path}" ]] || [[ "$(stat -c '%u:%g:%a' "${path}")" != "0:0:600" ]]; then
    fail "${unit} allowlist must be root:root mode 600"
    return
  fi
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    if [[ "${line}" != *=* ]]; then
      invalid=1
      continue
    fi
    key="${line%%=*}"
    if [[ -n "${seen["${key}"]+present}" ]]; then
      invalid=1
    else
      seen["${key}"]=1
    fi
    if [[ "${unit}" == "enterprise-business-agent-exception-ai-worker.service" ]]; then
      if ! [[ "${key}" =~ ${common_allowed} \
        || "${key}" == "EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE" \
        || "${key}" =~ ^HERMES_(API_BASE_URL|API_KEY|MODEL|REQUEST_TIMEOUT_SECONDS)$ ]]; then
        invalid=1
      fi
    elif ! [[ "${key}" =~ ${common_allowed} ]]; then
      invalid=1
    fi
  done < "${path}"
  for required_key in ENVIRONMENT DATABASE_URL EXCEPTION_CENTER_ENABLED EXCEPTION_AI_ENABLED EXCEPTION_SCHEDULE_ENABLED EXCEPTION_ACTIONS_ENABLED EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS; do
    if [[ "${seen["${required_key}"]:-0}" != "1" ]] \
      || ! grep --quiet -E "^${required_key}=.+" "${path}"; then
      invalid=1
    fi
  done
  if [[ "${unit}" == "enterprise-business-agent-exception-ai-worker.service" \
    && ( "${MODE}" == "manual-ready" || "${MODE}" == "manual" ) ]] \
    && { ! grep --quiet -E '^HERMES_API_KEY=.+$' "${path}" \
      || ! grep --quiet -E '^EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true$' "${path}"; }; then
      invalid=1
  fi
  if (( invalid == 0 )); then
    pass "${unit} uses a root-only environment allowlist"
  else
    fail "${unit} environment contains a key outside its allowlist"
  fi
}

if [[ "${PREFLIGHT}" == "false" ]]; then
  for unit in "${!expected_users[@]}"; do
    verify_service_environment_file "${unit}"
  done
  verify_service_environment_file enterprise-business-agent-exception-observer-metrics.service
fi

if [[ "${SKIP_SYSTEMD}" == "false" ]]; then
  units=(
    enterprise-business-agent.service
    enterprise-business-agent-exception-worker.service
    enterprise-business-agent-exception-ai-worker.service
    enterprise-business-agent-exception-scheduler.service
  )
  for unit in "${units[@]}"; do
    if systemctl is-active --quiet "${unit}" \
      && { systemctl is-enabled --quiet "${unit}" \
        || [[ "${ALLOW_DISABLED_EXCEPTION_SERVICES}" == "true" && "${unit}" != "enterprise-business-agent.service" ]]; }; then
      if systemctl is-enabled --quiet "${unit}"; then
        pass "${unit} is enabled and active"
      else
        pass "${unit} is active and intentionally not enabled during provisional verification"
      fi
    else
      fail "${unit} must be active and enabled unless provisional verification allows disabled exception services"
    fi
  done

  for unit in "${!expected_users[@]}"; do
    expected_user="${expected_users[${unit}]}"
    expected_state="${expected_states[${unit}]}"
    expected_service_env="${expected_env_files[${unit}]}"
    actual_user="$(systemctl show --property=User --value "${unit}")"
    state_directories="$(systemctl show --property=StateDirectory --value "${unit}")"
    environment_files="$(systemctl show --property=EnvironmentFiles --value "${unit}")"
    protect_system="$(systemctl show --property=ProtectSystem --value "${unit}")"
    read_only_paths="$(systemctl show --property=ReadOnlyPaths --value "${unit}")"
    inaccessible_paths="$(systemctl show --property=InaccessiblePaths --value "${unit}")"
    supplementary_groups="$(systemctl show --property=SupplementaryGroups --value "${unit}")"
    working_directory="$(systemctl show --property=WorkingDirectory --value "${unit}")"
    if [[ "${actual_user}" == "${expected_user}" ]] \
      && [[ "${state_directories}" == *"${expected_state}"* ]] \
      && [[ "${environment_files}" == *"${expected_service_env}"* ]] \
      && [[ "${environment_files}" != *"${APP_ROOT}/.env"* ]] \
      && [[ "${protect_system}" == "strict" ]] \
      && [[ "${read_only_paths}" == *"${APP_ROOT}"* ]] \
      && [[ "${supplementary_groups}" == *"${CODE_GROUP}"* ]] \
      && [[ "${inaccessible_paths}" == *"${APP_ROOT}/.env"* ]] \
      && [[ "${inaccessible_paths}" == *"${APP_ROOT}/runtime"* ]] \
      && [[ "${inaccessible_paths}" == *"${APP_ROOT}/uploads"* ]] \
      && [[ "${inaccessible_paths}" == *"${APP_ROOT}/attachments"* ]] \
      && [[ "${inaccessible_paths}" == *"${APP_ROOT}/reports"* ]] \
      && [[ "${inaccessible_paths}" == *"${APP_ROOT}/backups"* ]] \
      && [[ "${inaccessible_paths}" == *"${APP_ROOT}/output"* ]] \
      && [[ "${inaccessible_paths}" == *"${APP_ROOT}/outputs"* ]] \
      && [[ "${inaccessible_paths}" == *"${APP_ROOT}/.git"* ]] \
      && [[ "${working_directory}" == "/var/lib/${expected_state}" ]]; then
      pass "${unit} identity, state, environment, and read-only code isolation"
    else
      fail "${unit} isolation properties do not match the release contract"
    fi

    state_path="/var/lib/${expected_state}"
    expected_uid="$(id -u "${expected_user}" 2>/dev/null || true)"
    if [[ -n "${expected_uid}" ]] \
      && [[ -d "${state_path}" ]] \
      && [[ "$(stat -c '%u:%a' "${state_path}")" == "${expected_uid}:700" ]] \
      && ! runuser -u "${expected_user}" -g "${expected_user}" -G "${CODE_GROUP}" -- test -r "${ENV_FILE}" \
      && runuser -u "${expected_user}" -g "${expected_user}" -G "${CODE_GROUP}" -- test -x "${PYTHON}" \
      && runuser -u "${expected_user}" -g "${expected_user}" -G "${CODE_GROUP}" -- \
        test -r "${APP_ROOT}/backend/app/tasks/exception_worker.py" \
      && ! runuser -u "${expected_user}" -g "${expected_user}" -G "${CODE_GROUP}" -- test -w "${APP_ROOT}"; then
      pass "${unit} state ownership and filesystem permissions"
    else
      fail "${unit} state directory or filesystem permissions are unsafe"
    fi
  done

  observer_service="enterprise-business-agent-exception-observer.service"
  observer_metrics_service="enterprise-business-agent-exception-observer-metrics.service"
  observer_timer="enterprise-business-agent-exception-observer.timer"
  observer_user="$(systemctl show --property=User --value "${observer_service}")"
  observer_groups="$(systemctl show --property=SupplementaryGroups --value "${observer_service}")"
  observer_state="$(systemctl show --property=StateDirectory --value "${observer_service}")"
  observer_environment="$(systemctl show --property=EnvironmentFiles --value "${observer_service}")"
  observer_inaccessible="$(systemctl show --property=InaccessiblePaths --value "${observer_service}")"
  observer_read_write="$(systemctl show --property=ReadWritePaths --value "${observer_service}")"
  observer_protect_system="$(systemctl show --property=ProtectSystem --value "${observer_service}")"
  observer_requires="$(systemctl show --property=Requires --value "${observer_service}")"
  observer_state_path="/var/lib/enterprise-business-agent-exception-release"
  observer_uid="$(id -u handmade-exception-observer 2>/dev/null || true)"
  if [[ "${observer_user}" == "handmade-exception-observer" ]] \
    && [[ "${observer_groups}" == *"${CODE_GROUP}"* ]] \
    && [[ "${observer_groups}" != *"systemd-journal"* ]] \
    && [[ "${observer_state}" == *"enterprise-business-agent-exception-release"* ]] \
    && [[ -z "${observer_environment}" ]] \
    && [[ "${observer_requires}" == *"${observer_metrics_service}"* ]] \
    && [[ "${observer_inaccessible}" == *"${APP_ROOT}/.env"* ]] \
    && [[ "${observer_inaccessible}" == *"${APP_ROOT}/backups"* ]] \
    && [[ "${observer_inaccessible}" == *"${APP_ROOT}/output"* ]] \
    && [[ "${observer_inaccessible}" == *"${APP_ROOT}/outputs"* ]] \
    && [[ "${observer_read_write}" == *"/var/lib/enterprise-business-agent-exception-release"* ]] \
    && [[ "${observer_protect_system}" == "strict" ]] \
    && [[ -n "${observer_uid}" ]] \
    && [[ -d "${observer_state_path}" ]] \
    && [[ "$(stat -c '%u:%a' "${observer_state_path}")" == "${observer_uid}:750" ]]; then
    pass "${observer_service} has no database environment or journal-wide membership"
  else
    fail "${observer_service} isolation properties do not match the release contract"
  fi

  metrics_user="$(systemctl show --property=User --value "${observer_metrics_service}")"
  metrics_group="$(systemctl show --property=Group --value "${observer_metrics_service}")"
  metrics_environment="$(systemctl show --property=EnvironmentFiles --value "${observer_metrics_service}")"
  metrics_runtime="$(systemctl show --property=RuntimeDirectory --value "${observer_metrics_service}")"
  metrics_read_write="$(systemctl show --property=ReadWritePaths --value "${observer_metrics_service}")"
  metrics_protect_system="$(systemctl show --property=ProtectSystem --value "${observer_metrics_service}")"
  if [[ "${metrics_user}" == "root" ]] \
    && [[ "${metrics_group}" == "handmade-exception-observer" ]] \
    && [[ "${metrics_environment}" == *"${ENV_ROOT}/exception-observer-metrics.env"* ]] \
    && [[ "${metrics_environment}" != *"${APP_ROOT}/.env"* ]] \
    && [[ "${metrics_runtime}" == *"enterprise-business-agent-exception-observer-metrics"* ]] \
    && [[ "${metrics_read_write}" == *"/run/enterprise-business-agent-exception-observer-metrics"* ]] \
    && [[ "${metrics_protect_system}" == "strict" ]] \
    && systemctl cat "${observer_metrics_service}" \
      | grep --quiet --fixed-strings "IPAddressDeny=any" \
    && systemctl cat "${observer_metrics_service}" \
      | grep --quiet --fixed-strings "IPAddressAllow=localhost" \
    && systemctl cat "${observer_metrics_service}" \
      | grep --quiet --fixed-strings "SupplementaryGroups=systemd-journal"; then
    pass "${observer_metrics_service} is a localhost-only scalar helper"
  else
    fail "${observer_metrics_service} isolation properties do not match the scalar-helper contract"
  fi

  if [[ "${MODE}" == "dark" ]]; then
    if [[ "${ALLOW_DISABLED_EXCEPTION_SERVICES}" == "true" ]]; then
      pass "${observer_timer} activation is deferred until the observation baseline exists"
    else
      observer_timer_substate="$(systemctl show --property=SubState --value "${observer_timer}")"
      observer_timer_next_realtime="$(systemctl show --property=NextElapseUSecRealtime --value "${observer_timer}")"
      observer_timer_next_monotonic="$(systemctl show --property=NextElapseUSecMonotonic --value "${observer_timer}")"
    fi
    if [[ "${ALLOW_DISABLED_EXCEPTION_SERVICES}" != "true" ]] \
      && systemctl is-active --quiet "${observer_timer}" \
      && systemctl is-enabled --quiet "${observer_timer}" \
      && [[ "${observer_timer_substate}" == "waiting" ]] \
      && { \
        { [[ -n "${observer_timer_next_realtime}" ]] && [[ "${observer_timer_next_realtime}" != "infinity" ]]; } \
        || { [[ -n "${observer_timer_next_monotonic}" ]] && [[ "${observer_timer_next_monotonic}" != "infinity" ]]; } \
      } \
      && [[ "$(systemctl show --property=Result --value "${observer_metrics_service}")" == "success" ]] \
      && [[ "$(systemctl show --property=Result --value "${observer_service}")" == "success" ]]; then
      pass "${observer_timer} is enabled, waiting, and has a finite next trigger"
    elif [[ "${ALLOW_DISABLED_EXCEPTION_SERVICES}" != "true" ]]; then
      fail "${observer_timer} must be enabled, waiting, and scheduled after dark baseline initialization"
    fi
  elif ! systemctl is-active --quiet "${observer_timer}" \
    && ! systemctl is-enabled --quiet "${observer_timer}"; then
    pass "${observer_timer} is disabled outside dark observation"
  else
    fail "${observer_timer} must be stopped and disabled before manual readiness"
  fi

  for unit in enterprise-business-agent-exception-worker.service enterprise-business-agent-exception-scheduler.service; do
    main_pid="$(systemctl show --property=MainPID --value "${unit}")"
    if [[ "${main_pid}" =~ ^[1-9][0-9]*$ ]] \
      && tr '\0' '\n' < "/proc/${main_pid}/environ" \
        | awk -F= '
            $1 == "JWT_SECRET" || $1 ~ /^INITIAL_ADMIN_/ || $1 ~ /^HERMES_/ {
              if (substr($0, index($0, "=") + 1) != "") bad = 1
            }
            END { exit bad ? 1 : 0 }
          '; then
      pass "${unit} has no JWT, bootstrap-admin, or model secrets"
    else
      fail "${unit} process environment exposes a forbidden secret"
    fi
  done

  if curl --fail --silent --show-error --max-time 10 --output /dev/null "${API_BASE}/api/v1/health"; then
    pass "application health endpoint"
  else
    fail "application health endpoint"
  fi
  if curl --fail --silent --show-error --max-time 10 --output /dev/null "${API_BASE}/api/v1/health/db"; then
    pass "database health endpoint"
  else
    fail "database health endpoint"
  fi
fi

if (( failures > 0 )); then
  printf 'PRECHECK failures=%s; runtime database audit not started\n' "${failures}" >&2
  exit 1
fi

audit_args=(
  --mode "${MODE}"
  --expected-revision "${EXPECTED_REVISION}"
  --heartbeat-max-age "${HEARTBEAT_MAX_AGE}"
  --provider-canary-max-age-seconds "${PROVIDER_CANARY_MAX_AGE_SECONDS}"
)
if [[ "${SKIP_SYSTEMD}" == "true" ]]; then
  audit_args+=(--skip-heartbeats)
fi
if [[ "${PREFLIGHT}" == "true" ]]; then
  audit_args+=(--preflight)
fi
if [[ -n "${DARK_SINCE}" ]]; then
  audit_args+=(--dark-since "${DARK_SINCE}")
fi
if [[ -n "${TRANSITION_SINCE}" ]]; then
  audit_args+=(--transition-since "${TRANSITION_SINCE}")
fi
if [[ "${INITIALIZE_OBSERVATION}" == "true" ]]; then
  audit_args+=(--observation-file "${OBSERVATION_FILE}" --initialize-observation)
fi
if [[ "${RECORD_OBSERVATION}" == "true" ]]; then
  audit_args+=(
    --observation-file "${OBSERVATION_FILE}"
    --record-observation
    --http-5xx-count "${HTTP_5XX_COUNT}"
    --health-base "${API_BASE}"
  )
fi
if [[ "${REQUIRE_OBSERVATION}" == "true" ]]; then
  audit_args+=(
    --observation-file "${OBSERVATION_FILE}"
    --require-observation
    --observation-min-hours "${OBSERVATION_MIN_HOURS}"
    --observation-max-gap-seconds "${OBSERVATION_MAX_GAP_SECONDS}"
    --observation-latest-max-age-seconds "${OBSERVATION_LATEST_MAX_AGE_SECONDS}"
  )
fi

cd "${APP_ROOT}"
"${PYTHON}" "${RUNTIME_AUDIT}" "${audit_args[@]}"
