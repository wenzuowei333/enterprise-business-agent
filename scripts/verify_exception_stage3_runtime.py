#!/usr/bin/env python3
"""Release gate for the exception-center stage-three runtime.

The script deliberately reports only non-secret booleans, versions, and counts.
It never prints connection strings, model credentials, or exception evidence. The
explicit observation initialization and recording modes only write a root-only
health/count timeline at the operator-provided path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OBSERVATION_SCHEMA_VERSION = 2
OBSERVATION_METRICS_SCHEMA_VERSION = 1
PRODUCTION_OBSERVATION_MIN_HOURS = 8.0
PRODUCTION_OBSERVATION_MAX_GAP_SECONDS = 900
SYSTEMD_AI_TIMEOUT_STOP_SECONDS = 180
AI_SHUTDOWN_SAFETY_MARGIN_SECONDS = 5
PROVIDER_CANARY_MAX_AGE_SECONDS = 172800
PROVIDER_CANARY_RESOURCE_TYPE = "exception_provider_canary"
PROVIDER_CALL_STARTED_ACTION = "exception_provider_call_started"
PROVIDER_CANARY_COMPLETED_ACTION = "exception_provider_canary_completed"
PROVIDER_CANARY_FAILED_ACTION = "exception_provider_canary_failed"
OBSERVATION_TIMEZONE = ZoneInfo("Asia/Hong_Kong")
OBSERVATION_WORKDAY_START_HOUR = 9
OBSERVATION_WORKDAY_END_HOUR = 17
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


class ReleaseAudit:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def check(self, name: str, condition: bool, detail: str) -> None:
        self.results.append(CheckResult(name=name, ok=bool(condition), detail=detail))

    @property
    def failures(self) -> list[CheckResult]:
        return [result for result in self.results if not result.ok]

    def render(self, *, as_json: bool) -> None:
        if as_json:
            print(
                json.dumps(
                    {
                        "ok": not self.failures,
                        "checks": [
                            {"name": item.name, "ok": item.ok, "detail": item.detail}
                            for item in self.results
                        ],
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
            )
            return
        for result in self.results:
            label = "PASS" if result.ok else "FAIL"
            print(f"[{label}] {result.name}: {result.detail}")
        print(f"SUMMARY checks={len(self.results)} failures={len(self.failures)}")


def _secret_is_configured(value: str | None, *, minimum_length: int) -> bool:
    normalized = (value or "").strip()
    if len(normalized) < minimum_length:
        return False
    lowered = normalized.casefold()
    return not any(marker in lowered for marker in ("replace-with", "change-me", "example", "placeholder"))


def _aware_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("dark deployment timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_observation_limits(minimum_hours: float, maximum_gap_seconds: int) -> None:
    if not math.isfinite(minimum_hours) or minimum_hours < PRODUCTION_OBSERVATION_MIN_HOURS:
        raise ValueError(
            f"production observation minimum must be at least {PRODUCTION_OBSERVATION_MIN_HOURS:g} hours"
        )
    if not 60 <= maximum_gap_seconds <= PRODUCTION_OBSERVATION_MAX_GAP_SECONDS:
        raise ValueError(
            "production observation maximum gap must be between 60 and "
            f"{PRODUCTION_OBSERVATION_MAX_GAP_SECONDS} seconds"
        )


def _covered_workday_window(
    sample_times: list[datetime],
    *,
    deployed_at: datetime,
    now: datetime,
    maximum_gap_seconds: int,
) -> str | None:
    """Return a covered Hong Kong weekday whose 09:00-17:00 window is continuous."""
    local_deployed = deployed_at.astimezone(OBSERVATION_TIMEZONE)
    local_now = now.astimezone(OBSERVATION_TIMEZONE)
    cursor = local_deployed.date()
    final_date = local_now.date()
    ordered_samples = sorted(_aware_utc(value) for value in sample_times)
    while cursor <= final_date:
        if cursor.weekday() < 5:
            workday_start = datetime(
                cursor.year,
                cursor.month,
                cursor.day,
                OBSERVATION_WORKDAY_START_HOUR,
                tzinfo=OBSERVATION_TIMEZONE,
            ).astimezone(timezone.utc)
            workday_end = datetime(
                cursor.year,
                cursor.month,
                cursor.day,
                OBSERVATION_WORKDAY_END_HOUR,
                tzinfo=OBSERVATION_TIMEZONE,
            ).astimezone(timezone.utc)
            if deployed_at <= workday_start and now >= workday_end:
                window_samples = [
                    sampled_at
                    for sampled_at in ordered_samples
                    if workday_start <= sampled_at <= workday_end
                ]
                if window_samples:
                    gaps = [
                        int((window_samples[0] - workday_start).total_seconds()),
                        int((workday_end - window_samples[-1]).total_seconds()),
                        *[
                            int((current - previous).total_seconds())
                            for previous, current in zip(
                                window_samples,
                                window_samples[1:],
                                strict=False,
                            )
                        ],
                    ]
                    if all(0 <= gap <= maximum_gap_seconds for gap in gaps):
                        return cursor.isoformat()
        cursor += timedelta(days=1)
    return None


def _compute_release_identity(root: Path = ROOT) -> str:
    """Hash only deployed executable/configuration inputs, excluding mutable runtime data."""
    candidates = (
        root / "SOURCE_REVISION",
        root / "docker-compose.yml",
        root / "backend" / "requirements.txt",
        root / "backend" / "alembic.ini",
        root / "backend" / "app",
        root / "backend" / "alembic",
        root / "deploy",
        root / "scripts" / "verify_exception_stage3_runtime.py",
        root / "scripts" / "run_exception_provider_canary.py",
    )
    files: dict[str, Path] = {}
    for candidate in candidates:
        if candidate.is_dir():
            descendants = candidate.rglob("*")
        else:
            descendants = (candidate,)
        for path in descendants:
            if not path.is_file() and not path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            files[relative] = path
    if not files:
        raise ValueError("release identity has no executable inputs")

    digest = hashlib.sha256()
    for relative, path in sorted(files.items()):
        stat_result = path.lstat()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f"{stat_result.st_mode & 0o777:o}".encode("ascii"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(path).encode("utf-8"))
        else:
            digest.update(b"file\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _read_source_revision(root: Path = ROOT) -> str:
    value = (root / "SOURCE_REVISION").read_text(encoding="utf-8").strip()
    if not value or len(value) > 128 or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-" for character in value):
        raise ValueError("SOURCE_REVISION is missing or invalid")
    return value


def _provider_canary_checks(
    audit: ReleaseAudit,
    connection: Any,
    sql_text: Any,
    *,
    now: datetime,
    dark_since: datetime | None,
    maximum_age_seconds: int,
    source_revision: str,
    provider_model: str,
    prompt_version: str,
    contract_version: str,
) -> None:
    terminal = connection.execute(
        sql_text(
            """
            SELECT action_type, resource_id, after_data, created_at
            FROM audit_log
            WHERE resource_type = :resource_type
              AND action_type IN (:started_action, :completed_action, :failed_action)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ),
        {
            "resource_type": PROVIDER_CANARY_RESOURCE_TYPE,
            "started_action": PROVIDER_CALL_STARTED_ACTION,
            "completed_action": PROVIDER_CANARY_COMPLETED_ACTION,
            "failed_action": PROVIDER_CANARY_FAILED_ACTION,
        },
    ).mappings().one_or_none()
    audit.check(
        "provider_canary.latest_completed",
        terminal is not None and terminal["action_type"] == PROVIDER_CANARY_COMPLETED_ACTION,
        "the latest canary activity must be a successful terminal audit",
    )
    if terminal is None or terminal["action_type"] != PROVIDER_CANARY_COMPLETED_ACTION:
        return

    detail = _json_mapping(terminal["after_data"])
    completed_at = _aware_utc(terminal["created_at"])
    age_seconds = int((now - completed_at).total_seconds())
    audit.check(
        "provider_canary.age",
        0 <= age_seconds <= maximum_age_seconds,
        f"age_seconds={age_seconds}; maximum={maximum_age_seconds}",
    )
    audit.check(
        "provider_canary.before_dark_baseline",
        dark_since is not None and completed_at < dark_since,
        "the successful canary must predate the current dark-observation baseline",
    )
    audit.check(
        "provider_canary.release",
        detail.get("source_revision") == source_revision,
        "canary source revision must match the deployed release",
    )
    audit.check(
        "provider_canary.model",
        detail.get("model") == provider_model,
        "canary model must match the configured provider model",
    )
    audit.check(
        "provider_canary.contract",
        detail.get("prompt_version") == prompt_version
        and detail.get("contract_version") == contract_version,
        "canary prompt and JSON contract versions must match the deployed diagnosis service",
    )
    audit.check(
        "provider_canary.result_contract",
        detail.get("status") == "passed"
        and detail.get("root_cause_code") == "warehouse_missing"
        and detail.get("schema_valid") is True
        and detail.get("canonical_evidence_refs_valid") is True
        and detail.get("safety_guard_passed") is True
        and detail.get("usage_complete") is True
        and detail.get("evidence_truncated") is False,
        "schema, root cause, evidence references, safety, usage, and synthetic evidence must pass",
    )
    provider_call_count = detail.get("provider_call_count")
    audited_starts = int(
        connection.scalar(
            sql_text(
                """
                SELECT count(*) FROM audit_log
                WHERE resource_type = :resource_type
                  AND resource_id = :resource_id
                  AND action_type = :started_action
                """
            ),
            {
                "resource_type": PROVIDER_CANARY_RESOURCE_TYPE,
                "resource_id": terminal["resource_id"],
                "started_action": PROVIDER_CALL_STARTED_ACTION,
            },
        )
        or 0
    )
    audit.check(
        "provider_canary.call_audit",
        isinstance(provider_call_count, int)
        and not isinstance(provider_call_count, bool)
        and provider_call_count > 0
        and audited_starts == provider_call_count,
        f"started_audits={audited_starts}",
    )
    usage = (
        detail.get("prompt_tokens"),
        detail.get("completion_tokens"),
        detail.get("total_tokens"),
    )
    audit.check(
        "provider_canary.usage",
        all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in usage)
        and usage[2] >= usage[0] + usage[1],
        "all provider usage counters must be positive and internally consistent",
    )


