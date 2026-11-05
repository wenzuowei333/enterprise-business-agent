#!/usr/bin/env bash
set -euo pipefail
umask 0077

APP_ROOT="${APP_ROOT:-/opt/enterprise-business-agent}"
OBSERVATION_FILE="${OBSERVATION_FILE:-/var/lib/enterprise-business-agent-exception-release/dark-observation.json}"
METRICS_FILE="${OBSERVATION_METRICS_FILE:-/run/enterprise-business-agent-exception-observer-metrics/latest.json}"
OBSERVER_GROUP="${OBSERVER_GROUP:-handmade-exception-observer}"
PYTHON="${APP_ROOT}/.venv/bin/python"
AUDIT="${APP_ROOT}/scripts/verify_exception_stage3_runtime.py"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Observation metrics collector must run as root." >&2
  exit 1
fi
if [[ ! -f "${OBSERVATION_FILE}" ]]; then
  echo "Observation baseline is missing." >&2
  exit 1
fi
if [[ ! -d "$(dirname "${METRICS_FILE}")" ]]; then
  echo "Root-owned observation metrics runtime directory is missing." >&2
  exit 1
fi

mapfile -t observation_identity < <("${PYTHON}" - "${OBSERVATION_FILE}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
deployed_at = payload.get("deployed_at")
expected_revision = payload.get("expected_revision")
if not isinstance(deployed_at, str) or not deployed_at:
    raise SystemExit("observation baseline has no deployed_at timestamp")
if (
    not isinstance(expected_revision, str)
    or not expected_revision
    or len(expected_revision) > 128
    or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for character in expected_revision)
):
    raise SystemExit("observation baseline has no valid expected_revision")
print(deployed_at)
print(expected_revision)
PY
)
if [[ "${#observation_identity[@]}" -ne 2 ]]; then
  echo "Observation baseline identity is incomplete." >&2
  exit 1
fi
dark_since="${observation_identity[0]}"
expected_revision="${observation_identity[1]}"

# The privileged helper emits only a cumulative scalar. It never copies journal text.
http_5xx_count="$(
  journalctl --unit enterprise-business-agent.service --since "${dark_since}" --no-pager --output cat \
    | awk '/HTTP\/[0-9.]+" 5[0-9][0-9]([[:space:]]|$)/ { count += 1 } END { print count + 0 }'
)"

rm -f "${METRICS_FILE}"
set +e
"${PYTHON}" "${AUDIT}" \
  --mode dark \
  --expected-revision "${expected_revision}" \
  --dark-since "${dark_since}" \
  --observation-file "${OBSERVATION_FILE}" \
  --write-observation-metrics "${METRICS_FILE}" \
  --http-5xx-count "${http_5xx_count}"
collector_status=$?
set -e
if [[ -f "${METRICS_FILE}" ]]; then
  chown root:"${OBSERVER_GROUP}" "${METRICS_FILE}"
  chmod 0640 "${METRICS_FILE}"
fi
exit "${collector_status}"
