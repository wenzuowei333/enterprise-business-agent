"""unified global AI data model and legacy CRM backfill

Revision ID: 20260830_0100
Revises: 20260808_0100
Create Date: 2026-08-30 14:00:00
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.services.global_ai_backfill_service import backfill_legacy_global_ai_data


revision = "20260830_0100"
down_revision = "20260808_0100"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _legacy_columns() -> list[sa.Column]:
    return [
        sa.Column("source_system", sa.String(40), nullable=False),
        sa.Column("legacy_type", sa.String(80)),
        sa.Column("legacy_id", sa.String(160)),
    ]


def _indexes(table_name: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table_name}_{column}", table_name, [column])


def _legacy_unique(name: str) -> sa.UniqueConstraint:
    return sa.UniqueConstraint("source_system", "legacy_type", "legacy_id", name=name)


def upgrade() -> None:
    op.create_table(
        "ai_conversation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_no", sa.String(120), nullable=False, unique=True),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("channel", sa.String(80), nullable=False, server_default="web"),
        sa.Column("session_id", sa.String(120)),
        sa.Column("context_type", sa.String(80)),
        sa.Column("context_id", sa.String(160)),
        sa.Column("operation", sa.String(120)),
        sa.Column("status", sa.String(40), nullable=False, server_default="completed"),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("model_name", sa.String(160)),
        *_legacy_columns(),
        sa.Column("metadata_json", JSON),
        *_timestamps(),
        _legacy_unique("uq_ai_conversation_legacy_ref"),
    )
    _indexes(
        "ai_conversation",
        (
            "conversation_no",
            "domain",
            "channel",
            "session_id",
            "context_type",
            "context_id",
            "operation",
            "status",
            "actor_user_id",
            "created_by_user_id",
            "model_name",
            "source_system",
            "legacy_type",
            "legacy_id",
        ),
    )
    op.create_index(
        "ix_ai_conversation_actor_created", "ai_conversation", ["actor_user_id", "created_at"]
    )
    op.create_index("ix_ai_conversation_context", "ai_conversation", ["context_type", "context_id"])

    op.create_table(
        "ai_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_no", sa.String(120), nullable=False, unique=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="completed"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("request_id", sa.String(160)),
        sa.Column("model_name", sa.String(160)),
        sa.Column("contract_version", sa.String(120)),
        sa.Column("source_refs_json", JSON),
        *_legacy_columns(),
        sa.Column("payload_json", JSON),
        *_timestamps(),
        sa.UniqueConstraint("conversation_id", "sequence_no", name="uq_ai_message_conversation_sequence"),
        _legacy_unique("uq_ai_message_legacy_ref"),
        sa.CheckConstraint("role IN ('user','assistant','system','tool')", name="ck_ai_message_role"),
    )
    _indexes(
        "ai_message",
        (
            "message_no",
            "conversation_id",
            "role",
            "status",
            "created_by_user_id",
            "request_id",
            "model_name",
            "contract_version",
            "source_system",
            "legacy_type",
            "legacy_id",
        ),
    )
    op.create_index(
        "ix_ai_message_conversation_created", "ai_message", ["conversation_id", "created_at"]
    )

    op.create_table(
        "ai_insight",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("insight_no", sa.String(120), nullable=False, unique=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversation.id", ondelete="SET NULL")),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("insight_type", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(120)),
        sa.Column("resource_id", sa.String(160)),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.Text()),
        sa.Column("risk_level", sa.String(40)),
        sa.Column("opportunity_level", sa.String(40)),
        sa.Column("confidence_score", sa.Numeric(5, 4)),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("review_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("source_refs_json", JSON),
        sa.Column("evidence_json", JSON),
        sa.Column("model_name", sa.String(160)),
        *_legacy_columns(),
        sa.Column("payload_json", JSON),
        *_timestamps(),
        _legacy_unique("uq_ai_insight_legacy_ref"),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_ai_insight_confidence",
        ),
    )
    _indexes(
        "ai_insight",
        (
            "insight_no",
            "conversation_id",
            "domain",
            "insight_type",
            "resource_type",
            "resource_id",
            "risk_level",
            "opportunity_level",
            "status",
            "review_status",
            "reviewed_by_user_id",
            "reviewed_at",
            "created_by_user_id",
            "model_name",
            "source_system",
            "legacy_type",
            "legacy_id",
        ),
    )
    op.create_index("ix_ai_insight_resource", "ai_insight", ["resource_type", "resource_id"])
    op.create_index("ix_ai_insight_review", "ai_insight", ["review_status", "created_at"])

    op.create_table(
        "ai_context_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_no", sa.String(120), nullable=False, unique=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversation.id", ondelete="SET NULL")),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("context_version", sa.String(160), nullable=False),
        sa.Column("resource_type", sa.String(120)),
        sa.Column("resource_id", sa.String(160)),
        sa.Column("structured_fields_json", JSON, nullable=False),
        sa.Column("source_refs_json", JSON, nullable=False),
        sa.Column("redacted_fields_json", JSON, nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_legacy_columns(),
        *_timestamps(),
        _legacy_unique("uq_ai_context_snapshot_legacy_ref"),
    )
    _indexes(
        "ai_context_snapshot",
        (
            "snapshot_no",
            "conversation_id",
            "domain",
            "context_version",
            "resource_type",
            "resource_id",
            "created_by_user_id",
            "source_system",
            "legacy_type",
            "legacy_id",
        ),
    )
    op.create_index(
        "ix_ai_context_snapshot_resource", "ai_context_snapshot", ["resource_type", "resource_id"]
    )

    op.create_table(
        "ai_action_proposal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_no", sa.String(120), nullable=False, unique=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversation.id", ondelete="SET NULL")),
        sa.Column("insight_id", sa.Integer(), sa.ForeignKey("ai_insight.id", ondelete="SET NULL")),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("action_type", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(120)),
        sa.Column("resource_id", sa.String(160)),
        sa.Column("status", sa.String(40), nullable=False, server_default="proposed"),
        sa.Column("review_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("risk_level", sa.String(40)),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("parameters_json", JSON),
        sa.Column("impact_json", JSON),
        sa.Column("source_refs_json", JSON),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text()),
        *_legacy_columns(),
        *_timestamps(),
        _legacy_unique("uq_ai_action_proposal_legacy_ref"),
    )
    _indexes(
        "ai_action_proposal",
        (
            "proposal_no",
            "conversation_id",
            "insight_id",
            "domain",
            "action_type",
            "resource_type",
            "resource_id",
            "status",
            "review_status",
            "risk_level",
            "created_by_user_id",
            "reviewed_by_user_id",
            "reviewed_at",
            "source_system",
            "legacy_type",
            "legacy_id",
        ),
    )
    op.create_index(
        "ix_ai_action_proposal_resource", "ai_action_proposal", ["resource_type", "resource_id"]
    )

    op.create_table(
        "ai_action_execution",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("execution_no", sa.String(120), nullable=False, unique=True),
        sa.Column("proposal_id", sa.Integer(), sa.ForeignKey("ai_action_proposal.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("executor_identity", sa.String(120)),
        sa.Column("request_json", JSON),
        sa.Column("result_json", JSON),
        sa.Column("verification_json", JSON),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_legacy_columns(),
        *_timestamps(),
        _legacy_unique("uq_ai_action_execution_legacy_ref"),
        sa.CheckConstraint("attempts >= 0", name="ck_ai_action_execution_attempts"),
    )
    _indexes(
        "ai_action_execution",
        (
            "execution_no",
            "proposal_id",
            "idempotency_key",
            "status",
            "requested_by_user_id",
            "approved_by_user_id",
            "executor_identity",
            "error_code",
            "started_at",
            "completed_at",
            "source_system",
            "legacy_type",
            "legacy_id",
        ),
    )

    op.create_table(
        "ai_usage_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_no", sa.String(120), nullable=False, unique=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversation.id", ondelete="SET NULL")),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("ai_message.id", ondelete="SET NULL")),
        sa.Column("insight_id", sa.Integer(), sa.ForeignKey("ai_insight.id", ondelete="SET NULL")),
        sa.Column("request_id", sa.String(160)),
        sa.Column("provider_request_id", sa.String(160)),
        sa.Column("service_identity", sa.String(120), nullable=False),
        sa.Column("domain", sa.String(60), nullable=False),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("model_name", sa.String(160)),
        sa.Column("prompt_version", sa.String(120)),
        sa.Column("contract_version", sa.String(120)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        *_legacy_columns(),
        sa.Column("metadata_json", JSON),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _legacy_unique("uq_ai_usage_event_legacy_ref"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_ai_usage_event_latency"),
        sa.CheckConstraint("prompt_tokens IS NULL OR prompt_tokens >= 0", name="ck_ai_usage_event_prompt_tokens"),
        sa.CheckConstraint("completion_tokens IS NULL OR completion_tokens >= 0", name="ck_ai_usage_event_completion_tokens"),
        sa.CheckConstraint("total_tokens IS NULL OR total_tokens >= 0", name="ck_ai_usage_event_total_tokens"),
        sa.CheckConstraint("attempts >= 0", name="ck_ai_usage_event_attempts"),
    )
    _indexes(
        "ai_usage_event",
        (
            "event_no",
            "conversation_id",
            "message_id",
            "insight_id",
            "request_id",
            "provider_request_id",
            "service_identity",
            "domain",
            "operation",
            "status",
            "model_name",
            "prompt_version",
            "contract_version",
            "source_system",
            "legacy_type",
            "legacy_id",
            "occurred_at",
        ),
    )
    op.create_index("ix_ai_usage_event_domain_occurred", "ai_usage_event", ["domain", "occurred_at"])

    op.create_table(
        "ai_security_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_no", sa.String(120), nullable=False, unique=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(40), nullable=False, server_default="info"),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("service_identity", sa.String(120)),
        sa.Column("domain", sa.String(60)),
        sa.Column("resource_type", sa.String(120)),
        sa.Column("resource_id", sa.String(160)),
        sa.Column("request_id", sa.String(160)),
        sa.Column("detail_json", JSON),
        *_legacy_columns(),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _legacy_unique("uq_ai_security_event_legacy_ref"),
    )
    _indexes(
        "ai_security_event",
        (
            "event_no",
            "event_type",
            "severity",
            "outcome",
            "actor_user_id",
            "service_identity",
            "domain",
            "resource_type",
            "resource_id",
            "request_id",
            "source_system",
            "legacy_type",
            "legacy_id",
            "occurred_at",
        ),
    )
    op.create_index(
        "ix_ai_security_event_type_occurred", "ai_security_event", ["event_type", "occurred_at"]
    )

    if not context.is_offline_mode():
        backfill_legacy_global_ai_data(op.get_bind())


def downgrade() -> None:
    # Legacy CRM tables are the source of truth throughout stage 2 and are never modified.
    for table_name in (
        "ai_security_event",
        "ai_usage_event",
        "ai_action_execution",
        "ai_action_proposal",
        "ai_context_snapshot",
        "ai_insight",
        "ai_message",
        "ai_conversation",
    ):
        op.drop_table(table_name)
