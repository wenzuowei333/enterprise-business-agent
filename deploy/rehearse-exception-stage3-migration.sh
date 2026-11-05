#!/usr/bin/env bash
set -euo pipefail
umask 0077
export PYTHONDONTWRITEBYTECODE=1

BACKUP_DIR="${1:-}"
APP_ROOT="${2:-/opt/enterprise-business-agent}"
POSTGRES_HOST="127.0.0.1"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
START_REVISION="20260728_0400"
TARGET_REVISION="20260729_0500"
EXPECTED_PREVIOUS_SOURCE_REVISION="${EXPECTED_PREVIOUS_SOURCE_REVISION:-}"
EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION:-${START_REVISION}}"
EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256="${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256:-}"
EXPECTED_TARGET_SOURCE_REVISION="${EXPECTED_TARGET_SOURCE_REVISION:-}"
EXPECTED_BACKUP_APP_ROOT="${EXPECTED_BACKUP_APP_ROOT:-}"
REHEARSAL_PYTHON="${REHEARSAL_PYTHON:-}"

usage() {
  echo "Usage: $0 RELEASE_BACKUP_DIR [APP_ROOT]" >&2
}

validate_candidate_root() {
  local candidate_root="$1"
  if [[ -e "${candidate_root}/.venv" || -L "${candidate_root}/.venv" ]]; then
    echo "Candidate root must not contain a .venv entry or symbolic link." >&2
    return 1
  fi
}

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this migration rehearsal as root." >&2
  exit 1
fi
if [[ -z "${BACKUP_DIR}" ]]; then
  usage
  exit 2
