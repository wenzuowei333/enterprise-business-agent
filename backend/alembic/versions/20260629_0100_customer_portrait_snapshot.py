"""customer portrait snapshot tables

Revision ID: 20260629_0100
Revises: 20260628_0100
Create Date: 2026-06-29 18:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260629_0100"
down_revision = "20260628_0100"
branch_labels = None
depends_on = None


def created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "customer_portrait_rule_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_code", sa.String(length=120), nullable=False),
        sa.Column("version_name", sa.String(length=160), nullable=False),
        sa.Column("rule_json", postgresql.JSONB()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        created_at_column(),
    )
    op.create_index("ix_customer_portrait_rule_version_version_code", "customer_portrait_rule_version", ["version_code"], unique=True)
    op.create_index("ix_customer_portrait_rule_version_is_active", "customer_portrait_rule_version", ["is_active"])
    op.create_index("ix_customer_portrait_rule_version_created_by", "customer_portrait_rule_version", ["created_by"])

    op.create_table(
        "customer_portrait_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_no", sa.String(length=120), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("customer_code", sa.String(length=120)),
        sa.Column("total_customers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_json", postgresql.JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        created_at_column(),
    )
    op.create_index("ix_customer_portrait_task_task_no", "customer_portrait_task", ["task_no"], unique=True)
    op.create_index("ix_customer_portrait_task_task_type", "customer_portrait_task", ["task_type"])
    op.create_index("ix_customer_portrait_task_status", "customer_portrait_task", ["status"])
    op.create_index("ix_customer_portrait_task_customer_code", "customer_portrait_task", ["customer_code"])
    op.create_index("ix_customer_portrait_task_created_by", "customer_portrait_task", ["created_by"])

    op.create_table(
        "customer_portrait_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=120), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("data_cutoff_date", sa.Date()),
        sa.Column("rule_version", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="generated"),
        sa.Column("task_no", sa.String(length=120)),
        sa.Column("summary_json", postgresql.JSONB()),
        sa.Column("tag_json", postgresql.JSONB()),
        sa.Column("payment_json", postgresql.JSONB()),
        sa.Column("profile_json", postgresql.JSONB()),
        sa.Column("quality_json", postgresql.JSONB()),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_customer_portrait_snapshot_customer_code", "customer_portrait_snapshot", ["customer_code"])
    op.create_index("ix_customer_portrait_snapshot_customer_name", "customer_portrait_snapshot", ["customer_name"])
    op.create_index("ix_customer_portrait_snapshot_data_cutoff_date", "customer_portrait_snapshot", ["data_cutoff_date"])
    op.create_index("ix_customer_portrait_snapshot_rule_version", "customer_portrait_snapshot", ["rule_version"])
    op.create_index("ix_customer_portrait_snapshot_status", "customer_portrait_snapshot", ["status"])
    op.create_index("ix_customer_portrait_snapshot_task_no", "customer_portrait_snapshot", ["task_no"])
    op.create_index("ix_customer_portrait_snapshot_generated_at", "customer_portrait_snapshot", ["generated_at"])

    op.execute(
        """
        INSERT INTO customer_portrait_rule_version (version_code, version_name, rule_json, is_active)
        VALUES (
            'portrait-tag-v0.1',
            '客户画像规则 v0.1',
            '{"tags":"12维标签画像","payment":"6+1回款风险","profile":"9段深度画像","mode":"rule_template"}'::jsonb,
            true
        )
        ON CONFLICT (version_code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_customer_portrait_snapshot_generated_at", table_name="customer_portrait_snapshot")
    op.drop_index("ix_customer_portrait_snapshot_task_no", table_name="customer_portrait_snapshot")
    op.drop_index("ix_customer_portrait_snapshot_status", table_name="customer_portrait_snapshot")
    op.drop_index("ix_customer_portrait_snapshot_rule_version", table_name="customer_portrait_snapshot")
    op.drop_index("ix_customer_portrait_snapshot_data_cutoff_date", table_name="customer_portrait_snapshot")
    op.drop_index("ix_customer_portrait_snapshot_customer_name", table_name="customer_portrait_snapshot")
    op.drop_index("ix_customer_portrait_snapshot_customer_code", table_name="customer_portrait_snapshot")
    op.drop_table("customer_portrait_snapshot")

    op.drop_index("ix_customer_portrait_task_created_by", table_name="customer_portrait_task")
    op.drop_index("ix_customer_portrait_task_customer_code", table_name="customer_portrait_task")
    op.drop_index("ix_customer_portrait_task_status", table_name="customer_portrait_task")
    op.drop_index("ix_customer_portrait_task_task_type", table_name="customer_portrait_task")
    op.drop_index("ix_customer_portrait_task_task_no", table_name="customer_portrait_task")
    op.drop_table("customer_portrait_task")

    op.drop_index("ix_customer_portrait_rule_version_created_by", table_name="customer_portrait_rule_version")
    op.drop_index("ix_customer_portrait_rule_version_is_active", table_name="customer_portrait_rule_version")
    op.drop_index("ix_customer_portrait_rule_version_version_code", table_name="customer_portrait_rule_version")
    op.drop_table("customer_portrait_rule_version")
