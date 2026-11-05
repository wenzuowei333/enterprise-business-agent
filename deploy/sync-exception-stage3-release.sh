#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 dry-run|apply CANDIDATE_ROOT TARGET_ROOT" >&2
}

if [[ "$#" -ne 3 ]]; then
  usage
  exit 2
fi

MODE="$1"
CANDIDATE_ROOT="$2"
TARGET_ROOT="$3"
EXPECTED_TARGET_SOURCE_REVISION="${EXPECTED_TARGET_SOURCE_REVISION:-}"
EXPECTED_SYNC_PLAN_SHA256="${EXPECTED_SYNC_PLAN_SHA256:-}"

if [[ "${MODE}" != "dry-run" && "${MODE}" != "apply" ]]; then
  usage
  exit 2
fi
if ! [[ "${EXPECTED_TARGET_SOURCE_REVISION}" =~ ^[A-Za-z0-9._/-]{1,128}$ ]]; then
  echo "EXPECTED_TARGET_SOURCE_REVISION must identify the approved candidate revision." >&2
  exit 2
fi
for command_name in awk cat find grep mktemp readlink rm rsync sha256sum tr; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing release sync dependency: ${command_name}" >&2
    exit 1
  fi
done

CANDIDATE_ROOT="$(readlink -f "${CANDIDATE_ROOT}" 2>/dev/null || true)"
TARGET_ROOT="$(readlink -f "${TARGET_ROOT}" 2>/dev/null || true)"
if [[ -z "${CANDIDATE_ROOT}" || -z "${TARGET_ROOT}" ]] \
  || [[ ! -d "${CANDIDATE_ROOT}" || ! -d "${TARGET_ROOT}" ]] \
  || [[ "${CANDIDATE_ROOT}" == "/" || "${TARGET_ROOT}" == "/" ]] \
  || [[ "${CANDIDATE_ROOT}" == "${TARGET_ROOT}" ]]; then
  echo "Candidate and target must be distinct existing non-root directories." >&2
  exit 1
fi
if [[ "${CANDIDATE_ROOT}/" == "${TARGET_ROOT}/"* ]] \
  || [[ "${TARGET_ROOT}/" == "${CANDIDATE_ROOT}/"* ]]; then
  echo "Candidate and target directories must not contain one another." >&2
  exit 1
fi
if [[ -e "${CANDIDATE_ROOT}/.venv" || -L "${CANDIDATE_ROOT}/.venv" ]]; then
  echo "Candidate root must not contain a .venv entry or symbolic link." >&2
  exit 1
fi
candidate_cache_entry="$(
  find "${CANDIDATE_ROOT}" \
    \( -name __pycache__ -o -name '*.pyc' -o -name '*.pyo' \) \
    -print -quit
)"
if [[ -n "${candidate_cache_entry}" ]]; then
  echo "Candidate root must not contain Python bytecode or __pycache__ entries." >&2
  exit 1
fi
if [[ ! -f "${CANDIDATE_ROOT}/SOURCE_REVISION" ]]; then
  echo "Candidate SOURCE_REVISION is missing." >&2
  exit 1
fi
candidate_revision="$(tr -d '\r\n' < "${CANDIDATE_ROOT}/SOURCE_REVISION")"
if [[ "${candidate_revision}" != "${EXPECTED_TARGET_SOURCE_REVISION}" ]]; then
  echo "Candidate SOURCE_REVISION does not match the approved target revision." >&2
  exit 1
fi

# This list is the release sync contract. Callers cannot append or override filters.
readonly -a RSYNC_ARGS=(
  --archive
  --no-owner
  --no-group
  --no-perms
  --no-times
  --omit-dir-times
  --checksum
  --delete
  --itemize-changes
  "--exclude=/.env"
  "--exclude=/.venv/"
  "--exclude=/runtime/"
  "--exclude=/uploads/"
  "--exclude=/attachments/"
  "--exclude=/reports/"
  "--exclude=/backups/"
  "--exclude=/output/"
  "--exclude=/outputs/"
  "--exclude=/android/signing.properties"
  "--exclude=/android/local.properties"
  "--exclude=/android/*.jks"
  "--exclude=/android/*.keystore"
  "--exclude=/backend/app/static/downloads/"
)

plan_file="$(mktemp)"
cleanup() {
  rm -f -- "${plan_file}"
}
trap cleanup EXIT

LC_ALL=C rsync "${RSYNC_ARGS[@]}" --dry-run -- \
  "${CANDIDATE_ROOT}/" "${TARGET_ROOT}/" \
  | sed -E 's/^rsync\([0-9]+\): /rsync: /' \
  > "${plan_file}"

# A second guard keeps protected paths out of an approved plan even if filters drift.
protected_delete_pattern='^\*deleting[[:space:]]+(\.env($|/)|\.venv($|/)|runtime($|/)|uploads($|/)|attachments($|/)|reports($|/)|backups($|/)|output($|/)|outputs($|/)|android/signing\.properties$|android/local\.properties$|android/[^/]+\.(jks|keystore)$|backend/app/static/downloads($|/))'
if grep -Eq "${protected_delete_pattern}" "${plan_file}"; then
  echo "Release sync plan attempts to delete a protected production path." >&2
  exit 1
fi

plan_sha256="$(sha256sum "${plan_file}" | awk '{ print $1 }')"
if [[ "${MODE}" == "dry-run" ]]; then
  cat "${plan_file}"
  echo "SYNC_PLAN_SHA256=${plan_sha256}" >&2
  exit 0
fi

if ! [[ "${EXPECTED_SYNC_PLAN_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "EXPECTED_SYNC_PLAN_SHA256 is required for apply mode." >&2
  exit 2
fi
if [[ "${plan_sha256}" != "${EXPECTED_SYNC_PLAN_SHA256}" ]]; then
  echo "Current sync plan does not match the reviewed dry-run plan." >&2
  exit 1
fi

LC_ALL=C rsync "${RSYNC_ARGS[@]}" -- \
  "${CANDIDATE_ROOT}/" "${TARGET_ROOT}/"
if [[ ! -f "${TARGET_ROOT}/SOURCE_REVISION" ]] \
  || [[ "$(tr -d '\r\n' < "${TARGET_ROOT}/SOURCE_REVISION")" != "${EXPECTED_TARGET_SOURCE_REVISION}" ]]; then
  echo "Synchronized target does not contain the approved SOURCE_REVISION." >&2
  exit 1
fi
