#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${1:-/opt/enterprise-business-agent}"
BACKUP_ROOT="${2:-/var/backups/enterprise-business-agent-releases}"
MAX_CODE_ARCHIVE_BYTES="${MAX_CODE_ARCHIVE_BYTES:-268435456}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi
if ! [[ "${MAX_CODE_ARCHIVE_BYTES}" =~ ^[1-9][0-9]*$ ]]; then
  echo "MAX_CODE_ARCHIVE_BYTES must be a positive integer." >&2
  exit 2
fi

APP_ROOT="$(cd "${APP_ROOT}" && pwd -P)"
ENV_FILE="${APP_ROOT}/.env"
PYTHON="${APP_ROOT}/.venv/bin/python"

for command_name in tar pg_dump pg_restore psql sha256sum systemctl; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing backup dependency: ${command_name}" >&2
    exit 1
  fi
done
if [[ ! -f "${ENV_FILE}" ]] || [[ "$(stat -c '%a' "${ENV_FILE}")" != "600" ]]; then
  echo "${ENV_FILE} must exist and use mode 600." >&2
  exit 1
fi
if [[ ! -x "${PYTHON}" ]]; then
  echo "Application Python is missing: ${PYTHON}" >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
partial_dir="${BACKUP_ROOT}/.${timestamp}-$$.partial"
backup_dir="${BACKUP_ROOT}/${timestamp}-$$"
install -d -o root -g root -m 0700 "${BACKUP_ROOT}"
install -d -o root -g root -m 0700 \
  "${partial_dir}" "${partial_dir}/database" "${partial_dir}/environment" "${partial_dir}/units"

cleanup_partial() {
  local status="$?"
  if (( status != 0 )); then
    echo "Backup failed; incomplete evidence was retained at ${partial_dir}." >&2
  fi
}
trap cleanup_partial EXIT
trap 'exit 130' INT TERM

app_parent="$(dirname "${APP_ROOT}")"
app_name="$(basename "${APP_ROOT}")"
tar --create --gzip --file "${partial_dir}/code.tar.gz" \
  --directory "${app_parent}" \
  --exclude="${app_name}/.env" \
  --exclude="${app_name}/.venv" \
  --exclude="${app_name}/.git" \
  --exclude="${app_name}/.codex-remote-attachments" \
  --exclude="${app_name}/runtime" \
  --exclude="${app_name}/uploads" \
  --exclude="${app_name}/attachments" \
  --exclude="${app_name}/reports" \
  --exclude="${app_name}/backups" \
  --exclude="${app_name}/output" \
  --exclude="${app_name}/outputs" \
  --exclude="${app_name}/frontend/node_modules" \
  --exclude="${app_name}/frontend/playwright-report" \
  --exclude="${app_name}/frontend/test-results" \
  --exclude="${app_name}/android/.gradle" \
  --exclude="${app_name}/android/app/build" \
  --exclude="${app_name}/.pytest_cache" \
  --exclude="${app_name}/.ruff_cache" \
  --exclude="*/__pycache__" \
  --exclude="*.py[co]" \
  "${app_name}"
tar --list --gzip --file "${partial_dir}/code.tar.gz" >/dev/null
code_archive_bytes="$(stat -c '%s' "${partial_dir}/code.tar.gz")"
if (( code_archive_bytes > MAX_CODE_ARCHIVE_BYTES )); then
  echo "Code archive exceeds MAX_CODE_ARCHIVE_BYTES: ${code_archive_bytes}." >&2
  exit 1
fi
"${PYTHON}" - "${partial_dir}/code.tar.gz" "${app_name}" <<'PY'
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

install -o root -g root -m 0600 "${ENV_FILE}" "${partial_dir}/environment/application.env"

"${PYTHON}" - \
  "${ENV_FILE}" \
  "${partial_dir}/database/postgresql.dump" \
  "${partial_dir}/database/alembic-revision.txt" <<'PY'
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url


def read_database_url(path: Path) -> str:
    matches: list[str] = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if separator and key.strip() == "DATABASE_URL":
            parsed = shlex.split(value, posix=True)
            matches.append(parsed[0] if len(parsed) == 1 else value.strip())
    if len(matches) != 1 or not matches[0]:
        raise SystemExit(".env must contain exactly one non-empty DATABASE_URL")
    return matches[0]


env_path = Path(sys.argv[1])
destination = Path(sys.argv[2])
revision_destination = Path(sys.argv[3])
url = make_url(read_database_url(env_path))
if not url.database:
    raise SystemExit("DATABASE_URL does not identify a database")

environment = os.environ.copy()
for key in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSSLMODE"):
    environment.pop(key, None)
if url.host:
    environment["PGHOST"] = url.host
if url.port:
    environment["PGPORT"] = str(url.port)
if url.username:
    environment["PGUSER"] = url.username