def _manual_policy_activation_at(connection: Any, sql_text: Any) -> datetime | None:
    rows = connection.execute(
        sql_text(
            """
            SELECT before_data, after_data, created_at
            FROM audit_log
            WHERE action_type = 'update_exception_policy'
              AND resource_type = 'exception_policy'
              AND resource_id = 'default'
            ORDER BY created_at DESC, id DESC
            LIMIT 200
            """
        )
    ).mappings().all()
    for row in rows:
        before = _json_mapping(row["before_data"])
        after = _json_mapping(row["after_data"])
        if not bool(before.get("manual_ai_enabled")) and bool(after.get("manual_ai_enabled")):
            return _aware_utc(row["created_at"])
    return None


def _validate_manual_transition(
    audit: ReleaseAudit,
    *,
    activation_at: datetime | None,
    operator_marker: datetime | None,
    now: datetime,
) -> datetime | None:
    """Validate an optional operator marker without using it as the audit baseline."""
    audit.check(
        "manual.policy_activation_audit",
        activation_at is not None,
        "a server-side false-to-true manual policy audit event is required",
    )
    audit.check(
        "manual.policy_activation_not_future",
        activation_at is not None and activation_at <= now,
        "server-side activation timestamp must not be in the future",
    )
    if operator_marker is not None:
        audit.check(
            "manual.operator_marker_not_future",
            operator_marker <= now,
            "optional operator marker must not be in the future",
        )
        audit.check(
            "manual.operator_marker_precedes_activation",
            activation_at is not None and operator_marker <= activation_at,
            "optional operator marker must not follow server-side activation",
        )
    return activation_at


