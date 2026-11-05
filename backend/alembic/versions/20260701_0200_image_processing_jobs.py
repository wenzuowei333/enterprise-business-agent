"""image processing jobs

Revision ID: 20260701_0200
Revises: 20260701_0001
Create Date: 2026-07-01 02:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260701_0200"
down_revision = "20260701_0001"
branch_labels = None
depends_on = None


def created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


IMAGE_PERMISSIONS = [
    ("crm_image.view", "查看图片处理", "crm_image", "view"),
    ("crm_image.process", "处理图片任务", "crm_image", "process"),
    ("crm_image.download", "下载图片结果", "crm_image", "download"),
]

ROLE_GRANTS = {
    "boss": ["crm_image.view", "crm_image.process", "crm_image.download"],
    "business_middle_office": ["crm_image.view", "crm_image.process", "crm_image.download"],
    "data_middle_office": ["crm_image.view", "crm_image.process", "crm_image.download"],
    "salesperson": ["crm_image.view", "crm_image.process", "crm_image.download"],
    "viewer": ["crm_image.view"],
}


def upgrade() -> None:
    op.create_table(
        "image_processing_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_no", sa.String(length=120), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_by_username", sa.String(length=80)),
        sa.Column("template_type", sa.String(length=40), nullable=False, server_default="main"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="queued"),
        sa.Column("input_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("options_json", postgresql.JSONB()),
        sa.Column("result_json", postgresql.JSONB()),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_image_processing_jobs_job_no", "image_processing_jobs", ["job_no"], unique=True)
    op.create_index("ix_image_processing_jobs_created_by", "image_processing_jobs", ["created_by_user_id", "created_at"])
    op.create_index("ix_image_processing_jobs_created_by_username", "image_processing_jobs", ["created_by_username"])
    op.create_index("ix_image_processing_jobs_template", "image_processing_jobs", ["template_type"])
    op.create_index("ix_image_processing_jobs_status", "image_processing_jobs", ["status", "created_at"])
    op.create_index("ix_image_processing_jobs_started_at", "image_processing_jobs", ["started_at"])
    op.create_index("ix_image_processing_jobs_finished_at", "image_processing_jobs", ["finished_at"])

    op.create_table(
        "image_processing_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("image_processing_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("input_path", sa.String(length=800)),
        sa.Column("output_path", sa.String(length=800)),
        sa.Column("output_filename", sa.String(length=255)),
        sa.Column("content_type", sa.String(length=120)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text()),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_image_processing_files_job", "image_processing_files", ["job_id", "status", "sort_order"])
    op.create_index("ix_image_processing_files_status", "image_processing_files", ["status"])
    op.create_index("ix_image_processing_files_created_at", "image_processing_files", ["created_at"])

    for code, name, resource_type, action_type in IMAGE_PERMISSIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO permissions (permission_code, permission_name, resource_type, action_type, created_at, updated_at)
                VALUES (:code, :name, :resource_type, :action_type, now(), now())
                ON CONFLICT (permission_code) DO NOTHING
                """
            ).bindparams(code=code, name=name, resource_type=resource_type, action_type=action_type)
        )

    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id, created_at)
        SELECT r.id, p.id, now()
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.role_code = 'admin'
          AND p.resource_type = 'crm_image'
        ON CONFLICT ON CONSTRAINT uq_role_permissions_role_permission DO NOTHING
        """
    )
    for role_code, permission_codes in ROLE_GRANTS.items():
        quoted_codes = ", ".join(f"'{code}'" for code in permission_codes)
        op.execute(
            f"""
            INSERT INTO role_permissions (role_id, permission_id, created_at)
            SELECT r.id, p.id, now()
            FROM roles r
            JOIN permissions p ON p.permission_code IN ({quoted_codes})
            WHERE r.role_code = '{role_code}'
            ON CONFLICT ON CONSTRAINT uq_role_permissions_role_permission DO NOTHING
            """
        )

    for role_code, scope_mode in [
        ("admin", "all"),
        ("boss", "all"),
        ("business_middle_office", "all"),
        ("data_middle_office", "all"),
        ("salesperson", "own"),
        ("viewer", "own"),
    ]:
        op.execute(
            sa.text(
                """
                INSERT INTO data_scope_rules
                  (subject_type, subject_id, resource_type, scope_mode, scope_value, is_active, created_at, updated_at)
                VALUES ('role', :role_code, 'crm_image', :scope_mode, NULL, true, now(), now())
                ON CONFLICT DO NOTHING
                """
            ).bindparams(role_code=role_code, scope_mode=scope_mode)
        )


def downgrade() -> None:
    op.execute("DELETE FROM data_scope_rules WHERE resource_type = 'crm_image'")
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (SELECT id FROM permissions WHERE resource_type = 'crm_image')
        """
    )
    op.execute("DELETE FROM permissions WHERE resource_type = 'crm_image'")
    op.drop_table("image_processing_files")
    op.drop_table("image_processing_jobs")