if url.password:
    environment["PGPASSWORD"] = url.password
environment["PGDATABASE"] = url.database
if url.query.get("sslmode"):
    environment["PGSSLMODE"] = str(url.query["sslmode"])

subprocess.run(
    ["pg_dump", "--format=custom", "--no-password", "--file", str(destination)],
    check=True,
    env=environment,
)
revision_result = subprocess.run(
    [
        "psql",
        "--no-psqlrc",
        "--no-password",
        "--no-align",
        "--tuples-only",
        "--command",
        "SELECT version_num FROM alembic_version ORDER BY version_num",
    ],
    check=True,
    capture_output=True,
    text=True,
    env=environment,
)
revisions = [line.strip() for line in revision_result.stdout.splitlines() if line.strip()]
if len(revisions) != 1 or not revisions[0].replace("_", "").isalnum():
    raise SystemExit("database must contain exactly one safe Alembic revision")
revision_destination.write_text(f"{revisions[0]}\n", encoding="ascii")
PY
pg_restore --list "${partial_dir}/database/postgresql.dump" >/dev/null
database_dump_bytes="$(stat -c '%s' "${partial_dir}/database/postgresql.dump")"

units=(
  enterprise-business-agent.service
  enterprise-business-agent-exception-worker.service
  enterprise-business-agent-exception-ai-worker.service
  enterprise-business-agent-exception-scheduler.service
  enterprise-business-agent-exception-observer-metrics.service
  enterprise-business-agent-exception-observer.service
  enterprise-business-agent-exception-observer.timer
)
for unit in "${units[@]}"; do
  if systemctl cat "${unit}" >/dev/null 2>&1; then
    systemctl cat "${unit}" > "${partial_dir}/units/${unit}.effective"
    systemctl show "${unit}" \
      --property=FragmentPath,DropInPaths,LoadState,UnitFileState,ActiveState \
      > "${partial_dir}/units/${unit}.state"
    fragment_path="$(systemctl show "${unit}" --property=FragmentPath --value)"
    if [[ -n "${fragment_path}" && -f "${fragment_path}" ]]; then
      cp --archive "${fragment_path}" "${partial_dir}/units/${unit}.fragment"
    fi
    dropin_index=0
    while IFS= read -r dropin_path; do
      if [[ -n "${dropin_path}" && -f "${dropin_path}" ]]; then
        dropin_index=$((dropin_index + 1))
        cp --archive "${dropin_path}" \
          "${partial_dir}/units/${unit}.dropin-${dropin_index}.conf"
      fi
    done < <(systemctl show "${unit}" --property=DropInPaths --value | tr ' ' '\n')
  fi
done

if [[ ! -f "${APP_ROOT}/SOURCE_REVISION" ]]; then
  echo "SOURCE_REVISION is required before a release backup can be trusted." >&2
  exit 1
fi
source_revision="$(tr -d '\r\n' < "${APP_ROOT}/SOURCE_REVISION")"
if ! [[ "${source_revision}" =~ ^[A-Za-z0-9._/-]{1,128}$ ]]; then
  echo "SOURCE_REVISION contains an unsafe or unsupported value." >&2
  exit 1
fi
database_alembic_revision="$(tr -d '\r\n' < "${partial_dir}/database/alembic-revision.txt")"
if ! [[ "${database_alembic_revision}" =~ ^[A-Za-z0-9_]{1,128}$ ]]; then
  echo "Database Alembic revision is unsafe or missing." >&2
  exit 1
fi

cat > "${partial_dir}/release-backup.env" <<EOF
BACKUP_FORMAT_VERSION=2
CREATED_AT_UTC=$(date -u --iso-8601=seconds)
APP_ROOT=${APP_ROOT}
SOURCE_REVISION=${source_revision}
DATABASE_ALEMBIC_REVISION=${database_alembic_revision}
CODE_ARCHIVE=code.tar.gz
CODE_ARCHIVE_BYTES=${code_archive_bytes}
CODE_ARCHIVE_LIMIT_BYTES=${MAX_CODE_ARCHIVE_BYTES}
DATABASE_DUMP=database/postgresql.dump
DATABASE_DUMP_BYTES=${database_dump_bytes}
ENV_SNAPSHOT=environment/application.env
EOF

(
  cd "${partial_dir}"
  find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS
  sha256sum --check SHA256SUMS >/dev/null
)
chmod -R go-rwx "${partial_dir}"
mv "${partial_dir}" "${backup_dir}"
trap - EXIT INT TERM

manifest_digest="$(sha256sum "${backup_dir}/SHA256SUMS" | awk '{print $1}')"
printf 'Release backup: %s\nSource revision: %s\nAlembic revision: %s\nSHA256SUMS digest: %s\n' \
  "${backup_dir}" "${source_revision}" "${database_alembic_revision}" "${manifest_digest}"