def _runtime_environment_checks(
    audit: ReleaseAudit,
    settings: Any,
    *,
    mode: str,
    require_web_secret: bool = True,
) -> None:
    ai_runtime_expected = mode in {"manual-ready", "manual"}
    audit.check("environment.production", settings.environment == "production", "must equal production")
    audit.check("feature.exception_center", settings.exception_center_enabled, "must be enabled")
    audit.check(
        "feature.global_ai",
        settings.exception_ai_enabled is ai_runtime_expected,
        f"must be {'enabled' if ai_runtime_expected else 'disabled'} in {mode} mode",
    )
    audit.check("feature.schedule", not settings.exception_schedule_enabled, "must remain disabled")
    audit.check("feature.actions", not settings.exception_actions_enabled, "must remain disabled")
    audit.check("limit.ai_concurrency", settings.exception_ai_concurrency == 1, "must equal 1")
    audit.check("limit.manual_daily", settings.exception_manual_ai_daily_limit == 20, "must equal 20")
    audit.check(
        "limit.manual_provider_usage",
        settings.exception_manual_ai_require_provider_usage is True,
        "manual diagnosis and release canary must require complete provider usage",
    )
    audit.check("limit.scheduled_daily", settings.exception_scheduled_ai_daily_limit == 0, "must equal 0")
    audit.check("limit.evidence_bytes", settings.exception_evidence_max_bytes == 32768, "must equal 32768")
    audit.check("limit.evidence_tokens", settings.exception_evidence_max_tokens == 8000, "must equal 8000")
    audit.check(
        "limit.ai_shutdown_timeout",
        10 <= settings.exception_ai_shutdown_timeout_seconds
        <= SYSTEMD_AI_TIMEOUT_STOP_SECONDS - AI_SHUTDOWN_SAFETY_MARGIN_SECONDS,
        f"must be between 10 and {SYSTEMD_AI_TIMEOUT_STOP_SECONDS - AI_SHUTDOWN_SAFETY_MARGIN_SECONDS}",
    )
    audit.check(
        "secret.jwt",
        not require_web_secret or _secret_is_configured(settings.jwt_secret, minimum_length=32),
        "configured securely" if require_web_secret else "not required by least-privilege observation sampler",
    )
    if mode in {"manual-ready", "manual"}:
        base_url = (settings.hermes_api_base_url or "").strip()
        parsed = urlparse(base_url)
        audit.check(
            "provider.https",
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None,
            "configured with an HTTPS endpoint without URL-embedded credentials",
        )
        audit.check(
            "provider.api_key",
            _secret_is_configured(settings.hermes_api_key, minimum_length=16),
            "configured (value suppressed)",
        )


