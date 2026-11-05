#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import (
    AssistantConversation,
    CrmProjectInsight,
    ExceptionAction,
    ExceptionCase,
    ExceptionDiagnosis,
    ExceptionDiagnosisJob,
    ExceptionPolicy,
)

ROOT = Path(__file__).resolve().parents[1]
GLOBAL_AI_FLAGS = (
    "exception_ai_global_enabled",
    "exception_ai_crm_enabled",
    "exception_ai_data_enabled",
    "exception_ai_finance_enabled",
    "exception_ai_global_actions_enabled",
    "exception_ai_high_risk_actions_enabled",
)


def _count(db: Session, model: type[Any]) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _distribution(db: Session, model: type[Any], column: Any) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).select_from(model).group_by(column).order_by(column)).all()
    return {str(label or "unset"): int(count) for label, count in rows}


def _source_revision(path: Path | None = None) -> str:
    path = path or ROOT / "SOURCE_REVISION"
    return path.read_text(encoding="utf-8").strip() if path.exists() else "unavailable"


def _alembic_revisions(db: Session) -> list[str]:
    table = Table("alembic_version", MetaData(), autoload_with=db.get_bind())
    return sorted(str(value) for value in db.scalars(select(table.c.version_num)).all())


def collect_baseline(db: Session, source_revision_path: Path | None = None) -> dict[str, Any]:
    alembic_revisions = _alembic_revisions(db)
    policy = db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "source_revision": _source_revision(source_revision_path),
        "alembic_revision": alembic_revisions[0] if len(alembic_revisions) == 1 else None,
        "alembic_revisions": alembic_revisions,
        "runtime": {
            "exception_center_enabled": settings.exception_center_enabled,
            "exception_ai_enabled": settings.exception_ai_enabled,
            "exception_schedule_enabled": settings.exception_schedule_enabled,
            "exception_actions_enabled": settings.exception_actions_enabled,
            "hermes_model": settings.hermes_model,
        },
        "future_global_ai_flags": {name: bool(getattr(settings, name, False)) for name in GLOBAL_AI_FLAGS},
        "crm_ai": {
            "conversations": _count(db, AssistantConversation),
            "conversation_statuses": _distribution(db, AssistantConversation, AssistantConversation.status),
            "conversation_sources": _distribution(db, AssistantConversation, AssistantConversation.source),
            "insights": _count(db, CrmProjectInsight),
            "insight_statuses": _distribution(db, CrmProjectInsight, CrmProjectInsight.status),
            "insight_types": _distribution(db, CrmProjectInsight, CrmProjectInsight.insight_type),
        },
        "exception_ai": {
            "cases": _count(db, ExceptionCase),
            "case_domains": _distribution(db, ExceptionCase, ExceptionCase.domain),
            "case_statuses": _distribution(db, ExceptionCase, ExceptionCase.status),
            "diagnosis_jobs": _count(db, ExceptionDiagnosisJob),
            "diagnosis_job_statuses": _distribution(db, ExceptionDiagnosisJob, ExceptionDiagnosisJob.status),
            "diagnosis_job_triggers": _distribution(db, ExceptionDiagnosisJob, ExceptionDiagnosisJob.trigger_type),
            "diagnoses": _count(db, ExceptionDiagnosis),
            "actions": _count(db, ExceptionAction),
            "action_statuses": _distribution(db, ExceptionAction, ExceptionAction.status),
            "action_types": _distribution(db, ExceptionAction, ExceptionAction.action_type),
        },
        "policy": None,
    }
    if policy is not None:
        payload["policy"] = {
            "is_enabled": policy.is_enabled,
            "manual_ai_enabled": policy.manual_ai_enabled,
            "scheduled_ai_enabled": policy.scheduled_ai_enabled,
            "full_scan_enabled": policy.full_scan_enabled,
            "digest_enabled": policy.digest_enabled,
            "manual_ai_daily_limit": policy.manual_ai_daily_limit,
            "scheduled_ai_daily_limit": policy.scheduled_ai_daily_limit,
            "scheduled_ai_batch_limit": policy.scheduled_ai_batch_limit,
            "ai_concurrency": policy.ai_concurrency,
        }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a content-free global AI stage-zero baseline.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    parser.add_argument("--source-revision-path", type=Path, help="Optional deployed SOURCE_REVISION path.")
    args = parser.parse_args()
    with SessionLocal() as db:
        baseline = collect_baseline(db, args.source_revision_path)
    canonical = json.dumps(baseline, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        **baseline,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
