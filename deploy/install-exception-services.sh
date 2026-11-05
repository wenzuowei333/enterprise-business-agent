#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${1:-/opt/enterprise-business-agent}"
UNIT_ROOT="${2:-/etc/systemd/system}"
MODE="${3:-dark}"
EXPECTED_REVISION="${EXPECTED_REVISION:-}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/enterprise-business-agent-systemd}"
API_BASE="${API_BASE:-http://127.0.0.1:8082}"
ENV_ROOT="${ENV_ROOT:-/etc/enterprise-business-agent}"
CODE_GROUP="${EXCEPTION_CODE_GROUP:-handmade-exception-code}"
OBSERVATION_ROOT="${OBSERVATION_ROOT:-/var/lib/enterprise-business-agent-exception-release}"
OBSERVATION_FILE="${OBSERVATION_FILE:-${OBSERVATION_ROOT}/dark-observation.json}"
OBSERVATION_MIN_HOURS="${OBSERVATION_MIN_HOURS:-8}"
OBSERVATION_MAX_GAP_SECONDS="${OBSERVATION_MAX_GAP_SECONDS:-900}"
PROVIDER_CANARY_MAX_AGE_SECONDS="${PROVIDER_CANARY_MAX_AGE_SECONDS:-172800}"
RELEASE_BACKUP_DIR="${RELEASE_BACKUP_DIR:-}"
EXPECTED_PREVIOUS_SOURCE_REVISION="${EXPECTED_PREVIOUS_SOURCE_REVISION:-}"
EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION:-20260728_0400}"
EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256="${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256:-}"
MAX_CODE_ARCHIVE_BYTES="${MAX_CODE_ARCHIVE_BYTES:-268435456}"
RELEASE_BACKUP_MAX_AGE_SECONDS="${RELEASE_BACKUP_MAX_AGE_SECONDS:-172800}"
PRODUCTION_OBSERVATION_MIN_HOURS=8
PRODUCTION_OBSERVATION_MAX_GAP_SECONDS=900

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

APP_ROOT="$(cd "${APP_ROOT}" && pwd -P)"
if [[ "${APP_ROOT}" != "/opt/enterprise-business-agent" ]]; then
  echo "The checked-in units are pinned to /opt/enterprise-business-agent; refusing APP_ROOT=${APP_ROOT}." >&2
  exit 2
fi

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
if [[ ! -f "${APP_ROOT}/SOURCE_REVISION" ]]; then
  echo "Deployed SOURCE_REVISION is missing." >&2
  exit 1
fi
if [[ "$(tr -d '\r\n' < "${APP_ROOT}/SOURCE_REVISION")" != "${BASELINE_SOURCE_REVISION}" ]]; then
  echo "Deployed SOURCE_REVISION does not match the exception release baseline." >&2
  exit 1
fi

if [[ "${MODE}" != "dark" && "${MODE}" != "manual-ready" ]]; then
  echo "Mode must be dark or manual-ready. Enable the manual policy only after manual-ready passes." >&2
  exit 2
fi
if ! [[ "${OBSERVATION_MIN_HOURS}" =~ ^[0-9]+([.][0-9]+)?$ ]] \
  || ! awk -v value="${OBSERVATION_MIN_HOURS}" -v minimum="${PRODUCTION_OBSERVATION_MIN_HOURS}" \
    'BEGIN { exit !(value >= minimum) }'; then
  echo "Production observation must cover at least ${PRODUCTION_OBSERVATION_MIN_HOURS} hours." >&2
  exit 2
fi
if ! [[ "${OBSERVATION_MAX_GAP_SECONDS}" =~ ^[0-9]+$ ]] \
  || (( OBSERVATION_MAX_GAP_SECONDS < 60 \
    || OBSERVATION_MAX_GAP_SECONDS > PRODUCTION_OBSERVATION_MAX_GAP_SECONDS )); then
  echo "Production observation sample gaps must be between 60 and ${PRODUCTION_OBSERVATION_MAX_GAP_SECONDS} seconds." >&2
  exit 2
fi
for positive_integer in MAX_CODE_ARCHIVE_BYTES RELEASE_BACKUP_MAX_AGE_SECONDS PROVIDER_CANARY_MAX_AGE_SECONDS; do
  if ! [[ "${!positive_integer}" =~ ^[1-9][0-9]*$ ]]; then
    echo "${positive_integer} must be a positive integer." >&2
    exit 2
  fi
done
if (( PROVIDER_CANARY_MAX_AGE_SECONDS > 604800 )); then
  echo "PROVIDER_CANARY_MAX_AGE_SECONDS cannot exceed 604800 seconds." >&2
  exit 2
fi
if ! [[ "${EXPECTED_PREVIOUS_SOURCE_REVISION}" =~ ^[A-Za-z0-9._/-]{1,128}$ ]]; then
  echo "EXPECTED_PREVIOUS_SOURCE_REVISION must identify the code revision captured before sync." >&2
  exit 2
fi
if ! [[ "${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" =~ ^[A-Za-z0-9_]{1,128}$ ]]; then
  echo "EXPECTED_PREVIOUS_ALEMBIC_REVISION is invalid." >&2
  exit 2
fi
if ! [[ "${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256}" =~ ^[A-Fa-f0-9]{64}$ ]]; then
  echo "EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256 must be the saved pre-sync manifest digest." >&2
  exit 2
fi

ENV_FILE="${APP_ROOT}/.env"
PYTHON="${APP_ROOT}/.venv/bin/python"
AUDIT="${APP_ROOT}/scripts/verify_exception_stage3_runtime.py"
PROVIDER_CANARY="${APP_ROOT}/scripts/run_exception_provider_canary.py"
VERIFY="${APP_ROOT}/deploy/verify-exception-stage3.sh"
NON_AI_ENV="${APP_ROOT}/deploy/exception-non-ai.env"
OBSERVER_SERVICE="enterprise-business-agent-exception-observer.service"
OBSERVER_TIMER="enterprise-business-agent-exception-observer.timer"
OBSERVER_METRICS_SERVICE="enterprise-business-agent-exception-observer-metrics.service"
OBSERVER_RECORD="${APP_ROOT}/deploy/record-exception-stage3-observation.sh"
OBSERVER_COLLECT="${APP_ROOT}/deploy/collect-exception-stage3-observation-metrics.sh"

