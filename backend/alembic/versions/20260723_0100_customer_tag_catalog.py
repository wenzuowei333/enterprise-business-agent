"""company-wide customer tag catalog

Revision ID: 20260723_0100
Revises: 20260722_0100
Create Date: 2026-07-23 23:55:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0100"
down_revision = "20260722_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("normalized_name", sa.String(length=60), nullable=False),
        sa.Column("color_key", sa.String(length=20), nullable=False, server_default="blue"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "color_key IN ('blue', 'green', 'cyan', 'yellow', 'red', 'purple', 'pink', 'gray')",
            name="ck_customer_tag_color_key",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_customer_tag_normalized_name"),
    )
    op.create_index("ix_customer_tag_name", "customer_tag", ["name"])
    op.create_index("ix_customer_tag_color_key", "customer_tag", ["color_key"])
    op.create_index("ix_customer_tag_is_active", "customer_tag", ["is_active"])
    op.create_index("ix_customer_tag_created_by_user_id", "customer_tag", ["created_by_user_id"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and "customer_master" in sa.inspect(bind).get_table_names():
        op.execute(
            sa.text(
                """
                INSERT INTO customer_tag (name, normalized_name, color_key, is_active)
                SELECT DISTINCT ON (lower(left(btrim(tag_value), 30)))
                       left(btrim(tag_value), 30),
                       lower(left(btrim(tag_value), 30)),
                       'blue',
                       true
                FROM customer_master
                CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(customer_tags, '[]'::jsonb)) AS tags(tag_value)
                WHERE btrim(tag_value) <> ''
                ORDER BY lower(left(btrim(tag_value), 30)), customer_master.id
                ON CONFLICT (normalized_name) DO NOTHING
                """
            )
        )


def downgrade() -> None:
    op.drop_index("ix_customer_tag_created_by_user_id", table_name="customer_tag")
    op.drop_index("ix_customer_tag_is_active", table_name="customer_tag")
    op.drop_index("ix_customer_tag_color_key", table_name="customer_tag")
    op.drop_index("ix_customer_tag_name", table_name="customer_tag")
    op.drop_table("customer_tag")