def _database_checks(
    audit: ReleaseAudit,
    engine: Any,
    *,
    mode: str,
    expected_revision: str,
    heartbeat_max_age: int,
    skip_heartbeats: bool,
    preflight: bool,
    dark_since: datetime | None,
    transition_since: datetime | None,
    provider_canary_max_age_seconds: int = PROVIDER_CANARY_MAX_AGE_SECONDS,
    source_revision: str | None = None,
    provider_model: str | None = None,
    prompt_version: str | None = None,
    contract_version: str | None = None,
) -> dict[str, Any]:
    from sqlalchemy import text

    now = datetime.now(timezone.utc)
    with engine.connect() as connection:
        revisions = [str(row[0]) for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
        audit.check(
            "database.alembic_revision",
            revisions == [expected_revision],
            f"expected single revision {expected_revision}; found {','.join(revisions) or 'none'}",
        )

        policy = connection.execute(
            text(
                """
                SELECT is_enabled, manual_ai_enabled, scheduled_ai_enabled,
                       full_scan_enabled, digest_enabled, manual_ai_daily_limit,
                       scheduled_ai_daily_limit, scheduled_ai_batch_limit, ai_concurrency
                FROM exception_policy
                WHERE policy_key = 'default'
                """
            )
        ).mappings().one_or_none()
        audit.check("policy.default_exists", policy is not None, "exactly one default policy is required")
        manual_policy_expected = mode == "manual"
        manual_daily_limit = 0
        if policy is not None:
            audit.check("policy.enabled", bool(policy["is_enabled"]), "deterministic exception processing stays enabled")
            audit.check(
                "policy.manual_ai",
                bool(policy["manual_ai_enabled"]) is manual_policy_expected,
                f"must be {'enabled' if manual_policy_expected else 'disabled'} in {mode} mode",
            )
            audit.check("policy.scheduled_ai", not bool(policy["scheduled_ai_enabled"]), "must remain disabled")
            audit.check("policy.full_scan", not bool(policy["full_scan_enabled"]), "must remain disabled")
            audit.check("policy.digest", not bool(policy["digest_enabled"]), "must remain disabled")
            manual_daily_limit = int(policy["manual_ai_daily_limit"])
            audit.check("policy.manual_daily", manual_daily_limit == 20, "must equal 20")
            audit.check("policy.scheduled_daily", int(policy["scheduled_ai_daily_limit"]) == 0, "must equal 0")
            audit.check("policy.scheduled_batch", int(policy["scheduled_ai_batch_limit"]) == 20, "must equal 20")
            concurrency = int(policy["ai_concurrency"])
            audit.check(
                "policy.ai_concurrency",
                concurrency >= 1 and (mode == "dark" or concurrency == 1),
                f"value={concurrency}; AI-ready modes require 1 and dark mode preserves the existing valid value",
            )

        calls_since_dark = 0
        jobs_since_dark = 0
        check_dark_activity = mode == "dark" and not preflight
        check_manual_ready_activity = mode == "manual-ready" and dark_since is not None
        if check_dark_activity or check_manual_ready_activity:
            audit.check(
                "dark.baseline_provided",
                dark_since is not None,
                "--dark-since is required for a post-start dark deployment audit",
            )
            if dark_since is not None:
                audit.check(
                    "dark.baseline_not_future",
                    dark_since <= now + timedelta(minutes=5),
                    "deployment baseline must not be in the future",
                )
                diagnosis_calls_since_dark = int(
                    connection.scalar(
                        text(
                            """
                            SELECT count(*) FROM exception_event
                            WHERE event_type = 'diagnosis_ai_call_started'
                              AND created_at >= :dark_since
                            """
                        ),
                        {"dark_since": dark_since},
                    )
                    or 0
                )
                canary_calls_since_dark = int(
                    connection.scalar(
                        text(
                            """
                            SELECT count(*) FROM audit_log
                            WHERE resource_type = :resource_type
                              AND action_type = :started_action
                              AND created_at >= :dark_since
                            """
                        ),
                        {
                            "resource_type": PROVIDER_CANARY_RESOURCE_TYPE,
                            "started_action": PROVIDER_CALL_STARTED_ACTION,
                            "dark_since": dark_since,
                        },
                    )
                    or 0
                )
                calls_since_dark = diagnosis_calls_since_dark + canary_calls_since_dark
                jobs_since_dark = int(
                    connection.scalar(
                        text(
                            """
                            SELECT count(*) FROM exception_diagnosis_job
                            WHERE created_at >= :dark_since
                            """
                        ),
                        {"dark_since": dark_since},
                    )
                    or 0
                )
                audit.check("dark.ai_calls_since_start", calls_since_dark == 0, f"count={calls_since_dark}")
                audit.check("dark.diagnosis_jobs_since_start", jobs_since_dark == 0, f"count={jobs_since_dark}")

        stale_diagnosis = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*) FROM exception_diagnosis_job
                    WHERE status = 'processing'
                      AND (lease_expires_at IS NULL OR lease_expires_at < CURRENT_TIMESTAMP)
                    """
                )
            )
            or 0
        )
        stale_background = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*) FROM exception_background_job
                    WHERE status = 'processing'
                      AND (lease_expires_at IS NULL OR lease_expires_at < CURRENT_TIMESTAMP)
                    """
                )
            )
            or 0
        )
        audit.check("queue.diagnosis_expired_leases", stale_diagnosis == 0, f"count={stale_diagnosis}")
        audit.check("queue.background_expired_leases", stale_background == 0, f"count={stale_background}")

        duplicate_active = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*) FROM (
                        SELECT case_id, evidence_version
                        FROM exception_diagnosis_job
                        WHERE status IN ('queued', 'processing')
                        GROUP BY case_id, evidence_version
                        HAVING count(*) > 1
                    ) AS duplicate_jobs
                    """
                )
            )
            or 0
        )
        audit.check("queue.duplicate_active_diagnoses", duplicate_active == 0, f"groups={duplicate_active}")

        scheduled_active = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*) FROM exception_diagnosis_job
                    WHERE status IN ('queued', 'processing') AND trigger_type <> 'manual'
                    """
                )
            )
            or 0
        )
        audit.check("queue.scheduled_active", scheduled_active == 0, f"count={scheduled_active}")

        all_active = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*) FROM exception_diagnosis_job
                    WHERE status IN ('queued', 'processing')
                    """
                )
            )
            or 0
        )
        if mode in {"dark", "manual-ready", "manual"}:
            audit.check(f"queue.{mode}.active", all_active == 0, f"count={all_active}")

        local_zone = ZoneInfo("Asia/Hong_Kong")
        local_now = now.astimezone(local_zone)
        local_start = datetime(local_now.year, local_now.month, local_now.day, tzinfo=local_zone)
        event_rows = connection.execute(
            text(
                """
                SELECT detail_json FROM exception_event
                WHERE event_type = 'diagnosis_ai_call_started' AND created_at >= :day_start
                """
            ),
            {"day_start": local_start.astimezone(timezone.utc)},
        ).all()
        canary_calls_today = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*) FROM audit_log
                    WHERE resource_type = :resource_type
                      AND action_type = :started_action
                      AND created_at >= :day_start
                    """
                ),
                {
                    "resource_type": PROVIDER_CANARY_RESOURCE_TYPE,
                    "started_action": PROVIDER_CALL_STARTED_ACTION,
                    "day_start": local_start.astimezone(timezone.utc),
                },
            )
            or 0
        )
        provider_calls_today = len(event_rows) + canary_calls_today
        provider_budget_remaining = max(0, manual_daily_limit - provider_calls_today)
        audit.check(
            "budget.provider_daily_limit",
            mode == "dark" or provider_calls_today <= manual_daily_limit,
            (
                f"limit={manual_daily_limit}; used={provider_calls_today}; "
                f"canary_attempts={canary_calls_today}; remaining={provider_budget_remaining}"
            ),
        )
        scheduled_calls = sum(
            1
            for row in event_rows
            if isinstance(row[0], dict) and row[0].get("trigger_type") == "scheduled"
        )
        audit.check("budget.scheduled_calls_today", scheduled_calls == 0, f"count={scheduled_calls}")

        manual_calls = sum(
            1
            for row in event_rows
            if isinstance(row[0], dict) and row[0].get("trigger_type") == "manual"
        )
        manual_remaining = provider_budget_remaining
        audit.check(
            "budget.manual_remaining",
            mode == "dark" or manual_remaining > 0,
            (
                f"limit={manual_daily_limit}; business_used={manual_calls}; "
                f"provider_used={provider_calls_today}; remaining={manual_remaining}"
            ),
        )

        if mode in {"manual-ready", "manual"}:
            metadata_available = all(
                isinstance(value, str) and bool(value)
                for value in (source_revision, provider_model, prompt_version, contract_version)
            )
            audit.check(
                "provider_canary.expected_metadata",
                metadata_available,
                "release, model, prompt, and contract identifiers are required",
            )
            if metadata_available:
                _provider_canary_checks(
                    audit,
                    connection,
                    text,
                    now=now,
                    dark_since=dark_since,
                    maximum_age_seconds=provider_canary_max_age_seconds,
                    source_revision=source_revision or "",
                    provider_model=provider_model or "",
                    prompt_version=prompt_version or "",
                    contract_version=contract_version or "",
                )

        scheduled_background_today = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*) FROM exception_background_job
                    WHERE job_type IN ('full_scan', 'digest')
                      AND created_at >= :day_start
                    """
                ),
                {"day_start": local_start.astimezone(timezone.utc)},
            )
            or 0
        )
        audit.check(
            "queue.scheduled_background_today",
            scheduled_background_today == 0,
            f"count={scheduled_background_today}",
        )

        if mode == "manual":
            effective_transition = _validate_manual_transition(
                audit,
                activation_at=_manual_policy_activation_at(connection, text),
                operator_marker=transition_since,
                now=now,
            )
        else:
            effective_transition = None
        if effective_transition is not None:
            transition_jobs = int(
                connection.scalar(
                    text(
                        """
                        SELECT count(*) FROM exception_diagnosis_job
                        WHERE created_at >= :transition_since
                        """
                    ),
                    {"transition_since": effective_transition},
                )
                or 0
            )
            transition_calls = int(
                connection.scalar(
                    text(
                        """
                        SELECT count(*) FROM exception_event
                        WHERE event_type = 'diagnosis_ai_call_started'
                          AND created_at >= :transition_since
                        """
                    ),
                    {"transition_since": effective_transition},
                )
                or 0
            )
            audit.check("manual.transition_jobs", transition_jobs == 0, f"count={transition_jobs}")
            audit.check("manual.transition_calls", transition_calls == 0, f"count={transition_calls}")

        heartbeat_ages: dict[str, int | None] = {}
        if not skip_heartbeats:
            heartbeat_rows = connection.execute(
                text(
                    """
                    SELECT service_type, max(last_heartbeat_at) AS last_heartbeat_at
                    FROM exception_service_heartbeat
                    GROUP BY service_type
                    """
                )
            ).mappings().all()
            latest = {str(row["service_type"]): row["last_heartbeat_at"] for row in heartbeat_rows}
            for service_type in ("worker", "ai_worker", "scheduler"):
                heartbeat = latest.get(service_type)
                age = None if heartbeat is None else max(0, int((now - _aware_utc(heartbeat)).total_seconds()))
                heartbeat_ages[service_type] = age
                audit.check(
                    f"heartbeat.{service_type}",
                    age is not None and age <= heartbeat_max_age,
                    "missing" if age is None else f"age_seconds={age}",
                )

        diagnosis_calls_total = int(
            connection.scalar(
                text("SELECT count(*) FROM exception_event WHERE event_type = 'diagnosis_ai_call_started'")
            )
            or 0
        )
        canary_calls_total = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*) FROM audit_log
                    WHERE resource_type = :resource_type
                      AND action_type = :started_action
                    """
                ),
                {
                    "resource_type": PROVIDER_CANARY_RESOURCE_TYPE,
                    "started_action": PROVIDER_CALL_STARTED_ACTION,
                },
            )
            or 0
        )
        calls_total = diagnosis_calls_total + canary_calls_total
        diagnosis_jobs_total = int(connection.scalar(text("SELECT count(*) FROM exception_diagnosis_job")) or 0)
        return {
            "sampled_at": now.isoformat(),
            "ai_calls_total": calls_total,
            "diagnosis_jobs_total": diagnosis_jobs_total,
            "ai_calls_since_deploy": calls_since_dark,
            "diagnosis_jobs_since_deploy": jobs_since_dark,
            "active_diagnosis_jobs": all_active,
            "expired_diagnosis_leases": stale_diagnosis,
            "expired_background_leases": stale_background,
            "duplicate_active_diagnoses": duplicate_active,
            "scheduled_active_diagnoses": scheduled_active,
            "scheduled_calls_today": scheduled_calls,
            "provider_calls_today": provider_calls_today,
            "provider_canary_calls_today": canary_calls_today,
            "provider_budget_remaining": provider_budget_remaining,
            "scheduled_background_today": scheduled_background_today,
            "manual_budget_remaining": manual_remaining,
            "heartbeat_ages": heartbeat_ages,
        }


