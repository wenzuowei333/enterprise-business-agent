#!/usr/bin/env python3
"""Run one audited, synthetic exception-diagnosis provider canary.

The command never creates an exception case and never prints provider content,
credentials, prompts, or evidence. Every imminent HTTP attempt is committed to
``audit_log`` before network access, so it is included in provider-call totals.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CANARY_ACTION_STARTED = "exception_provider_call_started"
CANARY_ACTION_COMPLETED = "exception_provider_canary_completed"
CANARY_ACTION_FAILED = "exception_provider_canary_failed"
CANARY_RESOURCE_TYPE = "exception_provider_canary"
CANARY_ALLOWED_ROOT_CAUSES = ("warehouse_missing",)
_SAFE_RELEASE_RE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
_SAFE_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")

CANARY_EVIDENCE: dict[str, Any] = {
    "kind": "inventory_check",
    "rule_code": "inventory_warehouse_missing",
    "rule_version": "provider-canary.v1",
    "rule_description": "A stock record must identify its warehouse before remediation.",
    "reason": "Synthetic stock evidence has no warehouse mapping.",
    "expected_rule": "warehouse.name must identify exactly one warehouse",
    "recommended_action": "Complete the warehouse mapping, then rerun the inventory check.",
    "resource": {"type": "inventory_snapshot", "id": "CANARY-SNAPSHOT-001"},
    "snapshot_id": "CANARY-SNAPSHOT-001",
    "batch_id": "CANARY-BATCH-001",
    "data_date": "2026-01-01",
    "product": {"code": "CANARY-PRODUCT-001", "name": "Synthetic product"},
    "warehouse": {"name": None, "scope": "unresolved"},
    "observed": {"stock_qty": -2, "locked_qty": 0},
    "metadata": {
        "reason_code": "warehouse_missing",
        "severity": "high",
        "batch_id": "CANARY-BATCH-001",
        "snapshot_ids": ["CANARY-SNAPSHOT-001"],
    },
}


class ProviderCanaryError(RuntimeError):
    """Raised when the provider canary fails a local release contract."""


def _read_source_revision(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not _SAFE_RELEASE_RE.fullmatch(value):
        raise ProviderCanaryError("invalid_source_revision")
    return value


def _safe_error_code(exc: BaseException) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", exc.__class__.__name__)[:80]
    return value or "ProviderCanaryError"


def _provider_request_digest(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _write_canary_audit(
    session_factory: Callable[[], Any],
    *,
    action_type: str,
    canary_id: str,
    detail: dict[str, Any],
) -> None:
    from app.services.audit_service import write_audit_log

    with session_factory() as db:
        write_audit_log(
            db,
            action_type=action_type,
            resource_type=CANARY_RESOURCE_TYPE,
            resource_id=canary_id,
            after_data=detail,
        )
        db.commit()


def _reserve_canary_provider_attempt(
    session_factory: Callable[[], Any],
    *,
    canary_id: str,
    detail: dict[str, Any],
) -> None:
    """Atomically consume one company-wide provider attempt before HTTP access."""
    from sqlalchemy import func, select

    from app.models import AuditLog, ExceptionEvent, ExceptionPolicy
    from app.services.audit_service import write_audit_log

    local_now = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Hong_Kong"))
    local_day_start = datetime(
        local_now.year,
        local_now.month,
        local_now.day,
        tzinfo=ZoneInfo("Asia/Hong_Kong"),
    ).astimezone(timezone.utc)
    with session_factory() as db:
        daily_limit = db.scalar(
            select(ExceptionPolicy.manual_ai_daily_limit)
            .where(ExceptionPolicy.policy_key == "default")
            .with_for_update()
        )
        if not isinstance(daily_limit, int) or isinstance(daily_limit, bool) or daily_limit < 0:
            raise ProviderCanaryError("provider_daily_limit_unavailable")
        diagnosis_attempts = int(
            db.scalar(
                select(func.count())
                .select_from(ExceptionEvent)
                .where(
                    ExceptionEvent.event_type == "diagnosis_ai_call_started",
                    ExceptionEvent.created_at >= local_day_start,
                )
            )
            or 0
        )
        canary_attempts = int(
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.resource_type == CANARY_RESOURCE_TYPE,
                    AuditLog.action_type == CANARY_ACTION_STARTED,
                    AuditLog.created_at >= local_day_start,
                )
            )
            or 0
        )
        if daily_limit > 0 and diagnosis_attempts + canary_attempts >= daily_limit:
            raise ProviderCanaryError("provider_daily_limit_reached")
        write_audit_log(
            db,
            action_type=CANARY_ACTION_STARTED,
            resource_type=CANARY_RESOURCE_TYPE,
            resource_id=canary_id,
            after_data=detail,
        )
        db.commit()


def execute_provider_canary(
    *,
    session_factory: Callable[[], Any] | None = None,
    diagnosis_call: Callable[..., Any] | None = None,
    source_revision_path: Path | None = None,
    attempt_reserver: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Execute the canary and return only safe scalar release evidence."""
    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.services.hermes_ai_service import (
        EXCEPTION_CONTRACT_VERSION,
        EXCEPTION_PROMPT_VERSION,
        ExceptionDiagnosis,
        call_hermes_exception_diagnosis,
        prepare_exception_evidence,
    )

    factory = session_factory or SessionLocal
    provider_call = diagnosis_call or call_hermes_exception_diagnosis
    reserve_attempt = attempt_reserver or _reserve_canary_provider_attempt
    source_revision = _read_source_revision(source_revision_path or ROOT / "SOURCE_REVISION")
    model = settings.hermes_model.strip()
    if not _SAFE_MODEL_RE.fullmatch(model):
        raise ProviderCanaryError("invalid_model_identifier")
    endpoint = urlparse((settings.hermes_api_base_url or "").strip())
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username is not None
        or endpoint.password is not None
    ):
        raise ProviderCanaryError("provider_https_required")
    if not settings.exception_ai_enabled:
        raise ProviderCanaryError("exception_ai_runtime_disabled")

    prepared_evidence, prepared_metadata = prepare_exception_evidence(
        CANARY_EVIDENCE,
        domain="inventory",
    )
    canonical_refs = set(prepared_evidence.get("canonical_evidence_refs") or [])
    if not canonical_refs or prepared_metadata.get("evidence_truncated") is not False:
        raise ProviderCanaryError("invalid_synthetic_evidence")

    canary_id = f"provider-canary-{uuid.uuid4()}"
    request_id = str(uuid.uuid4())
    provider_call_count = 0

    def reserve_provider_attempt(http_attempt: int) -> None:
        nonlocal provider_call_count
        if (
            not isinstance(http_attempt, int)
            or isinstance(http_attempt, bool)
            or http_attempt != provider_call_count + 1
        ):
            raise ProviderCanaryError("non_monotonic_provider_attempt")
        reserve_attempt(
            factory,
            canary_id=canary_id,
            detail={
                "status": "started",
                "trigger_type": "provider_canary",
                "source_revision": source_revision,
                "model": model,
                "prompt_version": EXCEPTION_PROMPT_VERSION,
                "contract_version": EXCEPTION_CONTRACT_VERSION,
                "request_id": request_id,
                "http_attempt": http_attempt,
            },
        )
        provider_call_count += 1

    try:
        result = provider_call(
            CANARY_EVIDENCE,
            domain="inventory",
            allowed_root_cause_codes=list(CANARY_ALLOWED_ROOT_CAUSES),
            request_id=request_id,
            before_http_attempt=reserve_provider_attempt,
            require_complete_usage=True,
        )
        diagnosis = ExceptionDiagnosis.model_validate(result.diagnosis)
        metadata = result.metadata
        if provider_call_count < 1 or metadata.attempts != provider_call_count:
            raise ProviderCanaryError("provider_attempt_audit_mismatch")
        if diagnosis.root_cause_code not in CANARY_ALLOWED_ROOT_CAUSES:
            raise ProviderCanaryError("unsupported_root_cause")
        if not diagnosis.evidence_refs or any(ref not in canonical_refs for ref in diagnosis.evidence_refs):
            raise ProviderCanaryError("invalid_canonical_evidence_reference")
        if metadata.request_id != request_id or metadata.model != model:
            raise ProviderCanaryError("provider_metadata_identity_mismatch")
        if (
            metadata.prompt_version != EXCEPTION_PROMPT_VERSION
            or metadata.contract_version != EXCEPTION_CONTRACT_VERSION
        ):
            raise ProviderCanaryError("provider_contract_version_mismatch")
        usage = (metadata.prompt_tokens, metadata.completion_tokens, metadata.total_tokens)
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in usage):
            raise ProviderCanaryError("provider_usage_incomplete")
        if metadata.total_tokens < metadata.prompt_tokens + metadata.completion_tokens:
            raise ProviderCanaryError("provider_usage_inconsistent")

        completed_detail = {
            "status": "passed",
            "source_revision": source_revision,
            "model": model,
            "prompt_version": EXCEPTION_PROMPT_VERSION,
            "contract_version": EXCEPTION_CONTRACT_VERSION,
            "request_id": request_id,
            "provider_request_id_sha256": _provider_request_digest(metadata.provider_request_id),
            "provider_call_count": provider_call_count,
            "root_cause_code": diagnosis.root_cause_code,
            "schema_valid": True,
            "canonical_evidence_refs_valid": True,
            "safety_guard_passed": True,
            "usage_complete": True,
            "prompt_tokens": metadata.prompt_tokens,
            "completion_tokens": metadata.completion_tokens,
            "total_tokens": metadata.total_tokens,
            "evidence_bytes": metadata.evidence_bytes,
            "evidence_approx_tokens": metadata.evidence_approx_tokens,
            "evidence_truncated": metadata.evidence_truncated,
        }
        _write_canary_audit(
            factory,
            action_type=CANARY_ACTION_COMPLETED,
            canary_id=canary_id,
            detail=completed_detail,
        )
        return {
            "ok": True,
            "canary_id": canary_id,
            "request_id": request_id,
            "source_revision": source_revision,
            "provider_call_count": provider_call_count,
            "root_cause_code": diagnosis.root_cause_code,
            "usage_complete": True,
            "total_tokens": metadata.total_tokens,
            "schema_valid": True,
            "canonical_evidence_refs_valid": True,
            "safety_guard_passed": True,
        }
    except Exception as exc:
        try:
            _write_canary_audit(
                factory,
                action_type=CANARY_ACTION_FAILED,
                canary_id=canary_id,
                detail={
                    "status": "failed",
                    "source_revision": source_revision,
                    "model": model,
                    "prompt_version": EXCEPTION_PROMPT_VERSION,
                    "contract_version": EXCEPTION_CONTRACT_VERSION,
                    "request_id": request_id,
                    "provider_call_count": provider_call_count,
                    "error_code": _safe_error_code(exc),
                },
            )
        except Exception:
            pass
        raise


def main() -> int:
    try:
        result = execute_provider_canary()
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error_code": _safe_error_code(exc)},
                ensure_ascii=True,
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
