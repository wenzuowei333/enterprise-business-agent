#!/usr/bin/env bash
set -euo pipefail
umask 0077

APP_ROOT="${1:-/opt/enterprise-business-agent}"
BACKUP_DIR="${2:-}"
START_REVISION="20260728_0400"
TARGET_REVISION="20260729_0500"
EXPECTED_PREVIOUS_SOURCE_REVISION="${EXPECTED_PREVIOUS_SOURCE_REVISION:-}"
EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION:-}"
EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256="${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256:-}"
EXPECTED_TARGET_SOURCE_REVISION="${EXPECTED_TARGET_SOURCE_REVISION:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this migration wrapper as root." >&2
  exit 1
fi
if [[ -z "${BACKUP_DIR}" ]]; then
  echo "Usage: $0 APP_ROOT RELEASE_BACKUP_DIR" >&2
  exit 2
fi
for command_name in readlink sha256sum systemctl; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Missing migration dependency: ${command_name}" >&2
    exit 1
  }
done
if ! [[ "${EXPECTED_PREVIOUS_SOURCE_REVISION}" =~ ^[A-Za-z0-9._/-]{1,128}$ ]] \
  || ! [[ "${EXPECTED_TARGET_SOURCE_REVISION}" =~ ^[A-Za-z0-9._/-]{1,128}$ ]] \
  || [[ "${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" != "${START_REVISION}" ]] \
  || ! [[ "${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256}" =~ ^[A-Fa-f0-9]{64}$ ]]; then
  echo "Approved previous/target source revisions, previous Alembic revision, and manifest digest are required." >&2
  exit 2
fi

APP_ROOT="$(cd "${APP_ROOT}" && pwd -P)"
BACKUP_DIR="$(readlink -f "${BACKUP_DIR}" 2>/dev/null || true)"
PYTHON="${APP_ROOT}/.venv/bin/python"
ALEMBIC_INI="${APP_ROOT}/backend/alembic.ini"
METADATA="${BACKUP_DIR}/release-backup.env"
BACKUP_ALEMBIC_REVISION_FILE="${BACKUP_DIR}/database/alembic-revision.txt"
SOURCE_REVISION_FILE="${APP_ROOT}/SOURCE_REVISION"

if [[ -z "${BACKUP_DIR}" || ! -d "${BACKUP_DIR}" ]] \
  || [[ "$(stat -c '%U:%G:%a' "${BACKUP_DIR}")" != "root:root:700" ]]; then
  echo "Release backup is missing or does not use root:root mode 700." >&2
  exit 1
fi
for path in \
  "${BACKUP_DIR}/SHA256SUMS" \
  "${METADATA}" \
  "${BACKUP_ALEMBIC_REVISION_FILE}" \
  "${SOURCE_REVISION_FILE}" \
  "${ALEMBIC_INI}"; do
  [[ -f "${path}" ]] || {
    echo "Missing required migration artifact: ${path}" >&2
    exit 1
  }
done
[[ -x "${PYTHON}" ]] || {
  echo "Application Python is unavailable." >&2
  exit 1
}
(
  cd "${BACKUP_DIR}"
  sha256sum --check --quiet SHA256SUMS
)
manifest_digest="$(sha256sum "${BACKUP_DIR}/SHA256SUMS" | awk '{print $1}')"
if [[ "${manifest_digest,,}" != "${EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256,,}" ]]; then
  echo "Release backup manifest does not match the approved pre-sync digest." >&2
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
  ' "${METADATA}"
}
backup_source_revision="$(metadata_value SOURCE_REVISION)"
backup_database_revision="$(metadata_value DATABASE_ALEMBIC_REVISION)"
backup_revision_file_value="$(tr -d '\r\n' < "${BACKUP_ALEMBIC_REVISION_FILE}")"
if [[ "${backup_source_revision}" != "${EXPECTED_PREVIOUS_SOURCE_REVISION}" ]] \
  || [[ "${backup_database_revision}" != "${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" ]] \
  || [[ "${backup_revision_file_value}" != "${backup_database_revision}" ]] \
  || [[ "${backup_revision_file_value}" != "${START_REVISION}" ]] \
  || [[ "$(tr -d '\r\n' < "${SOURCE_REVISION_FILE}")" != "${EXPECTED_TARGET_SOURCE_REVISION}" ]]; then
  echo "Code, backup, or database baseline revision is not the approved release pair." >&2
  exit 1
