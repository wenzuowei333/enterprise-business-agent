"""master link issues

Revision ID: 20260706_0100
Revises: 20260705_0550
Create Date: 2026-07-06 01:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260706_0100"
down_revision = "20260705_0550"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "master_link_issue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source_file_type", sa.String(length=80), nullable=False),
        sa.Column("issue_type", sa.String(length=80), nullable=False),
        sa.Column("expected_master_kind", sa.String(length=40), nullable=False),
        sa.Column("reference_code", sa.String(length=120), nullable=True),
        sa.Column("reference_name", sa.String(length=255), nullable=True),
        sa.Column("counterpart_master_kind", sa.String(length=40), nullable=True),
        sa.Column("counterpart_code", sa.String(length=120), nullable=True),
        sa.Column("counterpart_name", sa.String(length=255), nullable=True),
        sa.Column("first_seen_date", sa.Date(), nullable=True),
        sa.Column("last_seen_date", sa.Date(), nullable=True),
        sa.Column("affected_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affected_documents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("amount_total", sa.Numeric(18, 2), nullable=True),
        sa.Column("quantity_total", sa.Numeric(18, 4), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("resolution_type", sa.String(length=80), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("source_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "batch_id",
            "source_file_type",
            "issue_type",
            "reference_code",
            "reference_name",
            name="uq_master_link_issue_batch_reference",
        ),
    )
    for column in [
        "batch_id",
        "source_file_type",
        "issue_type",
        "expected_master_kind",
        "reference_code",
        "reference_name",
        "counterpart_master_kind",
        "counterpart_code",
        "first_seen_date",
        "last_seen_date",
        "status",
        "resolution_type",
        "resolved_by_user_id",
    ]:
        op.create_index(f"ix_master_link_issue_{column}", "master_link_issue", [column])


def downgrade() -> None:
    op.drop_table("master_link_issue")