def _check_health_endpoint(base_url: str, path: str) -> bool:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        with urlopen(url, timeout=5) as response:  # noqa: S310 - fixed operator-provided internal endpoint.
            return 200 <= int(response.status) < 300
    except (HTTPError, URLError, TimeoutError, ValueError):
        return False


def _read_observation(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("observation document must be an object")
    return payload


def _write_observation(
    path: Path,
    payload: dict[str, Any],
    *,
    parent_mode: int = 0o750,
    file_mode: int = 0o640,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=parent_mode)
    os.chmod(path.parent, parent_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, file_mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _initialize_observation(
    audit: ReleaseAudit,
    path: Path,
    *,
    deployed_at: datetime | None,
    snapshot: dict[str, Any],
    release_identity: str,
    expected_revision: str,
) -> None:
    audit.check(
        "observation.initialize_mode",
        deployed_at is not None,
        "dark deployment timestamp is required",
    )
    if deployed_at is None or audit.failures:
        return
    payload = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "deployed_at": deployed_at.isoformat(),
        "release_identity": release_identity,
        "expected_revision": expected_revision,
        "baseline": {
            "ai_calls_total": int(snapshot["ai_calls_total"]),
            "diagnosis_jobs_total": int(snapshot["diagnosis_jobs_total"]),
        },
        "samples": [],
    }
    _write_observation(path, payload)
    audit.check("observation.initialized", True, f"path={path}; credentials=none")


def _record_observation(
    audit: ReleaseAudit,
    path: Path,
    *,
    snapshot: dict[str, Any],
    web_healthy: bool,
    database_healthy: bool,
    http_5xx_count: int | None,
) -> None:
    state = _read_observation(path)
    schema_valid = state.get("schema_version") == OBSERVATION_SCHEMA_VERSION
    audit.check("observation.record_schema", schema_valid, f"expected={OBSERVATION_SCHEMA_VERSION}")
    if not schema_valid:
        return
    audit.check(
        "observation.record_release_identity",
        isinstance(state.get("release_identity"), str) and len(state["release_identity"]) == 64,
        "schema v2 baseline must bind a SHA-256 release identity",
    )
    audit.check(
        "observation.record_expected_revision",
        isinstance(state.get("expected_revision"), str) and bool(state["expected_revision"]),
        "schema v2 baseline must bind an Alembic revision",
    )
    samples = state.get("samples")
    if not isinstance(samples, list):
        audit.check("observation.record_samples", False, "samples must be a list")
        return
    audit.check(
        "observation.record_5xx_metric",
        http_5xx_count is not None and http_5xx_count >= 0,
        "a non-negative cumulative application 5xx count is required",
    )
    sample = {
        "sampled_at": snapshot["sampled_at"],
        "web_healthy": web_healthy,
        "database_healthy": database_healthy,
        "http_5xx_count": http_5xx_count,
        "ai_calls_since_deploy": int(snapshot["ai_calls_since_deploy"]),
        "diagnosis_jobs_since_deploy": int(snapshot["diagnosis_jobs_since_deploy"]),
        "active_diagnosis_jobs": int(snapshot["active_diagnosis_jobs"]),
        "expired_diagnosis_leases": int(snapshot["expired_diagnosis_leases"]),
        "expired_background_leases": int(snapshot["expired_background_leases"]),
        "duplicate_active_diagnoses": int(snapshot["duplicate_active_diagnoses"]),
        "heartbeat_ages": snapshot["heartbeat_ages"],
        "audit_ok": not audit.failures,
    }
    samples.append(sample)
    state["samples"] = samples
    _write_observation(path, state)
    audit.check("observation.sample_recorded", True, f"samples={len(samples)}; credentials=none")


def _write_observation_metrics(
    audit: ReleaseAudit,
    path: Path,
    *,
    observation_path: Path,
    snapshot: dict[str, Any],
    web_healthy: bool,
    database_healthy: bool,
    http_5xx_count: int | None,
    release_identity: str,
    expected_revision: str,
) -> None:
    observation = _read_observation(observation_path)
    audit.check(
        "metrics.observation_schema",
        observation.get("schema_version") == OBSERVATION_SCHEMA_VERSION,
        f"expected={OBSERVATION_SCHEMA_VERSION}",
    )
    audit.check(
        "metrics.release_identity",
        observation.get("release_identity") == release_identity,
        "current release must match the observation baseline",
    )
    audit.check(
        "metrics.expected_revision",
        observation.get("expected_revision") == expected_revision,
        f"expected={expected_revision}",
    )
    audit.check(
        "metrics.http_5xx_count",
        isinstance(http_5xx_count, int) and http_5xx_count >= 0,
        "a non-negative cumulative 5xx count is required",
    )
    payload = {
        "schema_version": OBSERVATION_METRICS_SCHEMA_VERSION,
        "release_identity": release_identity,
        "expected_revision": expected_revision,
        "deployed_at": observation.get("deployed_at"),
        "sample": {
            "sampled_at": snapshot["sampled_at"],
            "web_healthy": bool(web_healthy),
            "database_healthy": bool(database_healthy),
            "http_5xx_count": http_5xx_count,
            "ai_calls_since_deploy": int(snapshot["ai_calls_since_deploy"]),
            "diagnosis_jobs_since_deploy": int(snapshot["diagnosis_jobs_since_deploy"]),
            "active_diagnosis_jobs": int(snapshot["active_diagnosis_jobs"]),
            "expired_diagnosis_leases": int(snapshot["expired_diagnosis_leases"]),
            "expired_background_leases": int(snapshot["expired_background_leases"]),
            "duplicate_active_diagnoses": int(snapshot["duplicate_active_diagnoses"]),
            "heartbeat_ages": snapshot["heartbeat_ages"],
            "audit_ok": not audit.failures,
        },
    }
    _write_observation(path, payload, parent_mode=0o750, file_mode=0o600)
    audit.check("metrics.written", True, f"path={path}; credentials=none")


def _consume_observation_metrics(
    audit: ReleaseAudit,
    observation_path: Path,
    metrics_path: Path,
    *,
    release_identity: str,
    expected_revision: str,
) -> None:
    metrics_stat = metrics_path.stat()
    audit.check(
        "metrics.root_owned",
        metrics_stat.st_uid == 0
        and metrics_stat.st_gid == os.getgid()
        and stat.S_IMODE(metrics_stat.st_mode) == 0o640,
        "metrics file must be root-owned, observer-group-readable, and mode 0640",
    )
    observation = _read_observation(observation_path)
    metrics = _read_observation(metrics_path)
    sample = metrics.get("sample")
    audit.check(
        "metrics.schema",
        metrics.get("schema_version") == OBSERVATION_METRICS_SCHEMA_VERSION,
        f"expected={OBSERVATION_METRICS_SCHEMA_VERSION}",
    )
    audit.check(
        "metrics.baseline_identity",
        metrics.get("release_identity") == observation.get("release_identity") == release_identity,
        "metrics, baseline, and current release identities must match",
    )
    audit.check(
        "metrics.baseline_revision",
        metrics.get("expected_revision") == observation.get("expected_revision") == expected_revision,
        f"expected={expected_revision}",
    )
    audit.check(
        "metrics.deployed_at",
        metrics.get("deployed_at") == observation.get("deployed_at"),
        "metrics must use the current observation deployment baseline",
    )
    audit.check("metrics.sample", isinstance(sample, dict), "metrics sample must be an object")
    if audit.failures or not isinstance(sample, dict):
        return
    sampled_at = _parse_utc_timestamp(str(sample.get("sampled_at") or ""))
    now = datetime.now(timezone.utc)
    audit.check(
        "metrics.sample_fresh",
        sampled_at is not None and timedelta(seconds=-5) <= now - sampled_at <= timedelta(minutes=2),
        "root metrics must be consumed within two minutes and cannot be future-dated",
    )
    integer_fields = (
        "http_5xx_count",
        "ai_calls_since_deploy",
        "diagnosis_jobs_since_deploy",
        "active_diagnosis_jobs",
        "expired_diagnosis_leases",
        "expired_background_leases",
        "duplicate_active_diagnoses",
    )
    audit.check(
        "metrics.sample_contract",
        all(isinstance(sample.get(field), int) and int(sample[field]) >= 0 for field in integer_fields)
        and isinstance(sample.get("web_healthy"), bool)
        and isinstance(sample.get("database_healthy"), bool)
        and sample.get("audit_ok") is True,
        "metrics sample must contain successful non-negative scalar checks",
    )
    if audit.failures:
        return
    snapshot = {
        "sampled_at": sample["sampled_at"],
        "ai_calls_since_deploy": sample["ai_calls_since_deploy"],
        "diagnosis_jobs_since_deploy": sample["diagnosis_jobs_since_deploy"],
        "active_diagnosis_jobs": sample["active_diagnosis_jobs"],
        "expired_diagnosis_leases": sample["expired_diagnosis_leases"],
        "expired_background_leases": sample["expired_background_leases"],
        "duplicate_active_diagnoses": sample["duplicate_active_diagnoses"],
        "heartbeat_ages": sample.get("heartbeat_ages") or {},
    }
    _record_observation(
        audit,
        observation_path,
        snapshot=snapshot,
        web_healthy=sample["web_healthy"],
        database_healthy=sample["database_healthy"],
        http_5xx_count=sample["http_5xx_count"],
    )


def _verify_observation(
    audit: ReleaseAudit,
    path: Path,
    *,
    minimum_hours: float,
    maximum_gap_seconds: int,
    latest_sample_max_age_seconds: int,
    release_identity: str,
    expected_revision: str,
) -> None:
    state = _read_observation(path)
    audit.check(
        "observation.schema",
        state.get("schema_version") == OBSERVATION_SCHEMA_VERSION,
        f"expected={OBSERVATION_SCHEMA_VERSION}",
    )
    recorded_identity = state.get("release_identity")
    audit.check(
        "observation.release_identity",
        recorded_identity == release_identity,
        "current deployed executable/configuration inputs must match the dark-deployment baseline",
    )
    recorded_revision = state.get("expected_revision")
    audit.check(
        "observation.expected_revision",
        recorded_revision == expected_revision,
        f"recorded={recorded_revision or 'missing'}; expected={expected_revision}",
    )
    deployed_at = _parse_utc_timestamp(str(state.get("deployed_at") or ""))
    samples = state.get("samples")
    if deployed_at is None or not isinstance(samples, list):
        audit.check("observation.structure", False, "deployed_at and samples are required")
        return

    now = datetime.now(timezone.utc)
    required_seconds = int(minimum_hours * 3600)
    duration_seconds = max(0, int((now - deployed_at).total_seconds()))
    audit.check(
        "observation.minimum_duration",
        duration_seconds >= required_seconds,
        f"observed_seconds={duration_seconds}; required_seconds={required_seconds}",
    )
    parsed_samples: list[tuple[datetime, dict[str, Any]]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        sampled_at = _parse_utc_timestamp(str(sample.get("sampled_at") or ""))
        if sampled_at is not None:
            parsed_samples.append((sampled_at, sample))
    parsed_samples.sort(key=lambda item: item[0])
    audit.check("observation.samples_present", bool(parsed_samples), f"count={len(parsed_samples)}")
    if not parsed_samples:
        return

    first_delay = int((parsed_samples[0][0] - deployed_at).total_seconds())
    latest_age = int((now - parsed_samples[-1][0]).total_seconds())
    largest_gap = max(
        [first_delay, latest_age]
        + [
            int((current[0] - previous[0]).total_seconds())
            for previous, current in zip(parsed_samples, parsed_samples[1:], strict=False)
        ]
    )
    audit.check(
        "observation.continuous_samples",
        0 <= first_delay <= maximum_gap_seconds
        and 0 <= latest_age <= latest_sample_max_age_seconds
        and largest_gap <= maximum_gap_seconds,
        (
            f"first_delay={first_delay}; latest_age={latest_age}; largest_gap={largest_gap}; "
            f"max_gap={maximum_gap_seconds}; latest_max={latest_sample_max_age_seconds}"
        ),
    )
    covered_workday = _covered_workday_window(
        [sampled_at for sampled_at, _ in parsed_samples],
        deployed_at=deployed_at,
        now=now,
        maximum_gap_seconds=maximum_gap_seconds,
    )
    audit.check(
        "observation.workday_coverage",
        covered_workday is not None,
        (
            f"covered_workday={covered_workday}; timezone=Asia/Hong_Kong; "
            f"window={OBSERVATION_WORKDAY_START_HOUR:02d}:00-"
            f"{OBSERVATION_WORKDAY_END_HOUR:02d}:00"
        ),
    )

    unhealthy = sum(
        1
        for _, sample in parsed_samples
        if not bool(sample.get("audit_ok"))
        or not bool(sample.get("web_healthy"))
        or not bool(sample.get("database_healthy"))
    )
    ai_activity = sum(
        1
        for _, sample in parsed_samples
        if int(sample.get("ai_calls_since_deploy") or 0) != 0
        or int(sample.get("diagnosis_jobs_since_deploy") or 0) != 0
    )
    stale_leases = sum(
        1
        for _, sample in parsed_samples
        if int(sample.get("expired_diagnosis_leases") or 0) != 0
        or int(sample.get("expired_background_leases") or 0) != 0
    )
    duplicate_jobs = sum(
        1 for _, sample in parsed_samples if int(sample.get("duplicate_active_diagnoses") or 0) != 0
    )
    samples_with_5xx = sum(
        1
        for _, sample in parsed_samples
        if not isinstance(sample.get("http_5xx_count"), int) or int(sample["http_5xx_count"]) != 0
    )
    audit.check("observation.health", unhealthy == 0, f"failed_samples={unhealthy}")
    audit.check("observation.ai_activity", ai_activity == 0, f"failed_samples={ai_activity}")
    audit.check("observation.expired_leases", stale_leases == 0, f"failed_samples={stale_leases}")
    audit.check("observation.duplicate_jobs", duplicate_jobs == 0, f"failed_samples={duplicate_jobs}")
    audit.check("observation.http_5xx", samples_with_5xx == 0, f"failed_samples={samples_with_5xx}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the exception-center stage-three production runtime")
    parser.add_argument("--mode", choices=("dark", "manual-ready", "manual"), default="dark")
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--heartbeat-max-age", type=int, default=120)
    parser.add_argument(
        "--dark-since",
        help="timezone-aware ISO-8601 timestamp marking the start of a dark deployment observation",
    )
    parser.add_argument(
        "--transition-since",
        help=(
            "optional timezone-aware operator marker used only to cross-check the server-side "
            "manual-AI policy audit timestamp"
        ),
    )
    parser.add_argument("--observation-file", type=Path)
    parser.add_argument("--initialize-observation", action="store_true")
    parser.add_argument("--record-observation", action="store_true")
    parser.add_argument("--write-observation-metrics", type=Path)
    parser.add_argument("--consume-observation-metrics", type=Path)
    parser.add_argument("--require-observation", action="store_true")
    parser.add_argument("--observation-min-hours", type=float, default=8.0)
    parser.add_argument("--observation-max-gap-seconds", type=int, default=900)
    parser.add_argument("--observation-latest-max-age-seconds", type=int, default=900)
    parser.add_argument(
        "--provider-canary-max-age-seconds",
        type=int,
        default=PROVIDER_CANARY_MAX_AGE_SECONDS,
        help="maximum age of the latest matching pre-dark provider canary",
    )
    parser.add_argument("--health-base", default="http://127.0.0.1:8082")
    parser.add_argument("--http-5xx-count", type=int)
    parser.add_argument("--skip-heartbeats", action="store_true")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="check configuration, migration, and policy before workers are started",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = ReleaseAudit()
    original_cwd = Path.cwd()
    try:
        scalar_observation_mode = bool(
            args.record_observation
            or args.write_observation_metrics
            or args.consume_observation_metrics
        )
        runtime_cwd = (
            args.observation_file.parent
            if scalar_observation_mode and args.observation_file is not None
            else ROOT
        )
        os.chdir(runtime_cwd)
        dark_since = _parse_utc_timestamp(args.dark_since)
        transition_since = _parse_utc_timestamp(args.transition_since)
        _validate_observation_limits(
            args.observation_min_hours,
            args.observation_max_gap_seconds,
        )
        if not 1 <= args.observation_latest_max_age_seconds <= args.observation_max_gap_seconds:
            raise ValueError("latest observation sample age must be positive and no larger than the gap limit")
        if not 1 <= args.provider_canary_max_age_seconds <= 604800:
            raise ValueError("provider canary maximum age must be between 1 second and 7 days")
        mutation_modes = (
            bool(args.initialize_observation),
            bool(args.record_observation),
            bool(args.write_observation_metrics),
            bool(args.consume_observation_metrics),
        )
        if sum(mutation_modes) > 1:
            raise ValueError("observation mutation modes are mutually exclusive")
        if (any(mutation_modes) or args.require_observation) \
            and args.observation_file is None:
            raise ValueError("observation file is required")
        if (args.record_observation or args.write_observation_metrics or args.require_observation) \
            and dark_since is None and args.observation_file is not None:
            dark_since = _parse_utc_timestamp(
                str(_read_observation(args.observation_file).get("deployed_at") or "")
            )

        release_identity = (
            _compute_release_identity()
            if args.initialize_observation
            or args.require_observation
            or args.write_observation_metrics
            or args.consume_observation_metrics
            else None
        )
        if args.consume_observation_metrics:
            _consume_observation_metrics(
                audit,
                args.observation_file,
                args.consume_observation_metrics,
                release_identity=release_identity or "",
                expected_revision=args.expected_revision,
            )
        else:
            from app.core.config import settings
            from app.core.database import engine
            from app.services.hermes_ai_service import (
                EXCEPTION_CONTRACT_VERSION,
                EXCEPTION_PROMPT_VERSION,
            )

            source_revision = _read_source_revision() if args.mode in {"manual-ready", "manual"} else None

            _runtime_environment_checks(
                audit,
                settings,
                mode=args.mode,
                require_web_secret=not (args.record_observation or args.write_observation_metrics),
            )
            snapshot = _database_checks(
                audit,
                engine,
                mode=args.mode,
                expected_revision=args.expected_revision,
                heartbeat_max_age=max(30, args.heartbeat_max_age),
                skip_heartbeats=args.skip_heartbeats,
                preflight=args.preflight,
                dark_since=dark_since,
                transition_since=transition_since,
                provider_canary_max_age_seconds=args.provider_canary_max_age_seconds,
                source_revision=source_revision,
                provider_model=settings.hermes_model,
                prompt_version=EXCEPTION_PROMPT_VERSION,
                contract_version=EXCEPTION_CONTRACT_VERSION,
            )
            web_healthy = _check_health_endpoint(args.health_base, "/api/v1/health")
            database_healthy = _check_health_endpoint(args.health_base, "/api/v1/health/db")
            if args.record_observation:
                audit.check("observation.web_health", web_healthy, "internal health endpoint")
                audit.check("observation.database_health", database_healthy, "internal database health endpoint")
                _record_observation(
                    audit,
                    args.observation_file,
                    snapshot=snapshot,
                    web_healthy=web_healthy,
                    database_healthy=database_healthy,
                    http_5xx_count=args.http_5xx_count,
                )
            if args.write_observation_metrics:
                audit.check("metrics.web_health", web_healthy, "internal health endpoint")
                audit.check("metrics.database_health", database_healthy, "internal database health endpoint")
                _write_observation_metrics(
                    audit,
                    args.write_observation_metrics,
                    observation_path=args.observation_file,
                    snapshot=snapshot,
                    web_healthy=web_healthy,
                    database_healthy=database_healthy,
                    http_5xx_count=args.http_5xx_count,
                    release_identity=release_identity or "",
                    expected_revision=args.expected_revision,
                )
            if args.initialize_observation:
                _initialize_observation(
                    audit,
                    args.observation_file,
                    deployed_at=dark_since,
                    snapshot=snapshot,
                    release_identity=release_identity or "",
                    expected_revision=args.expected_revision,
                )
            if args.require_observation:
                _verify_observation(
                    audit,
                    args.observation_file,
                    minimum_hours=args.observation_min_hours,
                    maximum_gap_seconds=args.observation_max_gap_seconds,
                    latest_sample_max_age_seconds=args.observation_latest_max_age_seconds,
                    release_identity=release_identity or "",
                    expected_revision=args.expected_revision,
                )
    except Exception as exc:  # Keep credentials and database URLs out of release logs.
        audit.check("runtime.audit_execution", False, f"failed with {exc.__class__.__name__}")
    finally:
        os.chdir(original_cwd)
    audit.render(as_json=args.json)
    return 1 if audit.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