service_users=(
  handmade-exception-worker
  handmade-exception-ai
  handmade-exception-scheduler
  handmade-exception-observer
)
common_environment_keys=(
  ENVIRONMENT
  DATABASE_URL
  EXCEPTION_CENTER_ENABLED
  EXCEPTION_AI_ENABLED
  EXCEPTION_SCHEDULE_ENABLED
  EXCEPTION_ACTIONS_ENABLED
  EXCEPTION_AI_MAX_RETRIES
  EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS
  EXCEPTION_AI_CONCURRENCY
  EXCEPTION_AI_DAILY_LIMIT
  EXCEPTION_AI_SCHEDULED_BATCH_SIZE
  EXCEPTION_MANUAL_AI_DAILY_LIMIT
  EXCEPTION_SCHEDULED_AI_DAILY_LIMIT
  EXCEPTION_SCHEDULED_AI_BATCH_SIZE
  EXCEPTION_AI_CIRCUIT_FAILURE_THRESHOLD
  EXCEPTION_AI_CIRCUIT_COOLDOWN_SECONDS
  EXCEPTION_EVIDENCE_MAX_BYTES
  EXCEPTION_EVIDENCE_MAX_TOKENS
  EXCEPTION_JOB_LEASE_SECONDS
  EXCEPTION_WORKER_POLL_SECONDS
  EXCEPTION_WORKER_HEARTBEAT_SECONDS
  EXCEPTION_RUNTIME_HEARTBEAT_SECONDS
  EXCEPTION_JOB_MAX_ATTEMPTS
  EXCEPTION_SCHEDULE_TIMEZONE
)
ai_environment_keys=(
  "${common_environment_keys[@]}"
  EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE
  HERMES_API_BASE_URL
  HERMES_API_KEY
  HERMES_MODEL
  HERMES_REQUEST_TIMEOUT_SECONDS
)
required_environment_keys=(
  ENVIRONMENT
  DATABASE_URL
  EXCEPTION_CENTER_ENABLED
  EXCEPTION_AI_ENABLED
  EXCEPTION_SCHEDULE_ENABLED
  EXCEPTION_ACTIONS_ENABLED
  EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS
)

ensure_system_identity() {
  local user_name="$1"
  if ! getent passwd "${user_name}" >/dev/null; then
    useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin "${user_name}"
    created_service_users+=("${user_name}")
  fi
  if [[ "$(id -u "${user_name}")" -lt 1000 ]] \
    && [[ "$(id -gn "${user_name}")" == "${user_name}" ]] \
    && [[ "$(getent passwd "${user_name}" | cut -d: -f7)" == "/usr/sbin/nologin" ]]; then
    return
  fi
  echo "${user_name} must be an independent system identity and group with /usr/sbin/nologin." >&2
  exit 1
}

read_backup_metadata_value() {
  local path="$1"
  local key="$2"
  awk -F= -v expected_key="${key}" '
    $1 == expected_key && !found {
      print substr($0, index($0, "=") + 1)
      found = 1
    }
    END { if (!found) exit 1 }
  ' "${path}"
}

validate_code_archive_contents() {
  local archive_path="$1"
  "${PYTHON}" - "${archive_path}" "$(basename "${APP_ROOT}")" <<'PY'
from __future__ import annotations

import sys
import tarfile
from pathlib import PurePosixPath


archive_path, expected_root = sys.argv[1:]
forbidden_components = {
    ".venv",
    ".git",
    ".codex-remote-attachments",
    "runtime",
    "uploads",
    "attachments",
    "reports",
    "backups",
    "output",
    "outputs",
}
forbidden_suffixes = (".dump", ".sql", ".xlsx", ".xls", ".csv")
compressed_suffixes = tuple(f"{suffix}.gz" for suffix in forbidden_suffixes)

with tarfile.open(archive_path, mode="r:gz") as archive:
    members = archive.getmembers()
    if not members:
        raise SystemExit("Code archive is empty")
    for member in members:
        path = PurePosixPath(member.name)
        parts = path.parts
        lowered_parts = tuple(part.casefold() for part in parts)
        if path.is_absolute() or not parts or parts[0] != expected_root or ".." in parts:
            raise SystemExit("Code archive contains an unsafe member path")
        if any(part in forbidden_components for part in lowered_parts):
            raise SystemExit("Code archive contains a forbidden runtime or business-output path")
        if any(
            part == ".env" or (part.startswith(".env.") and part != ".env.example")
            for part in lowered_parts
        ):
            raise SystemExit("Code archive contains a forbidden environment file")
        lowered_name = member.name.casefold()
        if lowered_name.endswith(forbidden_suffixes + compressed_suffixes):
            raise SystemExit("Code archive contains a forbidden database or tabular-data file")
        if member.isdev() or member.isfifo():
            raise SystemExit("Code archive contains a forbidden special file")
        if member.issym() or member.islnk():
            target = PurePosixPath(member.linkname)
            if target.is_absolute() or ".." in target.parts:
                raise SystemExit("Code archive contains an unsafe link target")
PY
}

