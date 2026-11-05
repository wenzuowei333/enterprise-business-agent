"""store import content hashes for duplicate detection

Revision ID: 20260728_0300
Revises: 20260728_0200
Create Date: 2026-07-28 18:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260728_0300"
down_revision = "20260728_0200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("import_batch"):
        return
    if "content_sha256" not in {column["name"] for column in inspector.get_columns("import_batch")}:
        op.add_column("import_batch", sa.Column("content_sha256", sa.String(64), nullable=True))
    inspector = sa.inspect(op.get_bind())
    if "ix_import_batch_content_sha256" not in {index["name"] for index in inspector.get_indexes("import_batch")}:
        op.create_index("ix_import_batch_content_sha256", "import_batch", ["content_sha256"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("import_batch"):
        return
    if "ix_import_batch_content_sha256" in {index["name"] for index in inspector.get_indexes("import_batch")}:
        op.drop_index("ix_import_batch_content_sha256", table_name="import_batch")
    inspector = sa.inspect(op.get_bind())
    if "content_sha256" in {column["name"] for column in inspector.get_columns("import_batch")}:
        op.drop_column("import_batch", "content_sha256")
