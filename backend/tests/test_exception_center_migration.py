import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


class ExceptionCenterMigrationTest(unittest.TestCase):
    def test_upgrade_and_downgrade_from_previous_head(self):
        backend_dir = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "exception-center.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                connection.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES ('20260728_0100')")
                connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql("INSERT INTO users (id) VALUES (1)")
                connection.exec_driver_sql("CREATE TABLE inventory_anomaly_case (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql("CREATE TABLE import_batch (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql(
                    """
                    CREATE TABLE permissions (
                        id INTEGER PRIMARY KEY,
                        permission_code VARCHAR(160) NOT NULL UNIQUE,
                        permission_name VARCHAR(255) NOT NULL,
                        resource_type VARCHAR(120) NOT NULL,
                        action_type VARCHAR(120) NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
                connection.exec_driver_sql(
                    "CREATE TABLE roles (id INTEGER PRIMARY KEY, role_code VARCHAR(80) NOT NULL UNIQUE)"
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE role_permissions (
                        id INTEGER PRIMARY KEY,
                        role_id INTEGER NOT NULL,
                        permission_id INTEGER NOT NULL,
                        created_at DATETIME NOT NULL,
                        CONSTRAINT uq_role_permissions_role_permission UNIQUE (role_id, permission_id)
                    )
                    """
                )
                for index, role_code in enumerate(
                    ("admin", "boss", "data_middle_office", "business_middle_office"),
                    start=1,
                ):
                    connection.execute(
                        text("INSERT INTO roles (id, role_code) VALUES (:id, :role_code)"),
                        {"id": index, "role_code": role_code},
                    )

            environment = os.environ.copy()
            environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
            upgraded = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "20260728_0300"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE exception_policy
                        SET ai_concurrency = 7,
                            settings_json = '{"retained_setting":"yes"}'
                        WHERE policy_key = 'default'
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO exception_case (
                            case_no, fingerprint, domain, rule_code, title, severity, status,
                            source_type, evidence_version, reason, affected_rows,
                            detected_at, last_seen_at, created_at, updated_at
                        ) VALUES (
                            'EXC-UNASSIGNED', 'unassigned-fingerprint', 'master_data',
                            'master_completeness.customer', 'Unassigned', 'warning', 'open',
                            'customer_master', 'evidence-v1', 'Unassigned reason', 1,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO exception_case (
                            case_no, fingerprint, domain, rule_code, title, severity, status,
                            source_type, source_batch_id, evidence_version, reason, affected_rows,
                            detected_at, last_seen_at, created_at, updated_at
                        ) VALUES (
                            'EXC-BASELINE', 'baseline-fingerprint', 'inventory',
                            'inventory.negative_stock', 'Baseline', 'critical', 'open',
                            'inventory_anomaly_case', 1, 'evidence-v1', 'Baseline reason', 1,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO exception_case (
                            case_no, fingerprint, domain, rule_code, title, severity, status,
                            source_type, source_batch_id, evidence_version, reason, affected_rows,
                            detected_at, last_seen_at, created_at, updated_at
                        ) VALUES (
                            'EXC-CHECK-BATCH', 'check-batch-fingerprint', 'inventory',
                            'inventory_check.quantity_mismatch', 'Check batch', 'high', 'open',
                            'inventory_check_result', 1, 'evidence-v1', 'Check reason', 1,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO exception_notification (
                            case_id, user_id, notification_type, evidence_version,
                            title, message, is_read, created_at, updated_at
                        ) VALUES (
                            (SELECT id FROM exception_case WHERE case_no = 'EXC-BASELINE'),
                            1, 'high_risk', 'evidence-v1', 'Baseline alert', 'Unread baseline alert',
                            false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO exception_diagnosis_job (
                            job_no, case_id, evidence_version, trigger_type, status, attempts,
                            available_at, created_at, updated_at
                        ) VALUES
                            (
                                'EXJOB-MIGRATION-QUEUED',
                                (SELECT id FROM exception_case WHERE case_no = 'EXC-BASELINE'),
                                'evidence-v1', 'manual', 'queued', 0,
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                            ),
                            (
                                'EXJOB-MIGRATION-PROCESSING',
                                (SELECT id FROM exception_case WHERE case_no = 'EXC-BASELINE'),
                                'evidence-v2', 'scheduled', 'processing', 1,
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                            )
                        """
                    )
                )
                connection.exec_driver_sql(
                    """
                        INSERT INTO exception_background_job (
                            job_no, job_type, payload_json, status, attempts, available_at,
                            lease_owner, lease_expires_at, dedupe_key, created_at, updated_at
                        ) VALUES
                            (
                                'EXBG-MIGRATION-UNTYPED', 'incremental_scan',
                                '{"domains":["inventory"],"source_batch_id":1}',
                                'processing', 1, CURRENT_TIMESTAMP,
                                'legacy-worker', DATETIME('now', '+1 hour'), 'incremental:1',
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                            ),
                            (
                                'EXBG-MIGRATION-IMPORT', 'incremental_scan',
                                '{"domains":["import"],"source_batch_kind":"import","source_batch_id":1}',
                                'queued', 0, CURRENT_TIMESTAMP,
                                NULL, NULL, 'legacy-import:1',
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                            ),
                            (
                                'EXBG-MIGRATION-CHECK', 'incremental_scan',
                                '{"domains":["inventory"],"source_batch_kind":"inventory_check","source_batch_id":1}',
                                'queued', 0, CURRENT_TIMESTAMP,
                                NULL, NULL, 'legacy-check:1',
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                            )
                    """
                )
            upgraded = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(upgraded.returncode, 0, upgraded.stderr)

            expected_tables = {
                "exception_case",
                "exception_evidence",
                "exception_diagnosis_job",
                "exception_background_job",
                "exception_diagnosis",
                "exception_action",
                "exception_event",
                "exception_notification",
                "exception_policy",
                "exception_service_heartbeat",
            }
            self.assertTrue(expected_tables.issubset(set(inspect(engine).get_table_names())))
            self.assertIn("content_sha256", {column["name"] for column in inspect(engine).get_columns("import_batch")})
            self.assertIn("ix_import_batch_content_sha256", {index["name"] for index in inspect(engine).get_indexes("import_batch")})
            self.assertTrue(
                {"occurrence_type", "occurrence_cycle", "rule_version", "source_batch_kind"}.issubset(
                    {column["name"] for column in inspect(engine).get_columns("exception_case")}
                )
            )
            self.assertIn(
                "ck_exception_case_source_batch_ref_pair",
                {constraint["name"] for constraint in inspect(engine).get_check_constraints("exception_case")},
            )
            self.assertTrue(
                {"ix_exception_case_source_batch_kind", "ix_exception_case_source_batch_ref"}.issubset(
                    {index["name"] for index in inspect(engine).get_indexes("exception_case")}
                )
            )
            self.assertTrue(
                {"feedback_rating", "feedback_note", "feedback_by_user_id", "feedback_at"}.issubset(
                    {column["name"] for column in inspect(engine).get_columns("exception_diagnosis")}
                )
            )
            self.assertTrue(
                {
                    "prompt_version",
                    "contract_version",
                    "provider_request_id",
                    "latency_ms",
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                }.issubset({column["name"] for column in inspect(engine).get_columns("exception_diagnosis")})
            )
            self.assertTrue(
                {"cancel_requested_at", "cancel_requested_by_user_id"}.issubset(
                    {column["name"] for column in inspect(engine).get_columns("exception_diagnosis_job")}
                )
            )
            self.assertIn(
                "uq_exception_diagnosis_job_active_case_evidence",
                {index["name"] for index in inspect(engine).get_indexes("exception_diagnosis_job")},
            )
            self.assertTrue(
                {
                    "manual_ai_enabled",
                    "scheduled_ai_enabled",
                    "full_scan_enabled",
                    "digest_enabled",
                    "manual_ai_daily_limit",
                    "scheduled_ai_daily_limit",
                    "scheduled_ai_batch_limit",
                }.issubset({column["name"] for column in inspect(engine).get_columns("exception_policy")})
            )
            self.assertTrue(
                {"occurrence_cycle", "archived_at", "archive_reason"}.issubset(
                    {column["name"] for column in inspect(engine).get_columns("exception_notification")}
                )
            )
            with engine.connect() as connection:
                permission_count = connection.scalar(
                    text("SELECT COUNT(*) FROM permissions WHERE permission_code LIKE 'exception_center.%'")
                )
                grant_count = connection.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM role_permissions rp
                        JOIN permissions p ON p.id = rp.permission_id
                        WHERE p.permission_code LIKE 'exception_center.%'
                        """
                    )
                )
                baseline = connection.execute(
                    text("SELECT occurrence_type, rule_version FROM exception_case WHERE case_no = 'EXC-BASELINE'")
                ).one()
                archived = connection.execute(
                    text(
                        """
                        SELECT is_read, read_at, acknowledged_at, archived_at, archive_reason
                        FROM exception_notification
                        WHERE notification_type = 'high_risk'
                        """
                    )
                ).one()
                archive_event = connection.execute(
                    text(
                        """
                        SELECT detail_json
                        FROM exception_event
                        WHERE event_type = 'baseline_notifications_archived'
                        """
                    )
                ).one()
                policy = connection.execute(
                    text(
                        """
                        SELECT manual_ai_enabled, scheduled_ai_enabled, full_scan_enabled, digest_enabled,
                               manual_ai_daily_limit, scheduled_ai_daily_limit,
                               scheduled_ai_batch_limit, ai_concurrency
                        FROM exception_policy
                        WHERE policy_key = 'default'
                        """
                    )
                ).one()
                batch_kinds = dict(
                    connection.execute(
                        text("SELECT case_no, source_batch_kind FROM exception_case ORDER BY case_no")
                    ).all()
                )
                diagnosis_jobs = dict(
                    connection.execute(
                        text(
                            "SELECT job_no, status FROM exception_diagnosis_job "
                            "WHERE job_no LIKE 'EXJOB-MIGRATION-%' ORDER BY job_no"
                        )
                    ).all()
                )
                background_jobs = {
                    row.job_no: row
                    for row in connection.execute(
                        text(
                            "SELECT job_no, status, dedupe_key, payload_json, error_message, "
                            "completed_at, lease_owner, lease_expires_at "
                            "FROM exception_background_job "
                            "WHERE job_no LIKE 'EXBG-MIGRATION-%' ORDER BY job_no"
                        )
                    ).all()
                }
            self.assertEqual(permission_count, 5)
            self.assertEqual(grant_count, 14)
            self.assertEqual(baseline.occurrence_type, "baseline")
            self.assertEqual(baseline.rule_version, "legacy-v1")
            self.assertEqual(archived.is_read, 0)
            self.assertIsNone(archived.read_at)
            self.assertIsNone(archived.acknowledged_at)
            self.assertIsNotNone(archived.archived_at)
            self.assertEqual(archived.archive_reason, "baseline_migration")
            archive_detail = json.loads(archive_event.detail_json) if isinstance(archive_event.detail_json, str) else archive_event.detail_json
            self.assertEqual(archive_detail["archived_notification_count"], 1)
            self.assertEqual(archive_detail["reason"], "baseline_migration")
            self.assertEqual(tuple(policy[:4]), (0, 0, 0, 0))
            self.assertEqual(tuple(policy[4:]), (20, 0, 20, 7))
            self.assertEqual(batch_kinds["EXC-BASELINE"], "import")
            self.assertEqual(batch_kinds["EXC-CHECK-BATCH"], "inventory_check")
            self.assertIsNone(batch_kinds["EXC-UNASSIGNED"])
            self.assertEqual(diagnosis_jobs["EXJOB-MIGRATION-PROCESSING"], "processing")
            self.assertEqual(diagnosis_jobs["EXJOB-MIGRATION-QUEUED"], "queued")
            self.assertEqual(background_jobs["EXBG-MIGRATION-UNTYPED"].status, "failed")
            self.assertIsNone(background_jobs["EXBG-MIGRATION-UNTYPED"].dedupe_key)
            self.assertEqual(
                background_jobs["EXBG-MIGRATION-UNTYPED"].error_message,
                "legacy_incremental_job_missing_typed_batch_reference",
            )
            self.assertIsNotNone(background_jobs["EXBG-MIGRATION-UNTYPED"].completed_at)
            self.assertIsNone(background_jobs["EXBG-MIGRATION-UNTYPED"].lease_owner)
            self.assertIsNone(background_jobs["EXBG-MIGRATION-UNTYPED"].lease_expires_at)
            self.assertEqual(
                background_jobs["EXBG-MIGRATION-IMPORT"].dedupe_key,
                "incremental:import:1",
            )
            self.assertEqual(
                background_jobs["EXBG-MIGRATION-CHECK"].dedupe_key,
                "incremental:inventory_check:1",
            )

            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE exception_policy
                        SET manual_ai_enabled = true,
                            scheduled_ai_enabled = false,
                            full_scan_enabled = true,
                            digest_enabled = true,
                            manual_ai_daily_limit = 17,
                            scheduled_ai_daily_limit = 3,
                            scheduled_ai_batch_limit = 4,
                            ai_concurrency = 7
                        WHERE policy_key = 'default'
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO exception_notification (
                            case_id, user_id, notification_type, evidence_version, occurrence_cycle,
                            title, message, is_read, created_at, updated_at
                        ) VALUES (
                            (SELECT id FROM exception_case WHERE case_no = 'EXC-BASELINE'),
                            1, 'high_risk', 'evidence-v1', 1,
                            'Reopened alert', 'Same evidence, new occurrence', false,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """
                    )
                )

            cycle_downgrade = subprocess.run(
                [sys.executable, "-m", "alembic", "downgrade", "20260728_0400"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(cycle_downgrade.returncode, 0, cycle_downgrade.stderr)
            with engine.connect() as connection:
                preserved_notifications = list(
                    connection.execute(
                        text(
                            "SELECT evidence_version, occurrence_cycle "
                            "FROM exception_notification ORDER BY id"
                        )
                    ).all()
                )
                downgraded_policy = connection.execute(
                    text(
                        "SELECT settings_json, ai_concurrency FROM exception_policy "
                        "WHERE policy_key = 'default'"
                    )
                ).one()
            self.assertEqual(len(preserved_notifications), 2)
            self.assertEqual([row.occurrence_cycle for row in preserved_notifications], [0, 1])
            self.assertEqual({row.evidence_version for row in preserved_notifications}, {"evidence-v1"})
            self.assertIn(
                "occurrence_cycle",
                {column["name"] for column in inspect(engine).get_columns("exception_notification")},
            )
            self.assertTrue(
                {"occurrence_type", "occurrence_cycle", "rule_version"}.issubset(
                    {column["name"] for column in inspect(engine).get_columns("exception_case")}
                )
            )
            self.assertTrue(
                {"feedback_rating", "feedback_note", "feedback_by_user_id", "feedback_at"}.issubset(
                    {column["name"] for column in inspect(engine).get_columns("exception_diagnosis")}
                )
            )
            self.assertTrue(
                {"archived_at", "archive_reason"}.issubset(
                    {column["name"] for column in inspect(engine).get_columns("exception_notification")}
                )
            )
            self.assertNotIn("exception_service_heartbeat", set(inspect(engine).get_table_names()))
            self.assertNotIn(
                "prompt_version",
                {column["name"] for column in inspect(engine).get_columns("exception_diagnosis")},
            )
            self.assertNotIn(
                "cancel_requested_at",
                {column["name"] for column in inspect(engine).get_columns("exception_diagnosis_job")},
            )
            self.assertNotIn(
                "uq_exception_diagnosis_job_active_case_evidence",
                {index["name"] for index in inspect(engine).get_indexes("exception_diagnosis_job")},
            )
            self.assertNotIn(
                "manual_ai_enabled",
                {column["name"] for column in inspect(engine).get_columns("exception_policy")},
            )
            self.assertNotIn(
                "source_batch_kind",
                {column["name"] for column in inspect(engine).get_columns("exception_case")},
            )
            snapshot_settings = (
                json.loads(downgraded_policy.settings_json)
                if isinstance(downgraded_policy.settings_json, str)
                else downgraded_policy.settings_json
            )
            self.assertEqual(downgraded_policy.ai_concurrency, 7)
            self.assertEqual(
                snapshot_settings["migration_20260729_0500_policy"],
                {
                    "manual_ai_enabled": 1,
                    "scheduled_ai_enabled": 0,
                    "full_scan_enabled": 1,
                    "digest_enabled": 1,
                    "manual_ai_daily_limit": 17,
                    "scheduled_ai_daily_limit": 3,
                    "scheduled_ai_batch_limit": 4,
                    "ai_concurrency": 7,
                    "settings_was_null": False,
                },
            )
            self.assertEqual(snapshot_settings["retained_setting"], "yes")
            with engine.connect() as connection:
                restored_background = {
                    row.job_no: row
                    for row in connection.execute(
                        text(
                            "SELECT job_no, status, dedupe_key, payload_json, error_message, "
                            "completed_at, lease_owner, lease_expires_at "
                            "FROM exception_background_job "
                            "WHERE job_no LIKE 'EXBG-MIGRATION-%' ORDER BY job_no"
                        )
                    ).all()
                }
            self.assertEqual(restored_background["EXBG-MIGRATION-UNTYPED"].status, "processing")
            self.assertEqual(restored_background["EXBG-MIGRATION-UNTYPED"].dedupe_key, "incremental:1")
            self.assertIsNone(restored_background["EXBG-MIGRATION-UNTYPED"].error_message)
            self.assertIsNone(restored_background["EXBG-MIGRATION-UNTYPED"].completed_at)
            self.assertEqual(restored_background["EXBG-MIGRATION-UNTYPED"].lease_owner, "legacy-worker")
            self.assertIsNotNone(restored_background["EXBG-MIGRATION-UNTYPED"].lease_expires_at)
            self.assertEqual(restored_background["EXBG-MIGRATION-IMPORT"].dedupe_key, "legacy-import:1")
            self.assertEqual(restored_background["EXBG-MIGRATION-CHECK"].dedupe_key, "legacy-check:1")

            cycle_upgrade = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(cycle_upgrade.returncode, 0, cycle_upgrade.stderr)
            with engine.connect() as connection:
                restored_policy = connection.execute(
                    text(
                        """
                        SELECT manual_ai_enabled, scheduled_ai_enabled, full_scan_enabled,
                               digest_enabled, manual_ai_daily_limit, scheduled_ai_daily_limit,
                               scheduled_ai_batch_limit, ai_concurrency, settings_json
                        FROM exception_policy WHERE policy_key = 'default'
                        """
                    )
                ).one()
            self.assertEqual(tuple(restored_policy[:8]), (1, 0, 1, 1, 17, 3, 4, 7))
            restored_settings = (
                json.loads(restored_policy.settings_json)
                if isinstance(restored_policy.settings_json, str)
                else restored_policy.settings_json
            )
            self.assertEqual(restored_settings, {"retained_setting": "yes"})

            downgraded = subprocess.run(
                [sys.executable, "-m", "alembic", "downgrade", "20260728_0100"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(downgraded.returncode, 0, downgraded.stderr)
            self.assertTrue(expected_tables.isdisjoint(set(inspect(engine).get_table_names())))
            self.assertNotIn("content_sha256", {column["name"] for column in inspect(engine).get_columns("import_batch")})
            with engine.connect() as connection:
                self.assertEqual(
                    connection.scalar(
                        text("SELECT COUNT(*) FROM permissions WHERE permission_code LIKE 'exception_center.%'")
                    ),
                    0,
                )
            engine.dispose()

    def test_duplicate_active_diagnosis_jobs_block_upgrade_without_mutating_jobs(self):
        backend_dir = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "duplicate-diagnosis-jobs.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                connection.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES ('20260728_0100')")
                connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql("INSERT INTO users (id) VALUES (1)")
                connection.exec_driver_sql("CREATE TABLE inventory_anomaly_case (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql("CREATE TABLE import_batch (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql(
                    """
                    CREATE TABLE permissions (
                        id INTEGER PRIMARY KEY,
                        permission_code VARCHAR(160) NOT NULL UNIQUE,
                        permission_name VARCHAR(255) NOT NULL,
                        resource_type VARCHAR(120) NOT NULL,
                        action_type VARCHAR(120) NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
                connection.exec_driver_sql(
                    "CREATE TABLE roles (id INTEGER PRIMARY KEY, role_code VARCHAR(80) NOT NULL UNIQUE)"
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE role_permissions (
                        id INTEGER PRIMARY KEY,
                        role_id INTEGER NOT NULL,
                        permission_id INTEGER NOT NULL,
                        created_at DATETIME NOT NULL,
                        CONSTRAINT uq_role_permissions_role_permission UNIQUE (role_id, permission_id)
                    )
                    """
                )
                for index, role_code in enumerate(
                    ("admin", "boss", "data_middle_office", "business_middle_office"),
                    start=1,
                ):
                    connection.execute(
                        text("INSERT INTO roles (id, role_code) VALUES (:id, :role_code)"),
                        {"id": index, "role_code": role_code},
                    )

            environment = os.environ.copy()
            environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
            previous_head = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "20260728_0400"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(previous_head.returncode, 0, previous_head.stderr)

            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO exception_case (
                            case_no, fingerprint, domain, rule_code, title, severity, status,
                            source_type, evidence_version, reason, affected_rows,
                            detected_at, last_seen_at, created_at, updated_at
                        ) VALUES (
                            'EXC-DUPLICATE-JOBS', 'duplicate-jobs-fingerprint', 'inventory',
                            'inventory.negative_stock', 'Duplicate jobs', 'critical', 'open',
                            'inventory_anomaly_case', 'evidence-v1', 'Duplicate jobs fixture', 1,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO exception_diagnosis_job (
                            job_no, case_id, evidence_version, trigger_type, status, attempts,
                            available_at, created_at, updated_at
                        ) VALUES
                            (
                                'EXJOB-DUPLICATE-QUEUED',
                                (SELECT id FROM exception_case WHERE case_no = 'EXC-DUPLICATE-JOBS'),
                                'evidence-v1', 'manual', 'queued', 0,
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                            ),
                            (
                                'EXJOB-DUPLICATE-PROCESSING',
                                (SELECT id FROM exception_case WHERE case_no = 'EXC-DUPLICATE-JOBS'),
                                'evidence-v1', 'scheduled', 'processing', 1,
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                            )
                        """
                    )
                )
                jobs_before = list(
                    connection.execute(
                        text(
                            "SELECT job_no, status, attempts, updated_at "
                            "FROM exception_diagnosis_job ORDER BY job_no"
                        )
                    ).all()
                )

            rejected = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "20260729_0500"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            with engine.connect() as connection:
                current_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                jobs_after = list(
                    connection.execute(
                        text(
                            "SELECT job_no, status, attempts, updated_at "
                            "FROM exception_diagnosis_job ORDER BY job_no"
                        )
                    ).all()
                )
            engine.dispose()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(
                "duplicate active diagnosis jobs must be reconciled",
                f"{rejected.stdout}\n{rejected.stderr}",
            )
            self.assertEqual(current_revision, "20260728_0400")
            self.assertEqual(jobs_after, jobs_before)


if __name__ == "__main__":
    unittest.main()