validate_release_backup() {
  local resolved_backup
  local required_path
  local metadata_path
  local backup_format
  local backup_app_root
  local created_at
  local created_epoch
  local now_epoch
  local archive_bytes
  local recorded_archive_bytes
  local recorded_archive_limit
  local recorded_dump_bytes
  local source_revision
  local database_alembic_revision
  local revision_file_value
  local manifest_digest
  if [[ -z "${RELEASE_BACKUP_DIR}" ]]; then
    echo "RELEASE_BACKUP_DIR must identify the completed pre-sync release backup." >&2
    exit 1
  fi
  resolved_backup="$(readlink -f "${RELEASE_BACKUP_DIR}" 2>/dev/null || true)"
  if [[ -z "${resolved_backup}" || ! -d "${resolved_backup}" ]]; then
    echo "Release backup directory does not exist: ${RELEASE_BACKUP_DIR}" >&2
    exit 1
  fi
  if [[ "${resolved_backup}" == "${APP_ROOT}" || "${resolved_backup}" == "${APP_ROOT}/"* ]]; then
    echo "Release backup must be stored outside ${APP_ROOT}." >&2
    exit 1
  fi
  if [[ "$(stat -c '%U:%G:%a' "${resolved_backup}")" != "root:root:700" ]]; then
    echo "Release backup root must be root:root mode 700." >&2
    exit 1
  fi
  for required_path in \
    SHA256SUMS \
    code.tar.gz \
    database/postgresql.dump \
    database/alembic-revision.txt \
    environment/application.env \
    units/enterprise-business-agent.service.effective \
    release-backup.env; do
    if [[ ! -f "${resolved_backup}/${required_path}" ]]; then
      echo "Incomplete release backup; missing ${required_path}." >&2
      exit 1
    fi
  done
  if [[ "$(stat -c '%u:%g:%a' "${resolved_backup}/environment/application.env")" != "0:0:600" ]]; then
    echo "Backed-up application environment must be root:root mode 600." >&2
    exit 1
  fi
  (
    cd "${resolved_backup}"
    sha256sum --check --quiet SHA256SUMS
  )
  manifest_digest="$(sha256sum "${resolved_backup}/SHA256SUMS" | awk '{print $1}')"
  if [[ "${manifest_digest,,}" != "${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256,,}" ]]; then
    echo "Release backup manifest does not match the pre-sync digest." >&2
    exit 1
  fi
  pg_restore --list "${resolved_backup}/database/postgresql.dump" >/dev/null
  metadata_path="${resolved_backup}/release-backup.env"
  backup_format="$(read_backup_metadata_value "${metadata_path}" BACKUP_FORMAT_VERSION)"
  backup_app_root="$(read_backup_metadata_value "${metadata_path}" APP_ROOT)"
  created_at="$(read_backup_metadata_value "${metadata_path}" CREATED_AT_UTC)"
  source_revision="$(read_backup_metadata_value "${metadata_path}" SOURCE_REVISION)"
  database_alembic_revision="$(read_backup_metadata_value "${metadata_path}" DATABASE_ALEMBIC_REVISION)"
  recorded_archive_bytes="$(read_backup_metadata_value "${metadata_path}" CODE_ARCHIVE_BYTES)"
  recorded_archive_limit="$(read_backup_metadata_value "${metadata_path}" CODE_ARCHIVE_LIMIT_BYTES)"
  recorded_dump_bytes="$(read_backup_metadata_value "${metadata_path}" DATABASE_DUMP_BYTES)"
  if [[ "${backup_format}" != "2" || "${backup_app_root}" != "${APP_ROOT}" ]]; then
    echo "Release backup metadata does not match format 2 and ${APP_ROOT}." >&2
    exit 1
  fi
  if ! [[ "${source_revision}" =~ ^[A-Za-z0-9._/-]{1,128}$ ]] \
    || ! [[ "${database_alembic_revision}" =~ ^[A-Za-z0-9_]{1,128}$ ]] \
    || ! [[ "${recorded_archive_bytes}" =~ ^[1-9][0-9]*$ ]] \
    || ! [[ "${recorded_archive_limit}" =~ ^[1-9][0-9]*$ ]] \
    || ! [[ "${recorded_dump_bytes}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Release backup metadata contains an invalid revision or size." >&2
    exit 1
  fi
  revision_file_value="$(tr -d '\r\n' < "${resolved_backup}/database/alembic-revision.txt")"
  if [[ "${source_revision}" != "${EXPECTED_PREVIOUS_SOURCE_REVISION}" ]] \
    || [[ "${database_alembic_revision}" != "${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" ]] \
    || [[ "${revision_file_value}" != "${database_alembic_revision}" ]]; then
    echo "Release backup source or database revision does not match the approved pre-sync baseline." >&2
    exit 1
  fi
  if [[ "${recorded_archive_bytes}" != "$(stat -c '%s' "${resolved_backup}/code.tar.gz")" ]] \
    || [[ "${recorded_dump_bytes}" != "$(stat -c '%s' "${resolved_backup}/database/postgresql.dump")" ]]; then
    echo "Release backup metadata sizes do not match the verified artifacts." >&2
    exit 1
  fi
  created_epoch="$(date --date="${created_at}" +%s 2>/dev/null || true)"
  now_epoch="$(date -u +%s)"
  if ! [[ "${created_epoch}" =~ ^[0-9]+$ ]] \
    || (( created_epoch > now_epoch + 300 || now_epoch - created_epoch > RELEASE_BACKUP_MAX_AGE_SECONDS )); then
    echo "Release backup timestamp is invalid, in the future, or older than the approved release window." >&2
    exit 1
  fi
  archive_bytes="$(stat -c '%s' "${resolved_backup}/code.tar.gz")"
  if (( archive_bytes > MAX_CODE_ARCHIVE_BYTES )); then
    echo "Release code archive exceeds MAX_CODE_ARCHIVE_BYTES: ${archive_bytes}." >&2
    exit 1
  fi
  if (( archive_bytes > recorded_archive_limit || recorded_archive_limit > MAX_CODE_ARCHIVE_BYTES )); then
    echo "Release code archive does not satisfy the recorded and installer size limits." >&2
    exit 1
  fi
  validate_code_archive_contents "${resolved_backup}/code.tar.gz"
  tar --list --gzip --file "${resolved_backup}/code.tar.gz" \
    | awk '/^[^/]+\/backend\// { found = 1 } END { exit found ? 0 : 1 }'
  RELEASE_BACKUP_DIR="${resolved_backup}"
}

ensure_code_group() {
  if getent group "${CODE_GROUP}" >/dev/null; then
    return
  fi
  groupadd --system "${CODE_GROUP}"
  code_group_created=true
}

service_can_access_code() {
  local user_name="$1"
  runuser -u "${user_name}" -g "${user_name}" -G "${CODE_GROUP}" -- test -x "${PYTHON}" \
    && runuser -u "${user_name}" -g "${user_name}" -G "${CODE_GROUP}" -- \
      test -r "${APP_ROOT}/backend/app/tasks/exception_worker.py" \
    && ! runuser -u "${user_name}" -g "${user_name}" -G "${CODE_GROUP}" -- test -w "${APP_ROOT}" \
    && ! runuser -u "${user_name}" -g "${user_name}" -G "${CODE_GROUP}" -- test -r "${ENV_FILE}"
}

write_allowlisted_environment() {
  local target_name="$1"
  local key_set_name="$2"
  local target_path="${ENV_ROOT}/${target_name}"
  local temporary_path
  local key
  local -a matches=()
  local -n key_set="${key_set_name}"

  temporary_path="$(mktemp "${ENV_ROOT}/.${target_name}.XXXXXX")"
  chmod 0600 "${temporary_path}"
  for key in "${key_set[@]}"; do
    mapfile -t matches < <(grep -E "^${key}=" "${ENV_FILE}" || true)
    if (( ${#matches[@]} > 1 )); then
      echo "Duplicate ${key} entries in ${ENV_FILE}; refusing ambiguous service configuration." >&2
      rm -f "${temporary_path}"
      exit 1
    fi
    if (( ${#matches[@]} == 1 )); then
      printf '%s\n' "${matches[0]%$'\r'}" >> "${temporary_path}"
    fi
  done
  for key in "${required_environment_keys[@]}"; do
    if ! grep --quiet -E "^${key}=.+" "${temporary_path}"; then
      echo "Required ${key} is missing or empty in ${ENV_FILE}." >&2
      rm -f "${temporary_path}"
      exit 1
    fi
  done
  if [[ "${MODE}" == "manual-ready" && "${target_name}" == "exception-ai-worker.env" ]]; then
    for key in HERMES_API_BASE_URL HERMES_API_KEY EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE; do
      if ! grep --quiet -E "^${key}=.+" "${temporary_path}"; then
        echo "Manual mode requires ${key} in ${ENV_FILE}." >&2
        rm -f "${temporary_path}"
        exit 1
      fi
    done
    if ! grep --quiet '^EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true$' "${temporary_path}"; then
      echo "Manual mode requires EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true." >&2
      rm -f "${temporary_path}"
      exit 1
    fi
  fi
  install -o root -g root -m 0600 "${temporary_path}" "${target_path}"
  rm -f "${temporary_path}"
}

validate_source_environment() {
  local key
  local count
  for key in "${required_environment_keys[@]}"; do
    count="$(grep -c -E "^${key}=.+" "${ENV_FILE}" || true)"
    if [[ "${count}" != "1" ]]; then
      echo "${ENV_FILE} must contain exactly one non-empty ${key}." >&2
      exit 1
    fi
  done
  if [[ "${MODE}" == "manual-ready" ]]; then
    for key in HERMES_API_BASE_URL HERMES_API_KEY EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE; do
      count="$(grep -c -E "^${key}=.+" "${ENV_FILE}" || true)"
      if [[ "${count}" != "1" ]]; then
        echo "Manual mode requires exactly one non-empty ${key} in ${ENV_FILE}." >&2
        exit 1
      fi
    done
    if ! grep --quiet '^EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true$' "${ENV_FILE}"; then
      echo "Manual mode requires EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true." >&2
      exit 1
    fi
  fi
}

validate_unit_source_contract() {
  local source_path="$1"
  local expected_user="$2"
  local expected_state="$3"
  local expected_environment="$4"
  grep --quiet --fixed-strings "User=${expected_user}" "${source_path}" \
    && grep --quiet --fixed-strings "Group=${expected_user}" "${source_path}" \
    && grep --quiet --fixed-strings "SupplementaryGroups=${CODE_GROUP}" "${source_path}" \
    && grep --quiet --fixed-strings "StateDirectory=${expected_state}" "${source_path}" \
    && grep --quiet --fixed-strings "WorkingDirectory=/var/lib/${expected_state}" "${source_path}" \
    && grep --quiet --fixed-strings "EnvironmentFile=${expected_environment}" "${source_path}" \
    && grep --quiet --fixed-strings "ProtectSystem=strict" "${source_path}" \
    && grep --quiet --fixed-strings "ReadOnlyPaths=${APP_ROOT}" "${source_path}" \
    && grep --quiet --fixed-strings "InaccessiblePaths=${APP_ROOT}/.env" "${source_path}" \
    && grep --quiet --fixed-strings "InaccessiblePaths=-${APP_ROOT}/runtime" "${source_path}" \
    && grep --quiet --fixed-strings "InaccessiblePaths=-${APP_ROOT}/uploads" "${source_path}" \
    && grep --quiet --fixed-strings "InaccessiblePaths=-${APP_ROOT}/attachments" "${source_path}" \
    && grep --quiet --fixed-strings "InaccessiblePaths=-${APP_ROOT}/reports" "${source_path}" \
    && grep --quiet --fixed-strings "InaccessiblePaths=-${APP_ROOT}/backups" "${source_path}" \
    && grep --quiet --fixed-strings "InaccessiblePaths=-${APP_ROOT}/output" "${source_path}" \
    && grep --quiet --fixed-strings "InaccessiblePaths=-${APP_ROOT}/outputs" "${source_path}" \
    && grep --quiet --fixed-strings "InaccessiblePaths=-${APP_ROOT}/.git" "${source_path}" \
    && ! grep --quiet --fixed-strings "EnvironmentFile=${ENV_FILE}" "${source_path}" \
    && ! grep --quiet --fixed-strings "ReadWritePaths=${APP_ROOT}" "${source_path}"
}

wait_for_web_health() {
  local attempt
  for attempt in {1..30}; do
    if systemctl is-active --quiet enterprise-business-agent.service \
      && curl --fail --silent --show-error --max-time 5 --output /dev/null "${API_BASE}/api/v1/health" \
      && curl --fail --silent --show-error --max-time 5 --output /dev/null "${API_BASE}/api/v1/health/db"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

read_process_environment_value() {
  local process_id="$1"
  local key="$2"
  tr '\0' '\n' < "/proc/${process_id}/environ" \
    | awk -F= -v expected_key="${key}" '
        $1 == expected_key && !found {
          value = substr($0, index($0, "=") + 1)
          found = 1
        }
        END {
          if (!found) exit 1
          print value
        }
      '
}

web_environment_matches_file() {
  local path="$1"
  local process_id
  local key
  local expected_value
  local actual_value
  process_id="$(systemctl show --property=MainPID --value enterprise-business-agent.service)"
  [[ "${process_id}" =~ ^[1-9][0-9]*$ ]] || return 1
  for key in EXCEPTION_CENTER_ENABLED EXCEPTION_AI_ENABLED EXCEPTION_SCHEDULE_ENABLED EXCEPTION_ACTIONS_ENABLED; do
    expected_value="$(awk -F= -v expected_key="${key}" '
      $1 == expected_key {
        print substr($0, index($0, "=") + 1)
        found = 1
      }
      END { if (!found) exit 1 }
    ' "${path}")" || return 1
    actual_value="$(read_process_environment_value "${process_id}" "${key}")" || return 1
    [[ "${actual_value}" == "${expected_value}" ]] || return 1
  done
}

replace_environment_value() {
  local path="$1"
  local key="$2"
  local value="$3"
  local temporary_path
  temporary_path="$(mktemp "${backup_dir}/.application-env.XXXXXX")"
  awk -v expected_key="${key}" -v replacement="${value}" -F= '
    BEGIN { replaced = 0 }
    $1 == expected_key {
      print expected_key "=" replacement
      replaced = 1
      next
    }
    { print }
    END { if (!replaced) exit 1 }
  ' "${path}" > "${temporary_path}"
  chmod --reference="${path}" "${temporary_path}"
  chown --reference="${path}" "${temporary_path}"
  mv -f "${temporary_path}" "${path}"
}

rollback_release() {
  local original_status="${1:-1}"
  local rollback_failures=0
  local unit
  local environment_name
  local target_path
  local index
  local service_user

  trap - EXIT INT TERM
  set +e
  echo "Release verification failed; stopping new exception runtimes and restoring the snapshot." >&2

  for unit in "${managed_units[@]}"; do
    if [[ -e "${UNIT_ROOT}/${unit}" ]] || systemctl cat "${unit}" >/dev/null 2>&1; then
      systemctl stop "${unit}" >/dev/null 2>&1 \
        || rollback_failures=$((rollback_failures + 1))
    fi
  done

  systemctl disable "${managed_units[@]}" >/dev/null 2>&1 || true

  if [[ "${previous_observation_root_exists}" == "true" ]]; then
    install -d -m "${previous_observation_mode}" "${OBSERVATION_ROOT}" \
      || rollback_failures=$((rollback_failures + 1))
    if [[ "${previous_observation_file_exists}" == "true" ]]; then
      cp --archive --force \
        "${backup_dir}/observation/dark-observation.json" "${OBSERVATION_FILE}" \
        || rollback_failures=$((rollback_failures + 1))
    else
      rm -f "${OBSERVATION_FILE}" || rollback_failures=$((rollback_failures + 1))
    fi
    chown "${previous_observation_uid}:${previous_observation_gid}" "${OBSERVATION_ROOT}" \
      || rollback_failures=$((rollback_failures + 1))
    chmod "${previous_observation_mode}" "${OBSERVATION_ROOT}" \
      || rollback_failures=$((rollback_failures + 1))
  else
    rm -f "${OBSERVATION_FILE}" || rollback_failures=$((rollback_failures + 1))
    if [[ -d "${OBSERVATION_ROOT}" ]]; then
      rmdir "${OBSERVATION_ROOT}" || rollback_failures=$((rollback_failures + 1))
    fi
  fi

  for environment_name in "${environment_names[@]}"; do
    target_path="${ENV_ROOT}/${environment_name}"
    if [[ "${previous_environment_exists[${environment_name}]}" == "true" ]]; then
      install -o root -g root -m 0600 \
        "${backup_dir}/environment/${environment_name}" "${target_path}" \
        || rollback_failures=$((rollback_failures + 1))
    else
      rm -f "${target_path}" || rollback_failures=$((rollback_failures + 1))
    fi
  done

  for unit in "${managed_units[@]}"; do
    target_path="${UNIT_ROOT}/${unit}"
    if [[ "${previous_unit_exists[${unit}]}" == "true" ]]; then
      install -o root -g root -m 0644 "${backup_dir}/units/${unit}" "${target_path}" \
        || rollback_failures=$((rollback_failures + 1))
    else
      rm -f "${target_path}" || rollback_failures=$((rollback_failures + 1))
    fi
  done

  chown ":${previous_app_gid}" "${APP_ROOT}" \
    || rollback_failures=$((rollback_failures + 1))
  chmod "${previous_app_mode}" "${APP_ROOT}" \
    || rollback_failures=$((rollback_failures + 1))
  if [[ "${code_group_created:-false}" == "true" && "${code_group_existed:-true}" != "true" ]]; then
    groupdel "${CODE_GROUP}" || rollback_failures=$((rollback_failures + 1))
  fi

  systemctl daemon-reload || rollback_failures=$((rollback_failures + 1))
  cp --archive --force "${backup_dir}/application.env.rollback" "${ENV_FILE}" \
    || rollback_failures=$((rollback_failures + 1))
  if [[ "${previous_main_active}" == "true" ]]; then
    systemctl restart enterprise-business-agent.service || rollback_failures=$((rollback_failures + 1))
    wait_for_web_health || rollback_failures=$((rollback_failures + 1))
    web_environment_matches_file "${ENV_FILE}" || rollback_failures=$((rollback_failures + 1))
  else
    systemctl stop enterprise-business-agent.service >/dev/null 2>&1 || true
  fi

  for unit in "${managed_units[@]}"; do
    if [[ "${previous_unit_exists[${unit}]}" != "true" ]]; then
      systemctl stop "${unit}" >/dev/null 2>&1 || true
      systemctl disable "${unit}" >/dev/null 2>&1 || true
      echo "ROLLBACK ${unit}: removed; stopped; disabled"
      continue
    fi
    if [[ "${previous_enabled[${unit}]}" == "true" ]]; then
      systemctl enable "${unit}" >/dev/null 2>&1 \
        || rollback_failures=$((rollback_failures + 1))
    else
      systemctl disable "${unit}" >/dev/null 2>&1 || true
    fi
    if [[ "${previous_active[${unit}]}" == "true" ]]; then
      systemctl start "${unit}" || rollback_failures=$((rollback_failures + 1))
    else
      systemctl stop "${unit}" >/dev/null 2>&1 || true
    fi
    echo "ROLLBACK ${unit}: enabled=${previous_enabled[${unit}]} active=${previous_active[${unit}]}"
  done

  for (( index=${#created_service_users[@]}-1; index>=0; index-- )); do
    service_user="${created_service_users[${index}]}"
    userdel "${service_user}" >/dev/null 2>&1 \
      || rollback_failures=$((rollback_failures + 1))
    if getent group "${service_user}" >/dev/null; then
      groupdel "${service_user}" >/dev/null 2>&1 \
        || rollback_failures=$((rollback_failures + 1))
    fi
  done

  if (( rollback_failures == 0 )); then
    echo "ROLLBACK complete: prior allowlists, units, and service states restored. Snapshot: ${backup_dir}" >&2
  else
    systemctl stop enterprise-business-agent-exception-ai-worker.service >/dev/null 2>&1 || true
    echo "ROLLBACK incomplete: failures=${rollback_failures}. Keep the AI worker stopped and inspect ${backup_dir}." >&2
  fi
  exit "${original_status}"
}

release_exit_handler() {
  local status="$?"
  if [[ "${mutation_started:-false}" == "true" && "${release_committed:-false}" != "true" ]]; then
    rollback_release "${status}"
  fi
}

for path in \
  "${ENV_FILE}" "${AUDIT}" "${PROVIDER_CANARY}" "${VERIFY}" "${NON_AI_ENV}" \
  "${OBSERVER_RECORD}" "${OBSERVER_COLLECT}"; do
  if [[ ! -e "${path}" ]]; then
    echo "Missing required release artifact: ${path}" >&2
    exit 1
  fi
done
if [[ ! -x "${PYTHON}" ]]; then
  echo "Application virtualenv Python is missing or not executable: ${PYTHON}" >&2
  exit 1
fi

mode_bits="$(stat -c '%a' "${ENV_FILE}")"
if [[ "${mode_bits}" != "600" ]]; then
  echo "${ENV_FILE} must use owner-only mode 600." >&2
  exit 1
fi
validate_source_environment

units=(
  enterprise-business-agent-exception-worker.service
  enterprise-business-agent-exception-ai-worker.service
  enterprise-business-agent-exception-scheduler.service
)
observer_units=(
  "${OBSERVER_METRICS_SERVICE}"
  "${OBSERVER_SERVICE}"
  "${OBSERVER_TIMER}"
)
managed_units=(
  "${units[@]}"
  "${observer_units[@]}"
)
unit_users=(
  handmade-exception-worker
  handmade-exception-ai
  handmade-exception-scheduler
)
unit_states=(
  enterprise-business-agent-exception-worker
  enterprise-business-agent-exception-ai-worker
  enterprise-business-agent-exception-scheduler
)
unit_environments=(
  "${ENV_ROOT}/exception-worker.env"
  "${ENV_ROOT}/exception-ai-worker.env"
  "${ENV_ROOT}/exception-scheduler.env"
)
environment_names=(
  exception-worker.env
  exception-ai-worker.env
  exception-scheduler.env
  exception-observer-metrics.env
)
verify_paths=()
source_paths=()
for index in "${!units[@]}"; do
  unit="${units[${index}]}"
  source_path="${APP_ROOT}/deploy/${unit}"
  if [[ ! -f "${source_path}" ]]; then
    echo "Missing unit file: ${source_path}" >&2
    exit 1
  fi
  if ! validate_unit_source_contract \
    "${source_path}" \
    "${unit_users[${index}]}" \
    "${unit_states[${index}]}" \
    "${unit_environments[${index}]}"; then
    echo "Unit source does not satisfy the isolation contract: ${source_path}" >&2
    exit 1
  fi
  source_paths+=("${source_path}")
done
observer_source_paths=(
  "${APP_ROOT}/deploy/${OBSERVER_METRICS_SERVICE}"
  "${APP_ROOT}/deploy/${OBSERVER_SERVICE}"
  "${APP_ROOT}/deploy/${OBSERVER_TIMER}"
)
for source_path in "${observer_source_paths[@]}"; do
  if [[ ! -f "${source_path}" ]]; then
    echo "Missing observer unit file: ${source_path}" >&2
    exit 1
  fi
done
metrics_source="${observer_source_paths[0]}"
observer_source="${observer_source_paths[1]}"
if ! grep --quiet --fixed-strings "User=root" "${metrics_source}" \
  || ! grep --quiet --fixed-strings "Group=handmade-exception-observer" "${metrics_source}" \
  || ! grep --quiet --fixed-strings "EnvironmentFile=${ENV_ROOT}/exception-observer-metrics.env" "${metrics_source}" \
  || ! grep --quiet --fixed-strings "IPAddressDeny=any" "${metrics_source}" \
  || ! grep --quiet --fixed-strings "IPAddressAllow=localhost" "${metrics_source}" \
  || ! grep --quiet --fixed-strings "SupplementaryGroups=systemd-journal ${CODE_GROUP}" "${metrics_source}" \
  || ! grep --quiet --fixed-strings "ReadWritePaths=/run/enterprise-business-agent-exception-observer-metrics" "${metrics_source}"; then
  echo "Root scalar metrics helper does not satisfy the restricted helper contract." >&2
  exit 1
fi
if ! grep --quiet --fixed-strings "User=handmade-exception-observer" "${observer_source}" \
  || ! grep --quiet --fixed-strings "Group=handmade-exception-observer" "${observer_source}" \
  || ! grep --quiet --fixed-strings "SupplementaryGroups=${CODE_GROUP}" "${observer_source}" \
  || ! grep --quiet --fixed-strings "Requires=${OBSERVER_METRICS_SERVICE}" "${observer_source}" \
  || ! grep --quiet --fixed-strings "StateDirectory=enterprise-business-agent-exception-release" "${observer_source}" \
  || ! grep --quiet --fixed-strings "StateDirectoryMode=0750" "${observer_source}" \
  || ! grep --quiet --fixed-strings "ProtectSystem=strict" "${observer_source}" \
  || ! grep --quiet --fixed-strings "ReadOnlyPaths=${APP_ROOT}" "${observer_source}" \
  || ! grep --quiet --fixed-strings "ReadWritePaths=${OBSERVATION_ROOT}" "${observer_source}" \
  || grep --quiet --fixed-strings "EnvironmentFile=" "${observer_source}" \
  || grep --quiet --fixed-strings "systemd-journal" "${observer_source}"; then
  echo "Observer service source does not satisfy the release isolation contract." >&2
  exit 1
fi
source_paths+=("${observer_source_paths[@]}")

if ! systemctl is-active --quiet enterprise-business-agent.service; then
  echo "enterprise-business-agent.service must be active before exception workers are installed." >&2
  exit 1
fi
if ! curl --fail --silent --show-error --max-time 10 --output /dev/null "${API_BASE}/api/v1/health"; then
  echo "Application health preflight failed." >&2
  exit 1
fi
if ! curl --fail --silent --show-error --max-time 10 --output /dev/null "${API_BASE}/api/v1/health/db"; then
  echo "Database health preflight failed." >&2
  exit 1
fi
validate_release_backup

observation_deployed_at=""
if [[ "${MODE}" == "manual-ready" ]]; then
  # Close the final sampling gap while the dark-mode allowlist is still active.
  systemctl start "${OBSERVER_SERVICE}"
  if [[ "$(systemctl show --property=Result --value "${OBSERVER_METRICS_SERVICE}")" != "success" ]] \
    || [[ "$(systemctl show --property=Result --value "${OBSERVER_SERVICE}")" != "success" ]]; then
    echo "The mandatory final dark-observation sample failed." >&2
    exit 1
  fi
  observation_deployed_at="$("${PYTHON}" - "${OBSERVATION_FILE}" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("deployed_at")
if not isinstance(value, str) or not value:
    raise SystemExit("observation baseline has no deployed_at timestamp")
print(value)
PY
)"
fi

echo "Running read-only stage-three preflight (${MODE})..."
cd "${APP_ROOT}"
preflight_args=(
  --mode "${MODE}"
  --expected-revision "${EXPECTED_REVISION}"
  --skip-heartbeats
  --preflight
  --provider-canary-max-age-seconds "${PROVIDER_CANARY_MAX_AGE_SECONDS}"
)
if [[ "${MODE}" == "manual-ready" ]]; then
  preflight_args+=(
    --observation-file "${OBSERVATION_FILE}"
    --require-observation
    --observation-min-hours "${OBSERVATION_MIN_HOURS}"
    --observation-max-gap-seconds "${OBSERVATION_MAX_GAP_SECONDS}"
    --observation-latest-max-age-seconds 60
    --dark-since "${observation_deployed_at}"
  )
fi
"${PYTHON}" "${AUDIT}" "${preflight_args[@]}"

# Snapshot every artifact and service state before the first release mutation.
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${BACKUP_ROOT}/${timestamp}-$$"
  install -d -o root -g root -m 0700 \
    "${backup_dir}/environment" "${backup_dir}/units" "${backup_dir}/observation"
declare -A previous_environment_exists=()
declare -A previous_unit_exists=()
declare -A previous_enabled=()
declare -A previous_active=()
declare -A previous_main_settings=()
created_service_users=()
previous_observation_root_exists=false
previous_observation_file_exists=false
previous_observation_uid=""
previous_observation_gid=""
previous_observation_mode=""
previous_app_gid="$(stat -c '%g' "${APP_ROOT}")"
previous_app_group="$(stat -c '%G' "${APP_ROOT}")"
previous_app_mode="$(stat -c '%a' "${APP_ROOT}")"
if getent group "${CODE_GROUP}" >/dev/null; then
  code_group_existed=true
else
  code_group_existed=false
fi
code_group_created=false
printf 'group=%s gid=%s mode=%s\n' \
  "${previous_app_group}" "${previous_app_gid}" "${previous_app_mode}" \
  > "${backup_dir}/application-root-metadata.txt"
printf 'release_backup=%s\nmanifest_sha256=%s\n' \
  "${RELEASE_BACKUP_DIR}" \
  "$(sha256sum "${RELEASE_BACKUP_DIR}/SHA256SUMS" | awk '{print $1}')" \
  > "${backup_dir}/release-backup-reference.txt"

if [[ -d "${OBSERVATION_ROOT}" ]]; then
  previous_observation_root_exists=true
  previous_observation_uid="$(stat -c '%u' "${OBSERVATION_ROOT}")"
  previous_observation_gid="$(stat -c '%g' "${OBSERVATION_ROOT}")"
  previous_observation_mode="$(stat -c '%a' "${OBSERVATION_ROOT}")"
  printf 'exists=true uid=%s gid=%s mode=%s\n' \
    "${previous_observation_uid}" "${previous_observation_gid}" "${previous_observation_mode}" \
    > "${backup_dir}/observation/root-metadata.txt"
else
  printf 'exists=false\n' > "${backup_dir}/observation/root-metadata.txt"
fi
if [[ -f "${OBSERVATION_FILE}" ]]; then
  previous_observation_file_exists=true
  cp --archive "${OBSERVATION_FILE}" "${backup_dir}/observation/dark-observation.json"
fi

for environment_name in "${environment_names[@]}"; do
  target_path="${ENV_ROOT}/${environment_name}"
  if [[ -f "${target_path}" ]]; then
    previous_environment_exists["${environment_name}"]=true
    cp --archive "${target_path}" "${backup_dir}/environment/${environment_name}"
  else
    previous_environment_exists["${environment_name}"]=false
  fi
done
for unit in "${managed_units[@]}"; do
  target_path="${UNIT_ROOT}/${unit}"
  if [[ -f "${target_path}" ]]; then
    previous_unit_exists["${unit}"]=true
    cp --archive "${target_path}" "${backup_dir}/units/${unit}"
  else
    previous_unit_exists["${unit}"]=false
  fi
  if systemctl is-enabled --quiet "${unit}"; then
    previous_enabled["${unit}"]=true
  else
    previous_enabled["${unit}"]=false
  fi
  if systemctl is-active --quiet "${unit}"; then
    previous_active["${unit}"]=true
  else
    previous_active["${unit}"]=false
  fi
  printf '%s unit_exists=%s enabled=%s active=%s\n' \
    "${unit}" "${previous_unit_exists[${unit}]}" \
    "${previous_enabled[${unit}]}" "${previous_active[${unit}]}" \
    >> "${backup_dir}/service-state.txt"
done
if systemctl is-active --quiet enterprise-business-agent.service; then
  previous_main_active=true
else
  previous_main_active=false
fi
printf '%s active=%s\n' enterprise-business-agent.service "${previous_main_active}" \
  >> "${backup_dir}/service-state.txt"

main_pid="$(systemctl show --property=MainPID --value enterprise-business-agent.service)"
if ! [[ "${main_pid}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Cannot snapshot the running Web configuration: enterprise-business-agent.service has no MainPID." >&2
  exit 1
fi
cp --archive "${ENV_FILE}" "${backup_dir}/application.env.requested"
cp --archive "${ENV_FILE}" "${backup_dir}/application.env.rollback"
for key in EXCEPTION_CENTER_ENABLED EXCEPTION_AI_ENABLED EXCEPTION_SCHEDULE_ENABLED EXCEPTION_ACTIONS_ENABLED; do
  if ! previous_main_settings["${key}"]="$(read_process_environment_value "${main_pid}" "${key}")"; then
    echo "Cannot snapshot running ${key}; release compensation cannot be guaranteed." >&2
    exit 1
  fi
  replace_environment_value \
    "${backup_dir}/application.env.rollback" "${key}" "${previous_main_settings[${key}]}"
done

mutation_started=true
release_committed=false
trap release_exit_handler EXIT
trap 'exit 130' INT TERM

# The first release mutation happens only after all read-only checks and the snapshot succeed.
ensure_code_group
chown ":${CODE_GROUP}" "${APP_ROOT}"
chmod 0710 "${APP_ROOT}"
for service_user in "${service_users[@]}"; do
  ensure_system_identity "${service_user}"
  if ! service_can_access_code "${service_user}"; then
    echo "${service_user} failed the supplementary-group code access and secret-isolation check." >&2
    exit 1
  fi
done
install -d -o handmade-exception-observer -g handmade-exception-observer -m 0750 \
  "${OBSERVATION_ROOT}"

install -d -o root -g root -m 0700 "${ENV_ROOT}"
  write_allowlisted_environment exception-worker.env common_environment_keys
  write_allowlisted_environment exception-scheduler.env common_environment_keys
  write_allowlisted_environment exception-ai-worker.env ai_environment_keys
  write_allowlisted_environment exception-observer-metrics.env common_environment_keys

dark_since="$(date -u --iso-8601=seconds)"

# Resolve users and validate the complete set before changing installed units.
systemd-analyze verify "${source_paths[@]}"

for unit in "${managed_units[@]}"; do
  source_path="${APP_ROOT}/deploy/${unit}"
  target_path="${UNIT_ROOT}/${unit}"
  install -m 0644 "${source_path}" "${target_path}"
  verify_paths+=("${target_path}")
done

systemd-analyze verify "${verify_paths[@]}"
systemctl daemon-reload
systemctl stop "${managed_units[@]}" >/dev/null 2>&1 || true
systemctl disable "${managed_units[@]}" >/dev/null 2>&1 || true

systemctl restart enterprise-business-agent.service
if ! wait_for_web_health; then
  echo "enterprise-business-agent.service did not recover both health endpoints after configuration reload." >&2
  false
fi
if ! web_environment_matches_file "${ENV_FILE}"; then
  echo "enterprise-business-agent.service did not load the requested exception feature switches." >&2
  false
fi

systemctl restart "${units[@]}"

for attempt in {1..30}; do
  all_active=true
  for unit in "${units[@]}"; do
    if ! systemctl is-active --quiet "${unit}"; then
      all_active=false
      break
    fi
  done
  if [[ "${all_active}" == "true" ]]; then
    break
  fi
  sleep 1
done

for unit in "${units[@]}"; do
  if ! systemctl is-active --quiet "${unit}"; then
    echo "${unit} failed to start; inspect: journalctl -u ${unit} -n 100 --no-pager" >&2
    exit 1
  fi
  echo "${unit}: active"
done

# Workers persist their first heartbeat immediately; allow a short database round trip.
sleep 3
verify_args=(
  --mode "${MODE}"
  --app-root "${APP_ROOT}"
  --expected-revision "${EXPECTED_REVISION}"
  --provider-canary-max-age-seconds "${PROVIDER_CANARY_MAX_AGE_SECONDS}"
)
if [[ "${MODE}" == "dark" ]]; then
  verify_args+=(--dark-since "${dark_since}")
else
  verify_args+=(
    --observation-file "${OBSERVATION_FILE}"
    --require-observation
    --observation-min-hours "${OBSERVATION_MIN_HOURS}"
    --observation-max-gap-seconds "${OBSERVATION_MAX_GAP_SECONDS}"
    --observation-latest-max-age-seconds 60
    --dark-since "${observation_deployed_at}"
  )
fi

# Verify the running services before making them persistent across reboot.
bash "${VERIFY}" "${verify_args[@]}" --allow-disabled-exception-services
systemctl enable "${units[@]}"
if [[ "${MODE}" == "dark" ]]; then
  install -d -o handmade-exception-observer -g handmade-exception-observer -m 0750 \
    "${OBSERVATION_ROOT}"
  "${PYTHON}" "${AUDIT}" \
    --mode dark \
    --expected-revision "${EXPECTED_REVISION}" \
    --dark-since "${dark_since}" \
    --observation-file "${OBSERVATION_FILE}" \
    --initialize-observation
  chown handmade-exception-observer:handmade-exception-observer "${OBSERVATION_FILE}"
  chmod 0640 "${OBSERVATION_FILE}"
  systemctl start "${OBSERVER_SERVICE}"
  if [[ "$(systemctl show --property=Result --value "${OBSERVER_SERVICE}")" != "success" ]]; then
    echo "${OBSERVER_SERVICE} failed to record the first least-privilege sample." >&2
    false
  fi
  systemctl enable --now "${OBSERVER_TIMER}"
  bash "${VERIFY}" "${verify_args[@]}"
else
  bash "${VERIFY}" "${verify_args[@]}"
fi

release_committed=true
trap - EXIT INT TERM
echo "Unit backup: ${backup_dir}"
