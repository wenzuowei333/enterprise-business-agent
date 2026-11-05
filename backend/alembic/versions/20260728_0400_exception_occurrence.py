"""classify exception occurrence and store diagnosis feedback

Revision ID: 20260728_0400
Revises: 20260728_0300
Create Date: 2026-07-28 20:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260728_0400"
down_revision = "20260728_0300"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def _check_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_check_constraints(table) if constraint.get("name")}


def _unique_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_unique_constraints(table) if constraint.get("name")}


def _batch_options(bind: sa.Connection) -> dict[str, object]:
    # Legacy SQLite migration fixtures intentionally contain only the tables
    # needed by the migration under test. Avoid recursively reflecting foreign
    # key targets that are unrelated to this revision.
    if bind.dialect.name == "sqlite":
        return {"reflect_kwargs": {"resolve_fks": False}}
    return {}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("exception_case"):
        columns = _column_names(inspector, "exception_case")
        if "occurrence_type" not in columns:
            op.add_column(
                "exception_case",
                sa.Column("occurrence_type", sa.String(40), nullable=False, server_default="baseline"),
            )
        if "rule_version" not in columns:
            op.add_column(
                "exception_case",
                sa.Column("rule_version", sa.String(80), nullable=False, server_default="legacy-v1"),
            )
        if "occurrence_cycle" not in columns:
            op.add_column(
                "exception_case",
                sa.Column("occurrence_cycle", sa.Integer(), nullable=False, server_default="0"),
            )
        op.execute(sa.text("UPDATE exception_case SET occurrence_type = 'baseline' WHERE occurrence_type IS NULL"))
        op.execute(sa.text("UPDATE exception_case SET rule_version = 'legacy-v1' WHERE rule_version IS NULL OR rule_version = ''"))
        op.execute(sa.text("UPDATE exception_case SET occurrence_cycle = 0 WHERE occurrence_cycle IS NULL"))

        inspector = sa.inspect(bind)
        indexes = _index_names(inspector, "exception_case")
        if "ix_exception_case_occurrence_type" not in indexes:
            op.create_index("ix_exception_case_occurrence_type", "exception_case", ["occurrence_type"])
        if "ix_exception_case_rule_version" not in indexes:
            op.create_index("ix_exception_case_rule_version", "exception_case", ["rule_version"])
        if "ix_exception_case_occurrence_cycle" not in indexes:
            op.create_index("ix_exception_case_occurrence_cycle", "exception_case", ["occurrence_cycle"])
        inspector = sa.inspect(bind)
        if "ck_exception_case_occurrence_type" not in _check_names(inspector, "exception_case"):
            with op.batch_alter_table("exception_case", **_batch_options(bind)) as batch_op:
                batch_op.create_check_constraint(
                    "ck_exception_case_occurrence_type",
                    "occurrence_type IN ('baseline','new','reopened')",
                )

    inspector = sa.inspect(bind)
    if inspector.has_table("exception_notification"):
        columns = _column_names(inspector, "exception_notification")
        if "occurrence_cycle" not in columns:
            op.add_column(
                "exception_notification",
                sa.Column("occurrence_cycle", sa.Integer(), nullable=False, server_default="0"),
            )
        if "archived_at" not in columns:
            op.add_column("exception_notification", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        if "archive_reason" not in columns:
            op.add_column("exception_notification", sa.Column("archive_reason", sa.String(160), nullable=True))
        op.execute(sa.text("UPDATE exception_notification SET occurrence_cycle = 0 WHERE occurrence_cycle IS NULL"))
        inspector = sa.inspect(bind)
        unique_names = _unique_names(inspector, "exception_notification")
        with op.batch_alter_table("exception_notification", **_batch_options(bind)) as batch_op:
            if "uq_exception_notification_case_user_version" in unique_names:
                batch_op.drop_constraint("uq_exception_notification_case_user_version", type_="unique")
            if "uq_exception_notification_case_user_version_cycle" not in unique_names:
                batch_op.create_unique_constraint(
                    "uq_exception_notification_case_user_version_cycle",
                    ["case_id", "user_id", "notification_type", "evidence_version", "occurrence_cycle"],
                )
        if "ix_exception_notification_occurrence_cycle" not in _index_names(
            sa.inspect(bind), "exception_notification"
        ):
            op.create_index(
                "ix_exception_notification_occurrence_cycle",
                "exception_notification",
                ["occurrence_cycle"],
            )
        notification_indexes = _index_names(sa.inspect(bind), "exception_notification")
        if "ix_exception_notification_archived_at" not in notification_indexes:
            op.create_index("ix_exception_notification_archived_at", "exception_notification", ["archived_at"])
        if "ix_exception_notification_archive_reason" not in notification_indexes:
            op.create_index("ix_exception_notification_archive_reason", "exception_notification", ["archive_reason"])
        detail_expression = (
            "jsonb_build_object('archived_notification_count', COUNT(notification.id), "
            "'reason', 'baseline_migration')"
            if bind.dialect.name == "postgresql"
            else "json_object('archived_notification_count', COUNT(notification.id), "
            "'reason', 'baseline_migration')"
        )
        op.execute(
            sa.text(
                f"""
                INSERT INTO exception_event (case_id, event_type, detail_json, created_at)
                SELECT notification.case_id,
                       'baseline_notifications_archived',
                       {detail_expression},
                       CURRENT_TIMESTAMP
                FROM exception_notification AS notification
                JOIN exception_case AS exception_case ON exception_case.id = notification.case_id
                WHERE exception_case.occurrence_type = 'baseline'
                  AND notification.notification_type = 'high_risk'
                  AND notification.is_read = false
                  AND notification.archived_at IS NULL
                GROUP BY notification.case_id
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE exception_notification
                SET archived_at = CURRENT_TIMESTAMP,
                    archive_reason = 'baseline_migration'
                WHERE notification_type = 'high_risk'
                  AND is_read = false
                  AND archived_at IS NULL
                  AND case_id IN (
                      SELECT id FROM exception_case WHERE occurrence_type = 'baseline'
                  )
                """
            )
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("exception_diagnosis"):
        columns = _column_names(inspector, "exception_diagnosis")
        with op.batch_alter_table("exception_diagnosis", **_batch_options(bind)) as batch_op:
            if "feedback_rating" not in columns:
                batch_op.add_column(sa.Column("feedback_rating", sa.String(40), nullable=True))
            if "feedback_note" not in columns:
                batch_op.add_column(sa.Column("feedback_note", sa.Text(), nullable=True))
            if "feedback_by_user_id" not in columns:
                batch_op.add_column(sa.Column("feedback_by_user_id", sa.Integer(), nullable=True))
                batch_op.create_foreign_key(
                    "fk_exception_diagnosis_feedback_by_user_id_users",
                    "users",
                    ["feedback_by_user_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if "feedback_at" not in columns:
                batch_op.add_column(sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True))
            inspector = sa.inspect(bind)
            if "ck_exception_diagnosis_feedback_rating" not in _check_names(inspector, "exception_diagnosis"):
                batch_op.create_check_constraint(
                    "ck_exception_diagnosis_feedback_rating",
                    "feedback_rating IS NULL OR feedback_rating IN ('helpful','partial','incorrect')",
                )

        inspector = sa.inspect(bind)
        indexes = _index_names(inspector, "exception_diagnosis")
        for column in ("feedback_rating", "feedback_by_user_id", "feedback_at"):
            index_name = f"ix_exception_diagnosis_{column}"
            if index_name not in indexes:
                op.create_index(index_name, "exception_diagnosis", [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("exception_notification"):
        indexes = _index_names(inspector, "exception_notification")
        for column in ("archive_reason", "archived_at", "occurrence_cycle"):
            index_name = f"ix_exception_notification_{column}"
            if index_name in indexes:
                op.drop_index(index_name, table_name="exception_notification")
        op.execute(
            sa.text(
                """
                UPDATE exception_notification
                SET evidence_version = substr(evidence_version, 1, 110) || ':cycle:' || occurrence_cycle
                WHERE occurrence_cycle > 0
                """
            )
        )
        unique_names = _unique_names(sa.inspect(bind), "exception_notification")
        columns = _column_names(sa.inspect(bind), "exception_notification")
        with op.batch_alter_table("exception_notification", **_batch_options(bind)) as batch_op:
            if "uq_exception_notification_case_user_version_cycle" in unique_names:
                batch_op.drop_constraint("uq_exception_notification_case_user_version_cycle", type_="unique")
            if "uq_exception_notification_case_user_version" not in unique_names:
                batch_op.create_unique_constraint(
                    "uq_exception_notification_case_user_version",
                    ["case_id", "user_id", "notification_type", "evidence_version"],
                )
            for column in ("archive_reason", "archived_at", "occurrence_cycle"):
                if column in columns:
                    batch_op.drop_column(column)
        if sa.inspect(bind).has_table("exception_event"):
            op.execute(
                sa.text(
                    "DELETE FROM exception_event WHERE event_type = 'baseline_notifications_archived'"
                )
            )

    inspector = sa.inspect(bind)
    if inspector.has_table("exception_diagnosis"):
        indexes = _index_names(inspector, "exception_diagnosis")
        for column in ("feedback_at", "feedback_by_user_id", "feedback_rating"):
            index_name = f"ix_exception_diagnosis_{column}"
            if index_name in indexes:
                op.drop_index(index_name, table_name="exception_diagnosis")
        columns = _column_names(sa.inspect(bind), "exception_diagnosis")
        with op.batch_alter_table("exception_diagnosis", **_batch_options(bind)) as batch_op:
            if "ck_exception_diagnosis_feedback_rating" in _check_names(sa.inspect(bind), "exception_diagnosis"):
                batch_op.drop_constraint("ck_exception_diagnosis_feedback_rating", type_="check")
            if "feedback_by_user_id" in columns:
                foreign_keys = {
                    foreign_key.get("name")
                    for foreign_key in sa.inspect(bind).get_foreign_keys("exception_diagnosis")
                    if foreign_key.get("name")
                }
                if "fk_exception_diagnosis_feedback_by_user_id_users" in foreign_keys:
                    batch_op.drop_constraint("fk_exception_diagnosis_feedback_by_user_id_users", type_="foreignkey")
            for column in ("feedback_at", "feedback_by_user_id", "feedback_note", "feedback_rating"):
                if column in columns:
                    batch_op.drop_column(column)

    inspector = sa.inspect(bind)
    if inspector.has_table("exception_case"):
        indexes = _index_names(inspector, "exception_case")
        for column in ("rule_version", "occurrence_cycle", "occurrence_type"):
            index_name = f"ix_exception_case_{column}"
            if index_name in indexes:
                op.drop_index(index_name, table_name="exception_case")
        columns = _column_names(sa.inspect(bind), "exception_case")
        with op.batch_alter_table("exception_case", **_batch_options(bind)) as batch_op:
            if "ck_exception_case_occurrence_type" in _check_names(sa.inspect(bind), "exception_case"):
                batch_op.drop_constraint("ck_exception_case_occurrence_type", type_="check")
            for column in ("rule_version", "occurrence_cycle", "occurrence_type"):
                if column in columns:
                    batch_op.drop_column(column)
