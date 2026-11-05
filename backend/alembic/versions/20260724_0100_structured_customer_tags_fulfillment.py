"""structured customer tags and fulfillment execution

Revision ID: 20260724_0100
Revises: 20260723_0100
Create Date: 2026-07-24 18:00:00
"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.customer_tag_catalog import CATALOG_VERSION_CODE, FORMAL_CUSTOMER_TAGS, LEGACY_TAG_ALIASES


revision = "20260724_0100"
down_revision = "20260723_0100"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

PERMISSIONS = (
    ("customer_tag.submit", "提交客户标签申请", "customer_tag", "submit"),
    ("customer_tag.review", "审核客户标签申请", "customer_tag", "review"),
    ("customer_tag.catalog_manage", "维护客户标签目录", "customer_tag", "catalog_manage"),
    ("customer_tag.history", "查看客户标签历史", "customer_tag", "history"),
    ("customer_tag.export", "导出客户标签", "customer_tag", "export"),
    ("sales_order.view", "查看销售订单", "sales_order", "view"),
    ("sales_order.create", "创建销售订单", "sales_order", "create"),
    ("sales_order.edit", "编辑销售订单", "sales_order", "edit"),
    ("sales_order.confirm", "确认销售订单", "sales_order", "confirm"),
    ("sales_order.import", "导入销售订单", "sales_order", "import"),
    ("delivery.view", "查看配送任务", "delivery", "view"),
    ("delivery.manage", "执行配送任务", "delivery", "manage"),
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _normal_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _create_tables() -> None:
    bind = op.get_bind()
    op.create_table(
        "customer_tag_catalog_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("description", sa.Text()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamps(),
    )
    op.create_index("ix_customer_tag_catalog_version_code", "customer_tag_catalog_version", ["version_code"])
    op.create_index("ix_customer_tag_catalog_version_status", "customer_tag_catalog_version", ["status"])

    op.add_column("customer_tag", sa.Column("stable_code", sa.String(160), nullable=True))
    op.add_column("customer_tag", sa.Column("category_key", sa.String(80), nullable=True))
    op.add_column("customer_tag", sa.Column("category_name", sa.String(120), nullable=True))
    op.add_column("customer_tag", sa.Column("group_code", sa.String(120), nullable=True))
    op.add_column("customer_tag", sa.Column("group_name", sa.String(160), nullable=True))
    op.add_column("customer_tag", sa.Column("catalog_version_id", sa.Integer(), nullable=True))
    op.add_column("customer_tag", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("customer_tag", sa.Column("selection_rule", sa.String(40), nullable=False, server_default="multi"))
    op.add_column("customer_tag", sa.Column("mutual_exclusion_key", sa.String(120), nullable=True))
    op.add_column("customer_tag", sa.Column("applicability_json", JSON, nullable=True))
    op.add_column("customer_tag", sa.Column("is_formal", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("customer_tag", sa.Column("replaced_by_tag_id", sa.Integer(), nullable=True))
    if bind.dialect.name == "postgresql":
        op.create_foreign_key("fk_customer_tag_catalog_version", "customer_tag", "customer_tag_catalog_version", ["catalog_version_id"], ["id"], ondelete="SET NULL")
        op.create_foreign_key("fk_customer_tag_replaced_by", "customer_tag", "customer_tag", ["replaced_by_tag_id"], ["id"], ondelete="SET NULL")
        op.create_unique_constraint("uq_customer_tag_stable_code", "customer_tag", ["stable_code"])
    else:
        # SQLite cannot add constraints after table creation. A unique index keeps
        # the migration rehearsal contract without changing PostgreSQL DDL.
        op.create_index("uq_customer_tag_stable_code", "customer_tag", ["stable_code"], unique=True)
    for column in ("stable_code", "category_key", "group_code", "catalog_version_id", "sort_order", "mutual_exclusion_key", "is_formal", "replaced_by_tag_id"):
        op.create_index(f"ix_customer_tag_{column}", "customer_tag", [column])

    op.create_table(
        "customer_tag_governance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settings_key", sa.String(40), nullable=False, unique=True, server_default="default"),
        sa.Column("default_reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("backup_reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("tag_workflow_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recommendation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fulfillment_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_reminder_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamps(),
    )

    op.create_table(
        "customer_tag_change_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_no", sa.String(120), nullable=False, unique=True),
        sa.Column("customer_code", sa.String(120), sa.ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False),
        sa.Column("applicant_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("backup_reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approval_instance_id", sa.Integer(), sa.ForeignKey("approval_instance.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(40), nullable=False, server_default="submitted"),
        sa.Column("reason", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in ("request_no", "customer_code", "applicant_user_id", "reviewer_user_id", "approval_instance_id", "status", "submitted_at"):
        op.create_index(f"ix_customer_tag_change_request_{column}", "customer_tag_change_request", [column])

    op.create_table(
        "customer_tag_assignment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(120), sa.ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("customer_tag.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attribute_type", sa.String(40), nullable=False, server_default="long_term"),
        sa.Column("source", sa.String(80), nullable=False, server_default="business_input"),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("review_date", sa.Date()),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(40), nullable=False, server_default="effective"),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("details_json", JSON),
        sa.Column("source_request_item_id", sa.Integer()),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("customer_code", "tag_id", "effective_date", "status", name="uq_customer_tag_assignment_version"),
        *_timestamps(),
    )
    for column in ("customer_code", "tag_id", "attribute_type", "source", "effective_date", "review_date", "status", "owner_user_id", "source_request_item_id"):
        op.create_index(f"ix_customer_tag_assignment_{column}", "customer_tag_assignment", [column])

    op.create_table(
        "customer_tag_change_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("customer_tag_change_request.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("customer_tag_assignment.id", ondelete="SET NULL")),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("customer_tag.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attribute_type", sa.String(40), nullable=False, server_default="long_term"),
        sa.Column("source", sa.String(80), nullable=False, server_default="business_input"),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("review_date", sa.Date()),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("details_json", JSON),
        sa.Column("before_json", JSON),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("review_comment", sa.Text()),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in ("request_id", "action", "assignment_id", "tag_id", "status", "reviewed_by_user_id", "reviewed_at"):
        op.create_index(f"ix_customer_tag_change_item_{column}", "customer_tag_change_item", [column])
    if bind.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_customer_tag_assignment_source_item",
            "customer_tag_assignment",
            "customer_tag_change_item",
            ["source_request_item_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_table(
        "customer_tag_rule_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_code", sa.String(120), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("parameters_json", JSON, nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.UniqueConstraint("rule_code", "version_no", name="uq_customer_tag_rule_version"),
        *_timestamps(),
    )
    for column in ("rule_code", "status", "activated_at"):
        op.create_index(f"ix_customer_tag_rule_version_{column}", "customer_tag_rule_version", [column])

    op.create_table(
        "customer_tag_recommendation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(120), sa.ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("customer_tag.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_version_id", sa.Integer(), sa.ForeignKey("customer_tag_rule_version.id", ondelete="SET NULL")),
        sa.Column("statistics_start", sa.Date()),
        sa.Column("statistics_end", sa.Date()),
        sa.Column("metrics_json", JSON, nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("manual_result", sa.String(120)),
        sa.Column("manual_note", sa.Text()),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    for column in ("customer_code", "tag_id", "rule_version_id", "statistics_start", "statistics_end", "status"):
        op.create_index(f"ix_customer_tag_recommendation_{column}", "customer_tag_recommendation", [column])

    op.create_table(
        "customer_tag_legacy_mapping",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(120), sa.ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False),
        sa.Column("legacy_tag_name", sa.String(120), nullable=False),
        sa.Column("target_tag_id", sa.Integer(), sa.ForeignKey("customer_tag.id", ondelete="SET NULL")),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("rationale", sa.Text()),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("customer_code", "legacy_tag_name", name="uq_customer_tag_legacy_mapping"),
        *_timestamps(),
    )
    for column in ("customer_code", "legacy_tag_name", "target_tag_id", "status"):
        op.create_index(f"ix_customer_tag_legacy_mapping_{column}", "customer_tag_legacy_mapping", [column])

    op.create_table(
        "sales_order",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_no", sa.String(120), nullable=False, unique=True),
        sa.Column("external_order_no", sa.String(160), unique=True),
        sa.Column("customer_code", sa.String(120), sa.ForeignKey("customer_master.customer_code", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(255), nullable=False),
        sa.Column("source", sa.String(40), nullable=False, server_default="web"),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("planned_delivery_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_address", sa.Text()),
        sa.Column("temporary_requirements_json", JSON),
        sa.Column("requirement_snapshot_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamps(),
    )
    for column in ("order_no", "external_order_no", "customer_code", "source", "status", "planned_delivery_at"):
        op.create_index(f"ix_sales_order_{column}", "sales_order", [column])

    op.create_table(
        "sales_order_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("sales_order.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_code", sa.String(120), sa.ForeignKey("product_master.product_code", ondelete="SET NULL")),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(80)),
        sa.Column("remark", sa.Text()),
        sa.UniqueConstraint("order_id", "line_no", name="uq_sales_order_line_no"),
        *_timestamps(),
    )
    for column in ("order_id", "product_code", "product_name"):
        op.create_index(f"ix_sales_order_line_{column}", "sales_order_line", [column])

    op.create_table(
        "sales_order_requirement_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("sales_order.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("customer_tag.id", ondelete="SET NULL")),
        sa.Column("tag_code", sa.String(160)),
        sa.Column("tag_name", sa.String(120), nullable=False),
        sa.Column("group_code", sa.String(120)),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("requirement_json", JSON),
        sa.Column("source_assignment_id", sa.Integer(), sa.ForeignKey("customer_tag_assignment.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("order_id", "snapshot_version", "tag_id", "source_type", name="uq_order_requirement_snapshot"),
    )
    for column in ("order_id", "snapshot_version", "tag_id", "tag_code", "group_code", "source_type", "source_assignment_id"):
        op.create_index(f"ix_sales_order_requirement_snapshot_{column}", "sales_order_requirement_snapshot", [column])

    op.create_table(
        "delivery_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_no", sa.String(120), nullable=False, unique=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("sales_order.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("planned_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_address", sa.Text()),
        sa.Column("requirements_json", JSON),
        sa.Column("assignee_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("signed_by", sa.String(120)),
        sa.Column("signed_at", sa.DateTime(timezone=True)),
        sa.Column("exception_note", sa.Text()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamps(),
    )
    for column in ("delivery_no", "order_id", "status", "planned_at", "assignee_user_id"):
        op.create_index(f"ix_delivery_task_{column}", "delivery_task", [column])

    op.create_table(
        "delivery_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_id", sa.Integer(), sa.ForeignKey("delivery_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("from_status", sa.String(40)),
        sa.Column("to_status", sa.String(40)),
        sa.Column("note", sa.Text()),
        sa.Column("payload_json", JSON),
        sa.Column("operator_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("delivery_id", "event_type", "to_status", "operator_user_id", "created_at"):
        op.create_index(f"ix_delivery_event_{column}", "delivery_event", [column])

    op.create_table(
        "delivery_attachment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_id", sa.Integer(), sa.ForeignKey("delivery_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("delivery_id", "created_by_user_id", "created_at"):
        op.create_index(f"ix_delivery_attachment_{column}", "delivery_attachment", [column])


def _seed_catalog() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    if bind.dialect.name != "postgresql":
        version_table = sa.table(
            "customer_tag_catalog_version",
            sa.column("id", sa.Integer()),
            sa.column("version_code", sa.String()),
            sa.column("name", sa.String()),
            sa.column("status", sa.String()),
            sa.column("description", sa.Text()),
            sa.column("activated_at", sa.DateTime(timezone=True)),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        version_id = bind.execute(
            sa.select(version_table.c.id).where(version_table.c.version_code == CATALOG_VERSION_CODE)
        ).scalar_one_or_none()
        if version_id is None:
            bind.execute(
                version_table.insert().values(
                    version_code=CATALOG_VERSION_CODE,
                    name="管理中心客户标签正式目录 2026.07",
                    status="active",
                    description="确认稿四大类、15 个分组、152 个正式标签",
                    activated_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            version_id = bind.execute(
                sa.select(version_table.c.id).where(version_table.c.version_code == CATALOG_VERSION_CODE)
            ).scalar_one()
        tag_table = sa.table(
            "customer_tag",
            sa.column("id", sa.Integer()),
            sa.column("name", sa.String()),
            sa.column("normalized_name", sa.String()),
            sa.column("color_key", sa.String()),
            sa.column("is_active", sa.Boolean()),
            sa.column("stable_code", sa.String()),
            sa.column("category_key", sa.String()),
            sa.column("category_name", sa.String()),
            sa.column("group_code", sa.String()),
            sa.column("group_name", sa.String()),
            sa.column("catalog_version_id", sa.Integer()),
            sa.column("sort_order", sa.Integer()),
            sa.column("selection_rule", sa.String()),
            sa.column("mutual_exclusion_key", sa.String()),
            sa.column("applicability_json", sa.JSON()),
            sa.column("is_formal", sa.Boolean()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        for row in FORMAL_CUSTOMER_TAGS:
            values = {
                **{key: value for key, value in row.items() if key != "applicability"},
                "normalized_name": _normal_name(str(row["name"])),
                "catalog_version_id": version_id,
                "applicability_json": row["applicability"],
                "is_active": True,
                "is_formal": True,
                "updated_at": now,
            }
            tag_id = bind.execute(
                sa.select(tag_table.c.id).where(tag_table.c.normalized_name == values["normalized_name"])
            ).scalar_one_or_none()
            if tag_id is None:
                bind.execute(tag_table.insert().values(**values, created_at=now))
            else:
                bind.execute(tag_table.update().where(tag_table.c.id == tag_id).values(**values))
        settings_table = sa.table(
            "customer_tag_governance_settings",
            sa.column("id", sa.Integer()),
            sa.column("settings_key", sa.String()),
            sa.column("tag_workflow_enabled", sa.Boolean()),
            sa.column("recommendation_enabled", sa.Boolean()),
            sa.column("fulfillment_enabled", sa.Boolean()),
            sa.column("review_reminder_days", sa.Integer()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        if bind.execute(
            sa.select(settings_table.c.id).where(settings_table.c.settings_key == "default")
        ).scalar_one_or_none() is None:
            bind.execute(
                settings_table.insert().values(
                    settings_key="default",
                    tag_workflow_enabled=False,
                    recommendation_enabled=False,
                    fulfillment_enabled=False,
                    review_reminder_days=7,
                    created_at=now,
                    updated_at=now,
                )
            )
        return
    version_id = bind.execute(
        sa.text(
            """
            INSERT INTO customer_tag_catalog_version
                (version_code, name, status, description, activated_at, created_at, updated_at)
            VALUES (:code, :name, 'active', :description, :now, :now, :now)
            ON CONFLICT (version_code) DO UPDATE SET
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                description = EXCLUDED.description,
                activated_at = COALESCE(customer_tag_catalog_version.activated_at, EXCLUDED.activated_at),
                updated_at = EXCLUDED.updated_at
            RETURNING id
            """
        ),
        {"code": CATALOG_VERSION_CODE, "name": "管理中心客户标签正式目录 2026.07", "description": "确认稿四大类、15 个分组、152 个正式标签", "now": now},
    ).scalar_one()
    for row in FORMAL_CUSTOMER_TAGS:
        params = {
            **row,
            "normalized_name": _normal_name(str(row["name"])),
            "catalog_version_id": version_id,
            "applicability_json": json.dumps(row["applicability"], ensure_ascii=False),
            "now": now,
        }
        bind.execute(
            sa.text(
                """
                INSERT INTO customer_tag
                    (name, normalized_name, color_key, is_active, stable_code, category_key, category_name,
                     group_code, group_name, catalog_version_id, sort_order, selection_rule,
                     mutual_exclusion_key, applicability_json, is_formal, created_at, updated_at)
                VALUES
                    (:name, :normalized_name, :color_key, true, :stable_code, :category_key, :category_name,
                     :group_code, :group_name, :catalog_version_id, :sort_order, :selection_rule,
                     :mutual_exclusion_key, CAST(:applicability_json AS jsonb), true, :now, :now)
                ON CONFLICT (normalized_name) DO UPDATE SET
                    stable_code = EXCLUDED.stable_code,
                    category_key = EXCLUDED.category_key,
                    category_name = EXCLUDED.category_name,
                    group_code = EXCLUDED.group_code,
                    group_name = EXCLUDED.group_name,
                    catalog_version_id = EXCLUDED.catalog_version_id,
                    sort_order = EXCLUDED.sort_order,
                    selection_rule = EXCLUDED.selection_rule,
                    mutual_exclusion_key = EXCLUDED.mutual_exclusion_key,
                    applicability_json = EXCLUDED.applicability_json,
                    color_key = EXCLUDED.color_key,
                    is_formal = true,
                    is_active = true,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            params,
        )
    bind.execute(
        sa.text(
            """
            INSERT INTO customer_tag_governance_settings
                (settings_key, tag_workflow_enabled, recommendation_enabled, fulfillment_enabled,
                 review_reminder_days, created_at, updated_at)
            VALUES ('default', false, false, false, 7, :now, :now)
            ON CONFLICT (settings_key) DO NOTHING
            """
        ),
        {"now": now},
    )


