#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/enterprise-business-agent}"
OBSERVATION_FILE="${OBSERVATION_FILE:-/var/lib/enterprise-business-agent-exception-release/dark-observation.json}"
METRICS_FILE="${OBSERVATION_METRICS_FILE:-/run/enterprise-business-agent-exception-observer-metrics/latest.json}"
PYTHON="${APP_ROOT}/.venv/bin/python"
AUDIT="${APP_ROOT}/scripts/verify_exception_stage3_runtime.py"

if [[ ! -f "${OBSERVATION_FILE}" || ! -f "${METRICS_FILE}" ]]; then
  echo "Observation baseline is missing: ${OBSERVATION_FILE}" >&2
  exit 1
fi

expected_revision="$("${PYTHON}" - "${OBSERVATION_FILE}" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("expected_revision")
if (
    not isinstance(value, str)
    or not value
    or len(value) > 128
    or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for character in value)
):
    raise SystemExit("observation baseline has no valid expected_revision")
print(value)
PY
)"

exec "${PYTHON}" "${AUDIT}" \
  --expected-revision "${expected_revision}" \
  --observation-file "${OBSERVATION_FILE}" \
  --consume-observation-metrics "${METRICS_FILE}"
