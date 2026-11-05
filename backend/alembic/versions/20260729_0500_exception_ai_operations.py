"""add exception AI operations controls and telemetry

Revision ID: 20260729_0500
Revises: 20260728_0400
Create Date: 2026-07-29 12:00:00
"""

from __future__ import annotations

import json
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260729_0500"
down_revision = "20260728_0400"
branch_labels = None
depends_on = None


JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
POLICY_SNAPSHOT_KEY = "migration_20260729_0500_policy"
BACKGROUND_JOB_SNAPSHOT_KEY = "migration_20260729_0500_incremental_job"
ACTIVE_DIAGNOSIS_INDEX = "uq_exception_diagnosis_job_active_case_evidence"
SOURCE_BATCH_KINDS = {"import", "inventory_check", "legacy"}
POLICY_CONTROL_COLUMNS = (
    "manual_ai_enabled",
    "scheduled_ai_enabled",
    "full_scan_enabled",
    "digest_enabled",
    "manual_ai_daily_limit",
    "scheduled_ai_daily_limit",
    "scheduled_ai_batch_limit",
    "ai_concurrency",
)


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def _check_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_check_constraints(table) if constraint.get("name")}


def _foreign_key_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_foreign_keys(table) if constraint.get("name")}


def _batch_options(bind: sa.Connection) -> dict[str, object]:
    if bind.dialect.name == "sqlite":
        return {"reflect_kwargs": {"resolve_fks": False}}
    return {}


def _settings_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


