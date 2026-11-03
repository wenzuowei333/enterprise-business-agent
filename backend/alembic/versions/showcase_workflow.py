"""New showcase session and per-job Mock scenario; original 18-table baseline intact."""
from alembic import op
import sqlalchemy as sa

revision = "showcase_workflow"
down_revision = "showcase_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("exception_diagnosis_job", sa.Column("demo_scenario", sa.String(40), server_default="success", nullable=False))
    op.create_table("demo_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_token", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_demo_session_user_id", "demo_session", ["user_id"])
    op.create_index("ix_demo_session_expires_at", "demo_session", ["expires_at"])


def downgrade():
    op.drop_table("demo_session")
    op.drop_column("exception_diagnosis_job", "demo_scenario")
