"""unified exception diagnosis and remediation center

Revision ID: 20260728_0200
Revises: 20260728_0100
Create Date: 2026-07-28 16:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260728_0200"
down_revision = "20260728_0100"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

PERMISSIONS = (
    ("exception_center.view", "查看异常中心", "exception_center", "view"),
    ("exception_center.diagnose", "发起异常智能诊断", "exception_center", "diagnose"),
    ("exception_center.manage", "管理异常案件", "exception_center", "manage"),
    ("exception_center.action_execute", "执行异常修复动作", "exception_center", "action_execute"),
    ("exception_center.policy_manage", "管理异常巡检策略", "exception_center", "policy_manage"),
)

ROLE_GRANTS = {
    "admin": [item[0] for item in PERMISSIONS],
    "boss": ["exception_center.view"],
    "data_middle_office": [
        "exception_center.view",
        "exception_center.diagnose",
        "exception_center.manage",
        "exception_center.action_execute",
    ],
    "business_middle_office": [
        "exception_center.view",
        "exception_center.diagnose",
        "exception_center.manage",
        "exception_center.action_execute",
    ],
}


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "exception_case",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_no", sa.String(120), nullable=False, unique=True),
        sa.Column("fingerprint", sa.String(128), nullable=False, unique=True),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("rule_code", sa.String(160), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(40), nullable=False, server_default="warning"),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("resource_type", sa.String(120)),
        sa.Column("resource_id", sa.String(160)),
        sa.Column("resource_code", sa.String(160)),
        sa.Column("resource_name", sa.String(255)),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", sa.String(160)),
        sa.Column("source_batch_id", sa.Integer()),
        sa.Column("inventory_anomaly_case_id", sa.Integer(), sa.ForeignKey("inventory_anomaly_case.id", ondelete="SET NULL")),
        sa.Column("data_date", sa.Date()),
        sa.Column("evidence_version", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("initial_guidance", sa.Text()),
        sa.Column("action_path", sa.String(500)),
        sa.Column("affected_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affected_amount", sa.Numeric(18, 2)),
        sa.Column("affected_quantity", sa.Numeric(18, 4)),
        sa.Column("assignee_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("ignored_until", sa.DateTime(timezone=True)),
        sa.Column("resolution_note", sa.Text()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", JSON),
        *_timestamps(),
        sa.CheckConstraint("domain IN ('inventory','receivable','master_data','import')", name="ck_exception_case_domain"),
        sa.CheckConstraint("severity IN ('warning','high','critical')", name="ck_exception_case_severity"),
        sa.CheckConstraint("status IN ('open','action_required','processing','blocked','resolved','ignored')", name="ck_exception_case_status"),
    )
    _indexes(
        "exception_case",
        (
            "case_no", "fingerprint", "domain", "rule_code", "severity", "status", "resource_type", "resource_id",
            "resource_code", "resource_name", "source_type", "source_id", "source_batch_id", "inventory_anomaly_case_id",
            "data_date", "evidence_version", "assignee_user_id", "due_at", "detected_at", "last_seen_at", "resolved_at",
            "ignored_until", "verified_at",
        ),
    )

    op.create_table(
        "exception_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_version", sa.String(128), nullable=False),
        sa.Column("data_json", JSON, nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_timestamps(),
        sa.UniqueConstraint("case_id", "evidence_version", name="uq_exception_evidence_case_version"),
    )
    _indexes("exception_evidence", ("case_id", "evidence_version", "collected_at"))

    op.create_table(
        "exception_diagnosis_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_no", sa.String(120), nullable=False, unique=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_version", sa.String(128), nullable=False),
        sa.Column("trigger_type", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("trigger_type IN ('manual','scheduled')", name="ck_exception_diagnosis_job_trigger"),
        sa.CheckConstraint("status IN ('queued','processing','completed','failed','cancelled')", name="ck_exception_diagnosis_job_status"),
    )
    _indexes("exception_diagnosis_job", ("job_no", "case_id", "evidence_version", "trigger_type", "status", "requested_by_user_id", "available_at", "lease_owner", "lease_expires_at", "started_at", "completed_at"))
    op.create_index("ix_exception_diagnosis_job_active_lookup", "exception_diagnosis_job", ["case_id", "evidence_version", "status"])

    op.create_table(
        "exception_background_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_no", sa.String(120), nullable=False, unique=True),
        sa.Column("job_type", sa.String(40), nullable=False),
        sa.Column("payload_json", JSON),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("dedupe_key", sa.String(160), unique=True),
        *_timestamps(),
        sa.CheckConstraint("job_type IN ('full_scan','incremental_scan','digest')", name="ck_exception_background_job_type"),
        sa.CheckConstraint("status IN ('queued','processing','completed','failed','cancelled')", name="ck_exception_background_job_status"),
    )
    _indexes("exception_background_job", ("job_no", "job_type", "status", "available_at", "lease_owner", "lease_expires_at", "started_at", "completed_at", "dedupe_key"))

    op.create_table(
        "exception_diagnosis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("exception_diagnosis_job.id", ondelete="SET NULL")),
        sa.Column("evidence_version", sa.String(128), nullable=False),
        sa.Column("root_cause_code", sa.String(120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("disposition", sa.String(40), nullable=False),
        sa.Column("evidence_refs_json", JSON, nullable=False),
        sa.Column("impact_json", JSON, nullable=False),
        sa.Column("recommended_steps_json", JSON, nullable=False),
        sa.Column("missing_evidence_json", JSON, nullable=False),
        sa.Column("model_name", sa.String(160)),
        sa.Column("request_id", sa.String(160)),
        sa.Column("diagnosed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_timestamps(),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_exception_diagnosis_confidence"),
        sa.CheckConstraint("disposition IN ('actionable','manual_review','blocked')", name="ck_exception_diagnosis_disposition"),
    )
    _indexes("exception_diagnosis", ("case_id", "job_id", "evidence_version", "root_cause_code", "disposition", "request_id", "diagnosed_at"))
    op.create_index("ix_exception_diagnosis_case_version_time", "exception_diagnosis", ["case_id", "evidence_version", "diagnosed_at"])

    op.create_table(
        "exception_action",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_no", sa.String(120), nullable=False, unique=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="validated"),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("blockers_json", JSON),
        sa.Column("parameters_json", JSON),
        sa.Column("impact_json", JSON),
        sa.Column("evidence_version", sa.String(128), nullable=False),
        sa.Column("validation_token_hash", sa.String(128), unique=True),
        sa.Column("validation_expires_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(160), unique=True),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("result_json", JSON),
        sa.Column("verification_json", JSON),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint("status IN ('validated','blocked','executing','completed','failed')", name="ck_exception_action_status"),
    )
    _indexes("exception_action", ("action_no", "case_id", "action_type", "status", "allowed", "evidence_version", "validation_token_hash", "validation_expires_at", "idempotency_key", "requested_by_user_id", "started_at", "completed_at"))

    op.create_table(
        "exception_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("from_status", sa.String(40)),
        sa.Column("to_status", sa.String(40)),
        sa.Column("detail_json", JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    _indexes("exception_event", ("case_id", "event_type", "actor_user_id", "created_at"))

    op.create_table(
        "exception_notification",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notification_type", sa.String(60), nullable=False),
        sa.Column("evidence_version", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("case_id", "user_id", "notification_type", "evidence_version", name="uq_exception_notification_case_user_version"),
    )
    _indexes("exception_notification", ("case_id", "user_id", "notification_type", "is_read", "read_at", "acknowledged_at"))

    op.create_table(
        "exception_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_key", sa.String(80), nullable=False, unique=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("full_scan_cron", sa.String(80), nullable=False, server_default="30 2 * * *"),
        sa.Column("digest_cron", sa.String(80), nullable=False, server_default="30 8 * * *"),
        sa.Column("ai_daily_limit", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("ai_batch_limit", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("ai_concurrency", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("stale_diagnosis_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("settings_json", JSON),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamps(),
        sa.CheckConstraint("ai_daily_limit >= 0", name="ck_exception_policy_daily_limit"),
        sa.CheckConstraint("ai_batch_limit > 0", name="ck_exception_policy_batch_limit"),
        sa.CheckConstraint("ai_concurrency > 0", name="ck_exception_policy_concurrency"),
        sa.CheckConstraint("stale_diagnosis_hours > 0", name="ck_exception_policy_stale_hours"),
    )
    _indexes("exception_policy", ("policy_key", "is_enabled", "updated_by_user_id"))
    op.execute(
        """
        INSERT INTO exception_policy
            (policy_key, is_enabled, full_scan_cron, digest_cron, ai_daily_limit, ai_batch_limit,
             ai_concurrency, stale_diagnosis_hours, created_at, updated_at)
        VALUES ('default', true, '30 2 * * *', '30 8 * * *', 100, 50, 2, 24, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (policy_key) DO NOTHING
        """
    )

    conn = op.get_bind()
    if not sa.inspect(conn).has_table("permissions"):
        return
    for code, name, resource_type, action_type in PERMISSIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO permissions (permission_code, permission_name, resource_type, action_type, created_at, updated_at)
                VALUES (:code, :name, :resource_type, :action_type, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (permission_code) DO NOTHING
                """
            ),
            {"code": code, "name": name, "resource_type": resource_type, "action_type": action_type},
        )
    for role_code, permission_codes in ROLE_GRANTS.items():
        for permission_code in permission_codes:
            conflict_clause = (
                "ON CONFLICT (role_id, permission_id) DO NOTHING"
                if conn.dialect.name == "sqlite"
                else "ON CONFLICT ON CONSTRAINT uq_role_permissions_role_permission DO NOTHING"
            )
            conn.execute(
                sa.text(
                    f"""
                    INSERT INTO role_permissions (role_id, permission_id, created_at)
                    SELECT roles.id, permissions.id, CURRENT_TIMESTAMP
                    FROM roles JOIN permissions ON permissions.permission_code = :permission_code
                    WHERE roles.role_code = :role_code
                    {conflict_clause}
                    """
                ),
                {"role_code": role_code, "permission_code": permission_code},
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if inspector.has_table("permissions"):
        for code, *_ in PERMISSIONS:
            if inspector.has_table("role_permissions"):
                conn.execute(
                    sa.text(
                        """
                        DELETE FROM role_permissions
                        WHERE permission_id IN (SELECT id FROM permissions WHERE permission_code = :code)
                        """
                    ),
                    {"code": code},
                )
            conn.execute(sa.text("DELETE FROM permissions WHERE permission_code = :code"), {"code": code})
    for table in (
        "exception_policy",
        "exception_notification",
        "exception_event",
        "exception_action",
        "exception_diagnosis",
        "exception_background_job",
        "exception_diagnosis_job",
        "exception_evidence",
        "exception_case",
    ):
        op.drop_table(table)