def _timestamp_snapshot(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _timestamp_restore(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _write_policy_settings(bind: sa.Connection, policy_id: int, settings: dict[str, object] | None) -> None:
    if settings is None:
        bind.execute(
            sa.text("UPDATE exception_policy SET settings_json = NULL WHERE id = :policy_id"),
            {"policy_id": policy_id},
        )
        return
    statement = sa.text(
        "UPDATE exception_policy SET settings_json = :settings_json WHERE id = :policy_id"
    ).bindparams(sa.bindparam("settings_json", type_=JSON))
    bind.execute(statement, {"settings_json": settings, "policy_id": policy_id})


def _write_background_payload(bind: sa.Connection, job_id: int, payload: dict[str, object]) -> None:
    statement = sa.text(
        "UPDATE exception_background_job SET payload_json = :payload_json WHERE id = :job_id"
    ).bindparams(sa.bindparam("payload_json", type_=JSON))
    bind.execute(statement, {"payload_json": payload, "job_id": job_id})


def _incremental_job_reference(payload: dict[str, object]) -> tuple[str, int] | None:
    kind = payload.get("source_batch_kind")
    batch_id = payload.get("source_batch_id")
    if kind is None and batch_id is None:
        return None
    if kind not in SOURCE_BATCH_KINDS or batch_id is None or isinstance(batch_id, bool):
        raise ValueError("ambiguous source batch reference")
    try:
        normalized_id = int(batch_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("ambiguous source batch reference") from exc
    if normalized_id <= 0:
        raise ValueError("ambiguous source batch reference")
    return str(kind), normalized_id


def _snapshot_incremental_job(row: sa.RowMapping, payload: dict[str, object]) -> dict[str, object]:
    updated = dict(payload)
    updated[BACKGROUND_JOB_SNAPSHOT_KEY] = {
        "payload": payload,
        "dedupe_key": row["dedupe_key"],
        "status": row["status"],
        "error_message": row["error_message"],
        "completed_at": _timestamp_snapshot(row["completed_at"]),
        "lease_owner": row["lease_owner"],
        "lease_expires_at": _timestamp_snapshot(row["lease_expires_at"]),
    }
    return updated


def _quarantine_incremental_job(
    bind: sa.Connection,
    row: sa.RowMapping,
    payload: dict[str, object],
    *,
    reason: str,
) -> None:
    _write_background_payload(bind, int(row["id"]), _snapshot_incremental_job(row, payload))
    bind.execute(
        sa.text(
            """
            UPDATE exception_background_job
            SET status = CASE WHEN status IN ('queued','processing') THEN 'failed' ELSE status END,
                completed_at = CASE
                    WHEN status IN ('queued','processing') THEN COALESCE(completed_at, created_at)
                    ELSE completed_at
                END,
                lease_owner = NULL,
                lease_expires_at = NULL,
                dedupe_key = NULL,
                error_message = :reason
            WHERE id = :job_id
            """
        ),
        {"job_id": int(row["id"]), "reason": reason},
    )


def _normalize_background_incremental_jobs(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table("exception_background_job"):
        return
    rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id, payload_json, dedupe_key, status, error_message, completed_at,
                       lease_owner, lease_expires_at
                FROM exception_background_job
                WHERE job_type = 'incremental_scan'
                ORDER BY id
                """
            )
        ).mappings()
    )
    grouped: dict[str, list[tuple[sa.RowMapping, dict[str, object], tuple[str, int] | None]]] = {}
    for row in rows:
        payload = _settings_mapping(row["payload_json"])
        try:
            reference = _incremental_job_reference(payload)
        except ValueError:
            _quarantine_incremental_job(
                bind,
                row,
                payload,
                reason="legacy_incremental_job_missing_typed_batch_reference",
            )
            continue
        canonical = (
            f"incremental:{reference[0]}:{reference[1]}"
            if reference is not None
            else "incremental:global"
        )
        grouped.setdefault(canonical, []).append((row, payload, reference))

    for canonical, candidates in grouped.items():
        keeper = min(
            candidates,
            key=lambda item: (
                item[0]["dedupe_key"] != canonical,
                item[0]["status"] != "processing",
                -int(item[0]["id"]),
            ),
        )
        for candidate in candidates:
            if candidate is keeper:
                continue
            row, payload, _reference = candidate
            _quarantine_incremental_job(
                bind,
                row,
                payload,
                reason="duplicate_incremental_job_typed_batch_namespace",
            )
        row, payload, reference = keeper
        normalized_payload = dict(payload)
        if reference is not None:
            normalized_payload["source_batch_kind"] = reference[0]
            normalized_payload["source_batch_id"] = reference[1]
        if row["dedupe_key"] != canonical or normalized_payload != payload:
            migrated_payload = _snapshot_incremental_job(row, payload)
            if reference is not None:
                migrated_payload["source_batch_kind"] = reference[0]
                migrated_payload["source_batch_id"] = reference[1]
            _write_background_payload(bind, int(row["id"]), migrated_payload)
            bind.execute(
                sa.text("UPDATE exception_background_job SET dedupe_key = :dedupe_key WHERE id = :job_id"),
                {"job_id": int(row["id"]), "dedupe_key": canonical},
            )


def _restore_background_incremental_jobs(bind: sa.Connection) -> None:
    if not sa.inspect(bind).has_table("exception_background_job"):
        return
    rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id, payload_json
                FROM exception_background_job
                WHERE job_type = 'incremental_scan'
                ORDER BY id
                """
            )
        ).mappings()
    )
    restorable: list[tuple[int, dict[str, object]]] = []
    for row in rows:
        payload = _settings_mapping(row["payload_json"])
        snapshot = payload.get(BACKGROUND_JOB_SNAPSHOT_KEY)
        if isinstance(snapshot, dict) and isinstance(snapshot.get("payload"), dict):
            restorable.append((int(row["id"]), snapshot))
    for job_id, _snapshot in restorable:
        bind.execute(
            sa.text("UPDATE exception_background_job SET dedupe_key = NULL WHERE id = :job_id"),
            {"job_id": job_id},
        )
    restore_statement = sa.text(
        """
        UPDATE exception_background_job
        SET dedupe_key = :dedupe_key,
            status = :status,
            error_message = :error_message,
            completed_at = :completed_at,
            lease_owner = :lease_owner,
            lease_expires_at = :lease_expires_at
        WHERE id = :job_id
        """
    ).bindparams(
        sa.bindparam("completed_at", type_=sa.DateTime(timezone=True)),
        sa.bindparam("lease_expires_at", type_=sa.DateTime(timezone=True)),
    )
    for job_id, snapshot in restorable:
        _write_background_payload(bind, job_id, dict(snapshot["payload"]))
        completed_at = snapshot.get("completed_at")
        lease_expires_at = snapshot.get("lease_expires_at")
        bind.execute(
            restore_statement,
            {
                "job_id": job_id,
                "dedupe_key": snapshot.get("dedupe_key"),
                "status": snapshot.get("status"),
                "error_message": snapshot.get("error_message"),
                "completed_at": _timestamp_restore(completed_at),
                "lease_owner": snapshot.get("lease_owner"),
                "lease_expires_at": _timestamp_restore(lease_expires_at),
            },
        )


def _restore_policy_controls(bind: sa.Connection) -> None:
    rows = bind.execute(
        sa.text("SELECT id, settings_json FROM exception_policy ORDER BY id")
    ).mappings().all()
    for row in rows:
        original_settings = row["settings_json"]
        settings = _settings_mapping(original_settings)
        snapshot = settings.get(POLICY_SNAPSHOT_KEY)
        if not isinstance(snapshot, dict):
            continue
        values = {column: snapshot[column] for column in POLICY_CONTROL_COLUMNS if column in snapshot}
        if values:
            assignments = ", ".join(f"{column} = :{column}" for column in values)
            bind.execute(
                sa.text(f"UPDATE exception_policy SET {assignments} WHERE id = :policy_id"),
                {**values, "policy_id": row["id"]},
            )
        settings.pop(POLICY_SNAPSHOT_KEY, None)
        restored_settings = None if snapshot.get("settings_was_null") and not settings else settings
        _write_policy_settings(bind, int(row["id"]), restored_settings)


def _snapshot_policy_controls(bind: sa.Connection) -> None:
    available = _column_names(sa.inspect(bind), "exception_policy")
    selected_columns = [column for column in POLICY_CONTROL_COLUMNS if column in available]
    if not selected_columns:
        return
    rows = bind.execute(
        sa.text(
            f"SELECT id, settings_json, {', '.join(selected_columns)} "
            "FROM exception_policy ORDER BY id"
        )
    ).mappings().all()
    for row in rows:
        original_settings = row["settings_json"]
        settings = _settings_mapping(original_settings)
        snapshot = {column: row[column] for column in selected_columns}
        snapshot["settings_was_null"] = original_settings is None
        settings[POLICY_SNAPSHOT_KEY] = snapshot
        _write_policy_settings(bind, int(row["id"]), settings)


def _add_diagnosis_telemetry(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table("exception_diagnosis"):
        return

    columns = _column_names(inspector, "exception_diagnosis")
    additions = (
        ("prompt_version", sa.Column("prompt_version", sa.String(80), nullable=True)),
        ("contract_version", sa.Column("contract_version", sa.String(80), nullable=True)),
        ("provider_request_id", sa.Column("provider_request_id", sa.String(160), nullable=True)),
        ("latency_ms", sa.Column("latency_ms", sa.Integer(), nullable=True)),
        ("prompt_tokens", sa.Column("prompt_tokens", sa.Integer(), nullable=True)),
        ("completion_tokens", sa.Column("completion_tokens", sa.Integer(), nullable=True)),
        ("total_tokens", sa.Column("total_tokens", sa.Integer(), nullable=True)),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("exception_diagnosis", column)

    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "exception_diagnosis")
    for column in ("prompt_version", "contract_version", "provider_request_id"):
        index_name = f"ix_exception_diagnosis_{column}"
        if index_name not in indexes:
            op.create_index(index_name, "exception_diagnosis", [column])

    inspector = sa.inspect(bind)
    checks = _check_names(inspector, "exception_diagnosis")
    constraints = (
        ("ck_exception_diagnosis_latency_nonnegative", "latency_ms IS NULL OR latency_ms >= 0"),
        (
            "ck_exception_diagnosis_prompt_tokens_nonnegative",
            "prompt_tokens IS NULL OR prompt_tokens >= 0",
        ),
        (
            "ck_exception_diagnosis_completion_tokens_nonnegative",
            "completion_tokens IS NULL OR completion_tokens >= 0",
        ),
        ("ck_exception_diagnosis_total_tokens_nonnegative", "total_tokens IS NULL OR total_tokens >= 0"),
    )
    missing_constraints = [(name, expression) for name, expression in constraints if name not in checks]
    if missing_constraints:
        with op.batch_alter_table("exception_diagnosis", **_batch_options(bind)) as batch_op:
            for name, expression in missing_constraints:
                batch_op.create_check_constraint(name, expression)


def _add_job_cancellation(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table("exception_diagnosis_job"):
        return
    columns = _column_names(inspector, "exception_diagnosis_job")
    if "cancel_requested_at" not in columns:
        op.add_column(
            "exception_diagnosis_job",
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "cancel_requested_by_user_id" not in columns:
        op.add_column(
            "exception_diagnosis_job",
            sa.Column("cancel_requested_by_user_id", sa.Integer(), nullable=True),
        )
    inspector = sa.inspect(bind)
    if (
        "fk_exception_diagnosis_job_cancel_requested_by_user_id_users"
        not in _foreign_key_names(inspector, "exception_diagnosis_job")
    ):
        with op.batch_alter_table("exception_diagnosis_job", **_batch_options(bind)) as batch_op:
            batch_op.create_foreign_key(
                "fk_exception_diagnosis_job_cancel_requested_by_user_id_users",
                "users",
                ["cancel_requested_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )
    indexes = _index_names(sa.inspect(bind), "exception_diagnosis_job")
    for column in ("cancel_requested_at", "cancel_requested_by_user_id"):
        index_name = f"ix_exception_diagnosis_job_{column}"
        if index_name not in indexes:
            op.create_index(index_name, "exception_diagnosis_job", [column])


def _add_active_diagnosis_job_unique_index(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table("exception_diagnosis_job"):
        return
    rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id, case_id, evidence_version, status
                FROM exception_diagnosis_job
                WHERE status IN ('queued','processing')
                ORDER BY case_id, evidence_version,
                         CASE WHEN status = 'processing' THEN 0 ELSE 1 END,
                         id DESC
                """
            )
        ).mappings()
    )
    seen: set[tuple[int, str]] = set()
    duplicate_ids: list[int] = []
    for row in rows:
        key = (int(row["case_id"]), str(row["evidence_version"]))
        if key in seen:
            duplicate_ids.append(int(row["id"]))
        else:
            seen.add(key)
    if duplicate_ids:
        raise RuntimeError(
            "duplicate active diagnosis jobs must be reconciled before applying 20260729_0500"
        )
    if ACTIVE_DIAGNOSIS_INDEX in _index_names(sa.inspect(bind), "exception_diagnosis_job"):
        return
    where = sa.text("status IN ('queued','processing')")
    dialect_options: dict[str, object] = {}
    if bind.dialect.name == "postgresql":
        dialect_options["postgresql_where"] = where
    elif bind.dialect.name == "sqlite":
        dialect_options["sqlite_where"] = where
    else:
        return
    op.create_index(
        ACTIVE_DIAGNOSIS_INDEX,
        "exception_diagnosis_job",
        ["case_id", "evidence_version"],
        unique=True,
        **dialect_options,
    )


def _add_source_batch_kind(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table("exception_case"):
        return
    columns = _column_names(inspector, "exception_case")
    if "source_batch_kind" not in columns:
        op.add_column(
            "exception_case",
            sa.Column(
                "source_batch_kind",
                sa.String(40),
                nullable=True,
            ),
        )
    bind.execute(
        sa.text(
            """
            UPDATE exception_case
            SET source_batch_kind = CASE
                WHEN source_type IN ('latest_inventory_check', 'inventory_check_result')
                    THEN 'inventory_check'
                WHEN source_type IN (
                    'inventory_anomaly_case', 'inventory_flow_ledger',
                    'inventory_snapshot_quality', 'latest_receivable_check',
                    'import_batch', 'data_calendar_rule', 'master_link_issue'
                )
                    THEN 'import'
                ELSE 'legacy'
            END
            WHERE source_batch_id IS NOT NULL
            """
        )
    )
    indexes = _index_names(sa.inspect(bind), "exception_case")
    if "ix_exception_case_source_batch_kind" not in indexes:
        op.create_index(
            "ix_exception_case_source_batch_kind",
            "exception_case",
            ["source_batch_kind"],
        )
    if "ix_exception_case_source_batch_ref" not in indexes:
        op.create_index(
            "ix_exception_case_source_batch_ref",
            "exception_case",
            ["source_batch_kind", "source_batch_id"],
        )
    checks = _check_names(sa.inspect(bind), "exception_case")
    if "ck_exception_case_source_batch_ref_pair" not in checks:
        with op.batch_alter_table("exception_case", **_batch_options(bind)) as batch_op:
            batch_op.create_check_constraint(
                "ck_exception_case_source_batch_ref_pair",
                "(source_batch_kind IS NULL AND source_batch_id IS NULL) OR "
                "(source_batch_kind IS NOT NULL AND "
                "source_batch_kind IN ('import','inventory_check','legacy') AND source_batch_id IS NOT NULL)",
            )


def _add_policy_controls(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table("exception_policy"):
        return

    columns = _column_names(inspector, "exception_policy")
    additions = (
        (
            "manual_ai_enabled",
            sa.Column("manual_ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
        (
            "scheduled_ai_enabled",
            sa.Column("scheduled_ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
        (
            "full_scan_enabled",
            sa.Column("full_scan_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
        ("digest_enabled", sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.false())),
        (
            "manual_ai_daily_limit",
            sa.Column("manual_ai_daily_limit", sa.Integer(), nullable=False, server_default="20"),
        ),
        (
            "scheduled_ai_daily_limit",
            sa.Column("scheduled_ai_daily_limit", sa.Integer(), nullable=False, server_default="0"),
        ),
        (
            "scheduled_ai_batch_limit",
            sa.Column("scheduled_ai_batch_limit", sa.Integer(), nullable=False, server_default="20"),
        ),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("exception_policy", column)

    # Server defaults leave existing policies disabled without rewriting the
    # pre-existing ai_concurrency value. A downgrade snapshot is restored when
    # this revision is applied again during a rollback rehearsal.
    _restore_policy_controls(bind)

    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "exception_policy")
    for column in ("manual_ai_enabled", "scheduled_ai_enabled", "full_scan_enabled", "digest_enabled"):
        index_name = f"ix_exception_policy_{column}"
        if index_name not in indexes:
            op.create_index(index_name, "exception_policy", [column])

    inspector = sa.inspect(bind)
    checks = _check_names(inspector, "exception_policy")
    constraints = (
        ("ck_exception_policy_manual_daily_limit", "manual_ai_daily_limit >= 0"),
        ("ck_exception_policy_scheduled_daily_limit", "scheduled_ai_daily_limit >= 0"),
        ("ck_exception_policy_scheduled_batch_limit", "scheduled_ai_batch_limit > 0"),
    )
    missing_constraints = [(name, expression) for name, expression in constraints if name not in checks]
    if missing_constraints:
        with op.batch_alter_table("exception_policy", **_batch_options(bind)) as batch_op:
            batch_op.alter_column(
                "ai_concurrency",
                existing_type=sa.Integer(),
                existing_nullable=False,
                server_default="1",
            )
            for name, expression in missing_constraints:
                batch_op.create_check_constraint(name, expression)
    else:
        with op.batch_alter_table("exception_policy", **_batch_options(bind)) as batch_op:
            batch_op.alter_column(
                "ai_concurrency",
                existing_type=sa.Integer(),
                existing_nullable=False,
                server_default="1",
            )


def _create_service_heartbeat(bind: sa.Connection) -> None:
    if sa.inspect(bind).has_table("exception_service_heartbeat"):
        return
    op.create_table(
        "exception_service_heartbeat",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_type", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(160), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata_json", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("service_type", "instance_id", name="uq_exception_service_heartbeat_instance"),
        sa.CheckConstraint(
            "service_type IN ('worker','ai_worker','scheduler')",
            name="ck_exception_service_heartbeat_type",
        ),
    )
    for column in ("service_type", "instance_id", "started_at", "last_heartbeat_at"):
        op.create_index(f"ix_exception_service_heartbeat_{column}", "exception_service_heartbeat", [column])


def upgrade() -> None:
    bind = op.get_bind()
    _add_source_batch_kind(bind)
    _normalize_background_incremental_jobs(bind)
    _add_diagnosis_telemetry(bind)
    _add_job_cancellation(bind)
    _add_active_diagnosis_job_unique_index(bind)
    _add_policy_controls(bind)
    _create_service_heartbeat(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _restore_background_incremental_jobs(bind)

    if inspector.has_table("exception_service_heartbeat"):
        op.drop_table("exception_service_heartbeat")

    inspector = sa.inspect(bind)
    if inspector.has_table("exception_case"):
        indexes = _index_names(inspector, "exception_case")
        for index_name in (
            "ix_exception_case_source_batch_ref",
            "ix_exception_case_source_batch_kind",
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="exception_case")
        columns = _column_names(sa.inspect(bind), "exception_case")
        checks = _check_names(sa.inspect(bind), "exception_case")
        if "source_batch_kind" in columns:
            with op.batch_alter_table("exception_case", **_batch_options(bind)) as batch_op:
                if "ck_exception_case_source_batch_ref_pair" in checks:
                    batch_op.drop_constraint("ck_exception_case_source_batch_ref_pair", type_="check")
                batch_op.drop_column("source_batch_kind")

    inspector = sa.inspect(bind)
    if inspector.has_table("exception_policy"):
        _snapshot_policy_controls(bind)
        indexes = _index_names(inspector, "exception_policy")
        policy_columns = (
            "manual_ai_enabled",
            "scheduled_ai_enabled",
            "full_scan_enabled",
            "digest_enabled",
        )
        for column in policy_columns:
            index_name = f"ix_exception_policy_{column}"
            if index_name in indexes:
                op.drop_index(index_name, table_name="exception_policy")
        columns = _column_names(sa.inspect(bind), "exception_policy")
        checks = _check_names(sa.inspect(bind), "exception_policy")
        with op.batch_alter_table("exception_policy", **_batch_options(bind)) as batch_op:
            batch_op.alter_column(
                "ai_concurrency",
                existing_type=sa.Integer(),
                existing_nullable=False,
                server_default="2",
            )
            for constraint_name in (
                "ck_exception_policy_scheduled_batch_limit",
                "ck_exception_policy_scheduled_daily_limit",
                "ck_exception_policy_manual_daily_limit",
            ):
                if constraint_name in checks:
                    batch_op.drop_constraint(constraint_name, type_="check")
            for column in (
                "scheduled_ai_batch_limit",
                "scheduled_ai_daily_limit",
                "manual_ai_daily_limit",
                "digest_enabled",
                "full_scan_enabled",
                "scheduled_ai_enabled",
                "manual_ai_enabled",
            ):
                if column in columns:
                    batch_op.drop_column(column)

    inspector = sa.inspect(bind)
    if inspector.has_table("exception_diagnosis_job"):
        indexes = _index_names(inspector, "exception_diagnosis_job")
        if ACTIVE_DIAGNOSIS_INDEX in indexes:
            op.drop_index(ACTIVE_DIAGNOSIS_INDEX, table_name="exception_diagnosis_job")
            indexes.remove(ACTIVE_DIAGNOSIS_INDEX)
        for column in ("cancel_requested_by_user_id", "cancel_requested_at"):
            index_name = f"ix_exception_diagnosis_job_{column}"
            if index_name in indexes:
                op.drop_index(index_name, table_name="exception_diagnosis_job")
        columns = _column_names(sa.inspect(bind), "exception_diagnosis_job")
        foreign_keys = _foreign_key_names(sa.inspect(bind), "exception_diagnosis_job")
        with op.batch_alter_table("exception_diagnosis_job", **_batch_options(bind)) as batch_op:
            foreign_key_name = "fk_exception_diagnosis_job_cancel_requested_by_user_id_users"
            if foreign_key_name in foreign_keys:
                batch_op.drop_constraint(foreign_key_name, type_="foreignkey")
            for column in ("cancel_requested_by_user_id", "cancel_requested_at"):
                if column in columns:
                    batch_op.drop_column(column)

    inspector = sa.inspect(bind)
    if inspector.has_table("exception_diagnosis"):
        indexes = _index_names(inspector, "exception_diagnosis")
        for column in ("provider_request_id", "contract_version", "prompt_version"):
            index_name = f"ix_exception_diagnosis_{column}"
            if index_name in indexes:
                op.drop_index(index_name, table_name="exception_diagnosis")
        columns = _column_names(sa.inspect(bind), "exception_diagnosis")
        checks = _check_names(sa.inspect(bind), "exception_diagnosis")
        with op.batch_alter_table("exception_diagnosis", **_batch_options(bind)) as batch_op:
            for constraint_name in (
                "ck_exception_diagnosis_total_tokens_nonnegative",
                "ck_exception_diagnosis_completion_tokens_nonnegative",
                "ck_exception_diagnosis_prompt_tokens_nonnegative",
                "ck_exception_diagnosis_latency_nonnegative",
            ):
                if constraint_name in checks:
                    batch_op.drop_constraint(constraint_name, type_="check")
            for column in (
                "total_tokens",
                "completion_tokens",
                "prompt_tokens",
                "latency_ms",
                "provider_request_id",
                "contract_version",
                "prompt_version",
            ):
                if column in columns:
                    batch_op.drop_column(column)
