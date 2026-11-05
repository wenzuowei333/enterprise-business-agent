"""master category persistence

Revision ID: 20260701_0500
Revises: 20260701_0400
Create Date: 2026-07-01 05:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260701_0500"
down_revision = "20260701_0400"
branch_labels = None
depends_on = None


def created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "master_category_node",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("node_code", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("master_category_node.id", ondelete="CASCADE")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("remark", sa.Text()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        created_at_column(),
        updated_at_column(),
        sa.UniqueConstraint("node_code", name="uq_master_category_node_code"),
        sa.UniqueConstraint("kind", "parent_id", "label", name="uq_master_category_node_kind_parent_label"),
    )
    op.create_index("ix_master_category_node_node_code", "master_category_node", ["node_code"], unique=True)
    op.create_index("ix_master_category_node_kind", "master_category_node", ["kind"])
    op.create_index("ix_master_category_node_label", "master_category_node", ["label"])
    op.create_index("ix_master_category_node_parent_id", "master_category_node", ["parent_id"])
    op.create_index("ix_master_category_node_sort_order", "master_category_node", ["sort_order"])
    op.create_index("ix_master_category_node_is_enabled", "master_category_node", ["is_enabled"])
    op.create_index("ix_master_category_node_created_by_user_id", "master_category_node", ["created_by_user_id"])
    op.create_index("ix_master_category_node_updated_by_user_id", "master_category_node", ["updated_by_user_id"])

    op.create_table(
        "master_category_binding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("master_category_node.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_code", sa.String(length=120), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=120)),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        created_at_column(),
        updated_at_column(),
        sa.UniqueConstraint("category_id", "resource_type", "resource_code", name="uq_master_category_binding_category_resource"),
    )
    op.create_index("ix_master_category_binding_category_id", "master_category_binding", ["category_id"])
    op.create_index("ix_master_category_binding_resource_type", "master_category_binding", ["resource_type"])
    op.create_index("ix_master_category_binding_resource_code", "master_category_binding", ["resource_code"])
    op.create_index("ix_master_category_binding_is_primary", "master_category_binding", ["is_primary"])
    op.create_index("ix_master_category_binding_sort_order", "master_category_binding", ["sort_order"])
    op.create_index("ix_master_category_binding_source", "master_category_binding", ["source"])
    op.create_index("ix_master_category_binding_created_by_user_id", "master_category_binding", ["created_by_user_id"])


def downgrade() -> None:
    op.drop_table("master_category_binding")
    op.drop_table("master_category_node")
