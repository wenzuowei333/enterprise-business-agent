"""external inventory anomaly agent

Revision ID: 20260728_0100
Revises: 20260724_0100
Create Date: 2026-07-28 10:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260728_0100"
down_revision = "20260724_0100"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "inventory_anomaly_case",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_no", sa.String(120), nullable=False, unique=True),
        sa.Column("fingerprint", sa.String(128), nullable=False, unique=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("inventory_snapshot.id", ondelete="SET NULL")),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batch.id", ondelete="SET NULL")),
        sa.Column("data_date", sa.Date()),
        sa.Column("product_code", sa.String(120)),
        sa.Column("product_name", sa.String(255)),
        sa.Column("warehouse_name", sa.String(160)),
        sa.Column("warehouse_scope", sa.String(40)),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(40), nullable=False, server_default="high"),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("stock_qty", sa.Numeric(18, 4)),
        sa.Column("locked_qty", sa.Numeric(18, 4)),
        sa.Column("evidence_version", sa.String(128), nullable=False),
        sa.Column("root_cause", sa.String(80)),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("diagnosis_json", JSON),
        sa.Column("recommended_action", sa.String(80)),
        sa.Column("expected_result", sa.Text()),
        sa.Column("resolution_note", sa.Text()),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("diagnosed_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in (
        "case_no", "fingerprint", "snapshot_id", "batch_id", "data_date", "product_code", "product_name",
        "warehouse_name", "warehouse_scope", "reason_code", "severity", "status", "evidence_version",
        "root_cause", "recommended_action", "detected_at", "diagnosed_at", "resolved_at",
    ):
        op.create_index(f"ix_inventory_anomaly_case_{column}", "inventory_anomaly_case", [column])

    op.create_table(
        "inventory_remediation_action",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_no", sa.String(120), nullable=False, unique=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("inventory_anomaly_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_key_id", sa.String(120), sa.ForeignKey("external_api_keys.key_id", ondelete="SET NULL")),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="validated"),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("blockers_json", JSON),
        sa.Column("parameters_json", JSON),
        sa.Column("impact_json", JSON),
        sa.Column("evidence_version", sa.String(128), nullable=False),
        sa.Column("validation_token_hash", sa.String(128), unique=True),
        sa.Column("validation_expires_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(160), unique=True),
        sa.Column("before_data", JSON),
        sa.Column("result_json", JSON),
        sa.Column("verification_json", JSON),
        sa.Column("compensation_json", JSON),
        sa.Column("upstream_reference", sa.String(255)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in (
        "action_no", "case_id", "requested_by_key_id", "action_type", "status", "allowed",
        "evidence_version", "validation_token_hash", "validation_expires_at", "idempotency_key",
        "upstream_reference", "started_at", "completed_at",
    ):
        op.create_index(f"ix_inventory_remediation_action_{column}", "inventory_remediation_action", [column])


def downgrade() -> None:
    op.drop_table("inventory_remediation_action")
    op.drop_table("inventory_anomaly_case")