fi

services=(
  enterprise-business-agent-exception-worker.service
  enterprise-business-agent-exception-ai-worker.service
  enterprise-business-agent-exception-scheduler.service
)
declare -A previous_active=()
declare -A previous_loaded=()
loaded_services=()
for service in "${services[@]}"; do
  if systemctl cat "${service}" >/dev/null 2>&1; then
    previous_loaded["${service}"]=true
    loaded_services+=("${service}")
  else
    previous_loaded["${service}"]=false
  fi
  if [[ "${previous_loaded[${service}]}" == "true" ]] \
    && systemctl is-active --quiet "${service}"; then
    previous_active["${service}"]=true
  else
    previous_active["${service}"]=false
  fi
done

restore_services() {
  local original_status="$?"
  local restore_failed=0
  trap - EXIT INT TERM
  set +e
  for service in "${services[@]}"; do
    if [[ "${previous_loaded[${service}]}" != "true" ]]; then
      continue
    fi
    if [[ "${previous_active[${service}]}" == "true" ]]; then
      systemctl start "${service}" || restore_failed=1
    else
      systemctl stop "${service}" >/dev/null 2>&1 || true
    fi
  done
  if (( restore_failed != 0 )); then
    echo "Migration service-state restoration failed; keep the release blocked." >&2
    (( original_status == 0 )) && original_status=1
  fi
  exit "${original_status}"
}
trap restore_services EXIT
trap 'exit 130' INT TERM

if (( ${#loaded_services[@]} > 0 )); then
  systemctl stop "${loaded_services[@]}"
fi
for service in "${loaded_services[@]}"; do
  if systemctl is-active --quiet "${service}"; then
    echo "${service} did not stop before migration." >&2
    exit 1
  fi
done

cd "${APP_ROOT}"
PYTHONPATH="${APP_ROOT}/backend" "${PYTHON}" - "${START_REVISION}" <<'PY'
from __future__ import annotations

import sys

from sqlalchemy import text

from app.core.database import engine

expected_revision = sys.argv[1]
with engine.connect() as connection:
    revisions = [str(row[0]) for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
    diagnosis_processing = int(
        connection.scalar(
            text("SELECT count(*) FROM exception_diagnosis_job WHERE status = 'processing'")
        )
        or 0
    )
    background_processing = int(
        connection.scalar(
            text("SELECT count(*) FROM exception_background_job WHERE status = 'processing'")
        )
        or 0
    )
if revisions != [expected_revision]:
    raise SystemExit("production database is not at the approved starting revision")
if diagnosis_processing or background_processing:
    raise SystemExit(
        "processing leases remain after exception services stopped: "
        f"diagnosis={diagnosis_processing} background={background_processing}"
    )
print("Migration quiescence confirmed: diagnosis_processing=0 background_processing=0")
PY

(
  cd "${APP_ROOT}/backend"
  "${PYTHON}" -m alembic -c "${ALEMBIC_INI}" upgrade "${TARGET_REVISION}"
)
PYTHONPATH="${APP_ROOT}/backend" "${PYTHON}" - "${TARGET_REVISION}" <<'PY'
from __future__ import annotations

import sys

from sqlalchemy import text

from app.core.database import engine

with engine.connect() as connection:
    revisions = [str(row[0]) for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
if revisions != [sys.argv[1]]:
    raise SystemExit("production migration did not reach the target revision")
print(f"Production migration reached {sys.argv[1]}")
PY