fi
if ! [[ "${POSTGRES_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] || (( POSTGRES_PORT > 65535 )); then
  echo "POSTGRES_PORT must be a valid TCP port." >&2
  exit 2
fi

for command_name in openssl pg_restore psql readlink runuser sha256sum stat; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing migration rehearsal dependency: ${command_name}" >&2
    exit 1
  fi
done
if ! [[ "${EXPECTED_PREVIOUS_SOURCE_REVISION}" =~ ^[A-Za-z0-9._/-]{1,128}$ ]]; then
  echo "EXPECTED_PREVIOUS_SOURCE_REVISION must match the saved pre-sync revision." >&2
  exit 2
fi
if ! [[ "${EXPECTED_TARGET_SOURCE_REVISION}" =~ ^[A-Za-z0-9._/-]{1,128}$ ]]; then
  echo "EXPECTED_TARGET_SOURCE_REVISION must identify the candidate code revision." >&2
  exit 2
fi
if [[ -z "${EXPECTED_BACKUP_APP_ROOT}" ]] || [[ "${EXPECTED_BACKUP_APP_ROOT}" != /* ]] \
  || [[ "${EXPECTED_BACKUP_APP_ROOT}" == *".."* ]]; then
  echo "EXPECTED_BACKUP_APP_ROOT must be an absolute production application path." >&2
  exit 2
fi
if [[ -z "${REHEARSAL_PYTHON}" ]] || [[ "${REHEARSAL_PYTHON}" != /* ]] \
  || [[ "${REHEARSAL_PYTHON}" == *".."* ]]; then
  echo "REHEARSAL_PYTHON must be the absolute production virtualenv Python path." >&2
  exit 2
fi
if [[ "${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" != "${START_REVISION}" ]]; then
  echo "EXPECTED_PREVIOUS_ALEMBIC_REVISION must equal ${START_REVISION}." >&2
  exit 2
fi
if ! [[ "${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256}" =~ ^[A-Fa-f0-9]{64}$ ]]; then
  echo "EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256 must be the saved pre-sync manifest digest." >&2
  exit 2
fi

APP_ROOT="$(cd "${APP_ROOT}" && pwd -P)"
validate_candidate_root "${APP_ROOT}"
EXPECTED_BACKUP_APP_ROOT="$(readlink -f "${EXPECTED_BACKUP_APP_ROOT}" 2>/dev/null || true)"
BACKUP_DIR="$(readlink -f "${BACKUP_DIR}" 2>/dev/null || true)"
PYTHON="${REHEARSAL_PYTHON}"
ALEMBIC_INI="${APP_ROOT}/backend/alembic.ini"
DUMP_PATH="${BACKUP_DIR}/database/postgresql.dump"
SOURCE_REVISION_FILE="${APP_ROOT}/SOURCE_REVISION"

if [[ -z "${BACKUP_DIR}" || ! -d "${BACKUP_DIR}" ]]; then
  echo "Release backup directory does not exist." >&2
  exit 1
fi
if [[ "$(stat -c '%U:%G:%a' "${BACKUP_DIR}")" != "root:root:700" ]]; then
  echo "Release backup root must be root:root mode 700." >&2
  exit 1
fi
if [[ ! -x "${PYTHON}" || ! -f "${ALEMBIC_INI}" || ! -f "${SOURCE_REVISION_FILE}" ]]; then
  echo "Candidate Python, Alembic configuration, or source revision is missing." >&2
  exit 1
fi
if [[ -z "${EXPECTED_BACKUP_APP_ROOT}" ]] \
  || [[ "${PYTHON}" != "${EXPECTED_BACKUP_APP_ROOT}/.venv/bin/python" ]] \
  || [[ "$(tr -d '\r\n' < "${SOURCE_REVISION_FILE}")" != "${EXPECTED_TARGET_SOURCE_REVISION}" ]]; then
  echo "Candidate code does not match the approved target revision." >&2
  exit 1
fi
if [[ ! -f "${DUMP_PATH}" ]]; then
  echo "Release backup does not contain database/postgresql.dump." >&2
  exit 1
fi
for required_path in SHA256SUMS release-backup.env database/alembic-revision.txt; do
  if [[ ! -f "${BACKUP_DIR}/${required_path}" ]]; then
    echo "Release backup is missing ${required_path}." >&2
    exit 1
  fi
done
(
  cd "${BACKUP_DIR}"
  sha256sum --check --quiet SHA256SUMS
)
manifest_digest="$(sha256sum "${BACKUP_DIR}/SHA256SUMS" | awk '{print $1}')"
if [[ "${manifest_digest,,}" != "${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256,,}" ]]; then
  echo "Release backup manifest does not match the saved pre-sync digest." >&2
  exit 1
fi
metadata_value() {
  local key="$1"
  awk -F= -v expected_key="${key}" '
    $1 == expected_key && !found {
      print substr($0, index($0, "=") + 1)
      found = 1
    }
    END { if (!found) exit 1 }
  ' "${BACKUP_DIR}/release-backup.env"
}
backup_source_revision="$(metadata_value SOURCE_REVISION)"
backup_database_revision="$(metadata_value DATABASE_ALEMBIC_REVISION)"
backup_format="$(metadata_value BACKUP_FORMAT_VERSION)"
backup_app_root="$(metadata_value APP_ROOT)"
revision_file_value="$(tr -d '\r\n' < "${BACKUP_DIR}/database/alembic-revision.txt")"
if [[ "${backup_format}" != "2" || "${backup_app_root}" != "${EXPECTED_BACKUP_APP_ROOT}" ]] \
  || [[ "${backup_source_revision}" != "${EXPECTED_PREVIOUS_SOURCE_REVISION}" ]] \
  || [[ "${backup_database_revision}" != "${START_REVISION}" ]] \
  || [[ "${revision_file_value}" != "${START_REVISION}" ]]; then
  echo "Release backup identity does not match the approved migration baseline." >&2
  exit 1
fi
pg_restore --list "${DUMP_PATH}" >/dev/null

suffix="$(date -u +%Y%m%d%H%M%S)_$$_$(openssl rand -hex 4)"
database_name="handmade_exc3_${suffix}"
role_name="handmade_exc3_${suffix}"
role_password="$(openssl rand -hex 32)"
database_created=false
role_created=false

postgres_psql() {
  runuser -u postgres -- psql \
    --no-psqlrc \
    --port "${POSTGRES_PORT}" \
    --dbname postgres \
    --set ON_ERROR_STOP=1 \
    "$@"
}

cleanup() {
  local original_status="$?"
  local cleanup_status=0
  trap - EXIT INT TERM
  set +e
  if [[ "${database_created}" == "true" ]]; then
    postgres_psql --quiet >/dev/null <<SQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '${database_name}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "${database_name}";
SQL
    cleanup_status=$?
  fi
  if [[ "${role_created}" == "true" ]]; then
    postgres_psql --quiet >/dev/null <<SQL
DROP ROLE IF EXISTS "${role_name}";
SQL
    if (( $? != 0 )); then
      cleanup_status=1
    fi
  fi
  role_password=""
  if (( cleanup_status != 0 )); then
    echo "Migration rehearsal cleanup failed; keep the release blocked and inspect local PostgreSQL." >&2
    (( original_status == 0 )) && original_status=1
  fi
  exit "${original_status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

postgres_psql --quiet >/dev/null <<SQL
CREATE ROLE "${role_name}"
  LOGIN PASSWORD '${role_password}'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
SQL
role_created=true
postgres_psql --quiet >/dev/null <<SQL
CREATE DATABASE "${database_name}"
  OWNER "${role_name}"
  TEMPLATE template0
  ENCODING 'UTF8';
SQL
database_created=true

export PGPASSWORD="${role_password}"
pg_restore \
  --exit-on-error \
  --no-owner \
  --no-acl \
  --host "${POSTGRES_HOST}" \
  --port "${POSTGRES_PORT}" \
  --username "${role_name}" \
  --dbname "${database_name}" \
  "${DUMP_PATH}" >/dev/null

database_url="postgresql+psycopg://${role_name}:${role_password}@${POSTGRES_HOST}:${POSTGRES_PORT}/${database_name}"

current_revision() {
  psql \
    --no-psqlrc \
    --host "${POSTGRES_HOST}" \
    --port "${POSTGRES_PORT}" \
    --username "${role_name}" \
    --dbname "${database_name}" \
    --no-align \
    --tuples-only \
    --set ON_ERROR_STOP=1 \
    --command 'SELECT version_num FROM alembic_version ORDER BY version_num' \
    | tr -d '[:space:]'
}

query_scalar() {
  psql \
    --no-psqlrc \
    --host "${POSTGRES_HOST}" \
    --port "${POSTGRES_PORT}" \
    --username "${role_name}" \
    --dbname "${database_name}" \
    --no-align \
    --tuples-only \
    --set ON_ERROR_STOP=1 \
    --command "$1" \
    | tr -d '\r\n'
}

query_execute() {
  psql \
    --no-psqlrc \
    --host "${POSTGRES_HOST}" \
    --port "${POSTGRES_PORT}" \
    --username "${role_name}" \
    --dbname "${database_name}" \
    --set ON_ERROR_STOP=1 \
    --quiet \
    --command "$1" \
    >/dev/null
}

require_equal() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Migration rehearsal invariant failed: ${label}." >&2
    exit 1
  fi
}

require_scalar() {
  local label="$1"
  local expected="$2"
  local query="$3"
  require_equal "${label}" "${expected}" "$(query_scalar "${query}")"
}

case_fingerprint() {
  query_scalar "
    SELECT count(*)::text || ':' || md5(
      COALESCE(string_agg(md5((to_jsonb(c) - 'source_batch_kind')::text), '' ORDER BY c.id), '')
    )
    FROM exception_case AS c
  "
}

notification_fingerprint() {
  query_scalar "
    SELECT count(*)::text || ':' || md5(
      COALESCE(string_agg(md5(to_jsonb(n)::text), '' ORDER BY n.id), '')
    )
    FROM exception_notification AS n
  "
}

diagnosis_fingerprint() {
  query_scalar "
    SELECT count(*)::text || ':' || md5(
      COALESCE(
        string_agg(
          md5((
            to_jsonb(d) - ARRAY[
              'prompt_version', 'contract_version', 'provider_request_id',
              'latency_ms', 'prompt_tokens', 'completion_tokens', 'total_tokens'
            ]::text[]
          )::text), '' ORDER BY d.id
        ),
        ''
      )
    )
    FROM exception_diagnosis AS d
  "
}

diagnosis_job_legacy_fingerprint() {
  query_scalar "
    SELECT count(*)::text || ':' || md5(
      COALESCE(
        string_agg(
          md5((
            to_jsonb(j) - ARRAY[
              'cancel_requested_at', 'cancel_requested_by_user_id'
            ]::text[]
          )::text), '' ORDER BY j.id
        ),
        ''
      )
    )
    FROM exception_diagnosis_job AS j
  "
}

background_job_fingerprint() {
  query_scalar "
    SELECT count(*)::text || ':' || md5(
      COALESCE(string_agg(md5(to_jsonb(j)::text), '' ORDER BY j.id), '')
    )
    FROM exception_background_job AS j
  "
}

event_fingerprint() {
  query_scalar "
    SELECT count(*)::text || ':' || md5(
      COALESCE(string_agg(md5(to_jsonb(e)::text), '' ORDER BY e.id), '')
    )
    FROM exception_event AS e
  "
}

policy_legacy_fingerprint() {
  query_scalar "
    SELECT count(*)::text || ':' || md5(
      COALESCE(
        string_agg(
          md5((
            to_jsonb(p) - ARRAY[
              'settings_json', 'manual_ai_enabled', 'scheduled_ai_enabled',
              'full_scan_enabled', 'digest_enabled', 'manual_ai_daily_limit',
              'scheduled_ai_daily_limit', 'scheduled_ai_batch_limit'
            ]::text[]
          )::text), '' ORDER BY p.id
        ),
        ''
      )
    )
    FROM exception_policy AS p
  "
}

policy_settings_fingerprint() {
  query_scalar "
    SELECT count(*)::text || ':' || md5(
      COALESCE(
        string_agg(
          md5(jsonb_build_object('id', p.id, 'settings_json', p.settings_json)::text),
          '' ORDER BY p.id
        ),
        ''
      )
    )
    FROM exception_policy AS p
  "
}

policy_controls_fingerprint() {
  query_scalar "
    SELECT count(*)::text || ':' || md5(
      COALESCE(
        string_agg(
          md5(jsonb_build_object(
            'id', p.id,
            'manual_ai_enabled', p.manual_ai_enabled,
            'scheduled_ai_enabled', p.scheduled_ai_enabled,
            'full_scan_enabled', p.full_scan_enabled,
            'digest_enabled', p.digest_enabled,
            'manual_ai_daily_limit', p.manual_ai_daily_limit,
            'scheduled_ai_daily_limit', p.scheduled_ai_daily_limit,
            'scheduled_ai_batch_limit', p.scheduled_ai_batch_limit,
            'ai_concurrency', p.ai_concurrency
          )::text), '' ORDER BY p.id
        ),
        ''
      )
    )
    FROM exception_policy AS p
  "
}

require_revision() {
  local expected="$1"
  local actual
  actual="$(current_revision)"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Migration rehearsal revision mismatch: expected ${expected}, found ${actual:-none}." >&2
    exit 1
  fi
}

run_alembic() {
  (
    cd "${APP_ROOT}/backend"
    DATABASE_URL="${database_url}" "${PYTHON}" -m alembic -c "${ALEMBIC_INI}" "$@"
  )
}

echo "Restored isolated production backup; verifying starting revision."
require_revision "${START_REVISION}"
require_scalar "exactly one default policy at 0400" "1" \
  "SELECT count(*) FROM exception_policy WHERE policy_key = 'default'"
policy_row_count="$(query_scalar "SELECT count(*) FROM exception_policy")"
baseline_case="$(case_fingerprint)"
baseline_notification="$(notification_fingerprint)"
baseline_diagnosis="$(diagnosis_fingerprint)"
baseline_diagnosis_job="$(diagnosis_job_legacy_fingerprint)"
baseline_background_job="$(background_job_fingerprint)"
baseline_event="$(event_fingerprint)"
baseline_policy_legacy="$(policy_legacy_fingerprint)"
baseline_policy_settings="$(policy_settings_fingerprint)"

echo "Rehearsing ${START_REVISION} -> ${TARGET_REVISION}."
run_alembic upgrade "${TARGET_REVISION}"
require_revision "${TARGET_REVISION}"
require_scalar "typed source-batch backfill" "0" "
  SELECT count(*)
  FROM exception_case
  WHERE (source_batch_id IS NULL) <> (source_batch_kind IS NULL)
     OR source_batch_kind IS DISTINCT FROM CASE
          WHEN source_batch_id IS NULL THEN NULL
          WHEN source_type IN ('latest_inventory_check', 'inventory_check_result')
            THEN 'inventory_check'
          WHEN source_type IN (
            'inventory_anomaly_case', 'inventory_flow_ledger',
            'inventory_snapshot_quality', 'latest_receivable_check',
            'import_batch', 'data_calendar_rule', 'master_link_issue'
          ) THEN 'import'
          ELSE 'legacy'
        END
"
require_scalar "typed source-batch indexes" "2" "
  SELECT count(*)
  FROM pg_indexes
  WHERE schemaname = current_schema()
    AND tablename = 'exception_case'
    AND indexname IN ('ix_exception_case_source_batch_kind', 'ix_exception_case_source_batch_ref')
"
require_scalar "active diagnosis job partial unique index" "1" "
  SELECT count(*)
  FROM pg_class AS index_relation
  JOIN pg_index AS index_metadata ON index_metadata.indexrelid = index_relation.oid
  JOIN pg_class AS table_relation ON table_relation.oid = index_metadata.indrelid
  WHERE table_relation.relname = 'exception_diagnosis_job'
    AND index_relation.relname = 'uq_exception_diagnosis_job_active_case_evidence'
    AND index_metadata.indisunique
    AND index_metadata.indpred IS NOT NULL
"
require_equal "diagnosis job legacy fields preserved on upgrade" \
  "${baseline_diagnosis_job}" "$(diagnosis_job_legacy_fingerprint)"
upgraded_diagnosis_job="$(diagnosis_job_legacy_fingerprint)"
upgraded_background_job="$(background_job_fingerprint)"
query_execute "
  UPDATE exception_policy
  SET manual_ai_enabled = true,
      scheduled_ai_enabled = true,
      full_scan_enabled = true,
      digest_enabled = true,
      manual_ai_daily_limit = 11,
      scheduled_ai_daily_limit = 7,
      scheduled_ai_batch_limit = 13
  WHERE policy_key = 'default'
"
expected_policy_controls="$(policy_controls_fingerprint)"

echo "Rehearsing ${TARGET_REVISION} -> ${START_REVISION}."
run_alembic downgrade "${START_REVISION}"
require_revision "${START_REVISION}"
require_equal "exception_case 0400 round trip" "${baseline_case}" "$(case_fingerprint)"
require_equal "exception_notification occurrence/archive round trip" \
  "${baseline_notification}" "$(notification_fingerprint)"
require_equal "exception_diagnosis feedback round trip" \
  "${baseline_diagnosis}" "$(diagnosis_fingerprint)"
require_equal "exception_diagnosis_job full legacy round trip" \
  "${baseline_diagnosis_job}" "$(diagnosis_job_legacy_fingerprint)"
require_equal "exception_background_job full round trip" \
  "${baseline_background_job}" "$(background_job_fingerprint)"
require_equal "exception_event 0400 round trip" "${baseline_event}" "$(event_fingerprint)"
require_equal "exception_policy legacy fields round trip" \
  "${baseline_policy_legacy}" "$(policy_legacy_fingerprint)"
require_scalar "0400 occurrence, feedback, and archive columns retained" "10" "
  SELECT count(*)
  FROM information_schema.columns
  WHERE table_schema = current_schema()
    AND (table_name, column_name) IN (
      ('exception_case', 'occurrence_type'),
      ('exception_case', 'occurrence_cycle'),
      ('exception_case', 'rule_version'),
      ('exception_notification', 'occurrence_cycle'),
      ('exception_notification', 'archived_at'),
      ('exception_notification', 'archive_reason'),
      ('exception_diagnosis', 'feedback_rating'),
      ('exception_diagnosis', 'feedback_note'),
      ('exception_diagnosis', 'feedback_by_user_id'),
      ('exception_diagnosis', 'feedback_at')
    )
"
require_scalar "policy downgrade snapshots" "${policy_row_count}" "
  SELECT count(*)
  FROM exception_policy
  WHERE settings_json ? 'migration_20260729_0500_policy'
"
require_scalar "default policy non-default snapshot" "1" "
  SELECT count(*)
  FROM exception_policy
  WHERE policy_key = 'default'
    AND (settings_json -> 'migration_20260729_0500_policy' ->> 'manual_ai_enabled')::boolean
    AND (settings_json -> 'migration_20260729_0500_policy' ->> 'scheduled_ai_enabled')::boolean
    AND (settings_json -> 'migration_20260729_0500_policy' ->> 'full_scan_enabled')::boolean
    AND (settings_json -> 'migration_20260729_0500_policy' ->> 'digest_enabled')::boolean
    AND (settings_json -> 'migration_20260729_0500_policy' ->> 'manual_ai_daily_limit')::integer = 11
    AND (settings_json -> 'migration_20260729_0500_policy' ->> 'scheduled_ai_daily_limit')::integer = 7
    AND (settings_json -> 'migration_20260729_0500_policy' ->> 'scheduled_ai_batch_limit')::integer = 13
"

echo "Rehearsing final ${START_REVISION} -> ${TARGET_REVISION}."
run_alembic upgrade "${TARGET_REVISION}"
require_revision "${TARGET_REVISION}"
require_equal "exception_case final round trip" "${baseline_case}" "$(case_fingerprint)"
require_equal "exception_notification final round trip" \
  "${baseline_notification}" "$(notification_fingerprint)"
require_equal "exception_diagnosis final round trip" \
  "${baseline_diagnosis}" "$(diagnosis_fingerprint)"
require_equal "exception_diagnosis_job final upgraded state" \
  "${upgraded_diagnosis_job}" "$(diagnosis_job_legacy_fingerprint)"
require_equal "exception_background_job final upgraded state" \
  "${upgraded_background_job}" "$(background_job_fingerprint)"
require_equal "exception_event final round trip" "${baseline_event}" "$(event_fingerprint)"
require_equal "exception_policy legacy fields final round trip" \
  "${baseline_policy_legacy}" "$(policy_legacy_fingerprint)"
require_equal "exception_policy settings restored" \
  "${baseline_policy_settings}" "$(policy_settings_fingerprint)"
require_equal "exception_policy controls restored" \
  "${expected_policy_controls}" "$(policy_controls_fingerprint)"
require_scalar "policy migration snapshots cleaned" "0" "
  SELECT count(*)
  FROM exception_policy
  WHERE settings_json ? 'migration_20260729_0500_policy'
"
require_scalar "final typed source-batch backfill" "0" "
  SELECT count(*)
  FROM exception_case
  WHERE (source_batch_id IS NULL) <> (source_batch_kind IS NULL)
     OR source_batch_kind NOT IN ('import', 'inventory_check', 'legacy')
"
require_scalar "final active diagnosis job partial unique index" "1" "
  SELECT count(*)
  FROM pg_class AS index_relation
  JOIN pg_index AS index_metadata ON index_metadata.indexrelid = index_relation.oid
  WHERE index_relation.relname = 'uq_exception_diagnosis_job_active_case_evidence'
    AND index_metadata.indisunique
    AND index_metadata.indpred IS NOT NULL
"
printf '%s\n' \
  "Migration rehearsal passed; isolated database and role will now be removed." \
  "Evidence case=${baseline_case} notification=${baseline_notification}" \
  "Evidence diagnosis=${baseline_diagnosis} event=${baseline_event}" \
  "Evidence diagnosis_job=${baseline_diagnosis_job} background_job=${baseline_background_job}" \
  "Evidence policy_legacy=${baseline_policy_legacy} policy_controls=${expected_policy_controls}"