def _seed_permissions() -> None:
    bind = op.get_bind()
    table_names = set(sa.inspect(bind).get_table_names())
    if not {"permissions", "roles", "role_permissions"}.issubset(table_names):
        return
    if bind.dialect.name != "postgresql":
        permissions = sa.table(
            "permissions",
            sa.column("id", sa.Integer()),
            sa.column("permission_code", sa.String()),
            sa.column("permission_name", sa.String()),
            sa.column("resource_type", sa.String()),
            sa.column("action_type", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        roles = sa.table("roles", sa.column("id", sa.Integer()), sa.column("role_code", sa.String()))
        role_permissions = sa.table(
            "role_permissions", sa.column("role_id", sa.Integer()), sa.column("permission_id", sa.Integer())
        )
        admin_role_id = bind.execute(sa.select(roles.c.id).where(roles.c.role_code == "admin")).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        for code, name, resource_type, action_type in PERMISSIONS:
            permission_id = bind.execute(
                sa.select(permissions.c.id).where(permissions.c.permission_code == code)
            ).scalar_one_or_none()
            if permission_id is None:
                bind.execute(
                    permissions.insert().values(
                        permission_code=code,
                        permission_name=name,
                        resource_type=resource_type,
                        action_type=action_type,
                        created_at=now,
                        updated_at=now,
                    )
                )
                permission_id = bind.execute(
                    sa.select(permissions.c.id).where(permissions.c.permission_code == code)
                ).scalar_one()
            if admin_role_id is not None and bind.execute(
                sa.select(role_permissions.c.permission_id).where(
                    role_permissions.c.role_id == admin_role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).scalar_one_or_none() is None:
                bind.execute(role_permissions.insert().values(role_id=admin_role_id, permission_id=permission_id))
        return
    for code, name, resource_type, action_type in PERMISSIONS:
        bind.execute(
            sa.text(
                """
                INSERT INTO permissions
                    (permission_code, permission_name, resource_type, action_type, created_at, updated_at)
                VALUES (:code, :name, :resource_type, :action_type, now(), now())
                ON CONFLICT (permission_code) DO NOTHING
                """
            ),
            {"code": code, "name": name, "resource_type": resource_type, "action_type": action_type},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT roles.id, permissions.id
                FROM roles, permissions
                WHERE roles.role_code = 'admin' AND permissions.permission_code = :code
                ON CONFLICT (role_id, permission_id) DO NOTHING
                """
            ),
            {"code": code},
        )


def _seed_legacy_mapping_candidates() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    aliases = {name: values for name, values in LEGACY_TAG_ALIASES.items()}
    bind.execute(
        sa.text(
            """
            INSERT INTO customer_tag_legacy_mapping
                (customer_code, legacy_tag_name, target_tag_id, confidence, rationale, status, created_at, updated_at)
            SELECT customer_master.customer_code, tags.tag_value, customer_tag.id, 1.0,
                   '旧标签名称与正式目录精确匹配，仍需人工复核', 'pending', now(), now()
            FROM customer_master
            CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(customer_master.customer_tags, '[]'::jsonb)) tags(tag_value)
            JOIN customer_tag ON customer_tag.normalized_name = lower(btrim(tags.tag_value)) AND customer_tag.is_formal = true
            ON CONFLICT (customer_code, legacy_tag_name) DO NOTHING
            """
        )
    )
    for legacy_name, (target_code, confidence, rationale) in aliases.items():
        bind.execute(
            sa.text(
                """
                INSERT INTO customer_tag_legacy_mapping
                    (customer_code, legacy_tag_name, target_tag_id, confidence, rationale, status, created_at, updated_at)
                SELECT customer_master.customer_code, :legacy_name, customer_tag.id, :confidence, :rationale,
                       'pending', now(), now()
                FROM customer_master
                JOIN customer_tag ON customer_tag.stable_code = :target_code
                WHERE COALESCE(customer_master.customer_tags, '[]'::jsonb) @> jsonb_build_array(CAST(:legacy_name_json AS text))
                ON CONFLICT (customer_code, legacy_tag_name) DO NOTHING
                """
            ),
            {
                "legacy_name": legacy_name,
                "legacy_name_json": legacy_name,
                "target_code": target_code,
                "confidence": confidence,
                "rationale": rationale,
            },
        )
    bind.execute(
        sa.text(
            """
            INSERT INTO customer_tag_legacy_mapping
                (customer_code, legacy_tag_name, target_tag_id, confidence, rationale, status, created_at, updated_at)
            SELECT customer_master.customer_code, tags.tag_value, NULL, NULL,
                   '未找到正式目录精确名称或已配置别名', 'unmatched', now(), now()
            FROM customer_master
            CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(customer_master.customer_tags, '[]'::jsonb)) tags(tag_value)
            LEFT JOIN customer_tag ON customer_tag.normalized_name = lower(btrim(tags.tag_value)) AND customer_tag.is_formal = true
            WHERE customer_tag.id IS NULL
            ON CONFLICT (customer_code, legacy_tag_name) DO NOTHING
            """
        )
    )


def upgrade() -> None:
    _create_tables()
    _seed_catalog()
    _seed_permissions()
    _seed_legacy_mapping_candidates()


def downgrade() -> None:
    bind = op.get_bind()
    codes = [item[0] for item in PERMISSIONS]
    table_names = set(sa.inspect(bind).get_table_names())
    if {"permissions", "role_permissions"}.issubset(table_names):
        permissions = sa.table("permissions", sa.column("id", sa.Integer()), sa.column("permission_code", sa.String()))
        role_permissions = sa.table("role_permissions", sa.column("permission_id", sa.Integer()))
        permission_ids = sa.select(permissions.c.id).where(permissions.c.permission_code.in_(codes))
        bind.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(permission_ids)))
        bind.execute(permissions.delete().where(permissions.c.permission_code.in_(codes)))
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "fk_customer_tag_assignment_source_item",
            "customer_tag_assignment",
            type_="foreignkey",
        )
    for table in (
        "delivery_attachment", "delivery_event", "delivery_task", "sales_order_requirement_snapshot",
        "sales_order_line", "sales_order", "customer_tag_legacy_mapping", "customer_tag_recommendation",
        "customer_tag_rule_version", "customer_tag_change_item", "customer_tag_assignment",
        "customer_tag_change_request", "customer_tag_governance_settings",
    ):
        op.drop_table(table)
    for column in ("replaced_by_tag_id", "is_formal", "mutual_exclusion_key", "sort_order", "catalog_version_id", "group_code", "category_key", "stable_code"):
        op.drop_index(f"ix_customer_tag_{column}", table_name="customer_tag")
    if bind.dialect.name == "postgresql":
        op.drop_constraint("uq_customer_tag_stable_code", "customer_tag", type_="unique")
        op.drop_constraint("fk_customer_tag_replaced_by", "customer_tag", type_="foreignkey")
        op.drop_constraint("fk_customer_tag_catalog_version", "customer_tag", type_="foreignkey")
    else:
        op.drop_index("uq_customer_tag_stable_code", table_name="customer_tag")
    for column in (
        "replaced_by_tag_id", "is_formal", "applicability_json", "mutual_exclusion_key", "selection_rule",
        "sort_order", "catalog_version_id", "group_name", "group_code", "category_name", "category_key", "stable_code",
    ):
        op.drop_column("customer_tag", column)
    op.drop_table("customer_tag_catalog_version")
