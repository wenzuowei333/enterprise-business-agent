#!/usr/bin/env bash
set -euo pipefail

BASE_IMAGE="${BASE_IMAGE:-}"
OUTPUT_IMAGE="${OUTPUT_IMAGE:-localhost/enterprise-business-agent-remediation-sandbox:20260902}"
if [[ ! "$BASE_IMAGE" =~ @sha256:[0-9a-fA-F]{64}$ ]]; then
  echo "BASE_IMAGE must be an immutable image reference ending in @sha256:<64 hex>" >&2
  exit 2
fi
command -v podman >/dev/null || { echo "podman is required" >&2; exit 3; }
bash -n deploy/remediation-sandbox/remediation-sandbox

podman build --pull=never --build-arg "BASE_IMAGE=$BASE_IMAGE" -t "$OUTPUT_IMAGE" deploy/remediation-sandbox
digest="$(podman image inspect "$OUTPUT_IMAGE" --format '{{.Digest}}')"
[[ "$digest" =~ ^sha256:[0-9a-fA-F]{64}$ ]] || { echo "built image has no immutable digest" >&2; exit 4; }

run_canary() {
  local language="$1"
  local candidate="$2"
  printf '%s\n' "$candidate" | podman run \
    --rm \
    --network=none \
    --pull=never \
    --read-only \
    --ipc=private \
    --uts=private \
    --cap-drop=ALL \
    --security-opt=no-new-privileges \
    --pids-limit=64 \
    --memory=256m \
    --cpus=1 \
    --tmpfs=/tmp:rw,noexec,nosuid,size=64m \
    --user=65534:65534 \
    -i \
    "$OUTPUT_IMAGE@$digest" \
    /usr/local/bin/remediation-sandbox \
    "$language" \
    >/dev/null
}

run_canary shell 'printf sandbox-shell-ok'
run_canary sql 'SELECT 1;'
run_canary http 'curl -fsS http://127.0.0.1:18080/ >/dev/null'
printf 'AI_REMEDIATION_SANDBOX_IMAGE=%s@%s\n' "$OUTPUT_IMAGE" "$digest"
