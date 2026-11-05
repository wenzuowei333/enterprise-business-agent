import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import (
    CustomerMaster,
    ExceptionCase,
    ExceptionDiagnosis,
    ExceptionDiagnosisJob,
    ExceptionEvidence,
    ExceptionEvent,
    ExceptionNotification,
    ExceptionPolicy,
    ImportBatch,
    InventoryCheckBatch,
    InventoryCheckResult,
    InventoryFlowLedger,
    InventorySnapshot,
    Permission,
    ProductMaster,
    Role,
    RolePermission,
    SalesDetail,
    SupplierMaster,
    User,
)
from app.services.exception_center_service import (
    enqueue_due_ai_diagnoses,
    run_full_exception_scan,
    scoped_exception_stmt,
    serialize_diagnosis,
    summary_for_cases,
    sync_exception_cases,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ExceptionOccurrenceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        role = Role(role_code="admin", role_name="Admin")
        self.db.add(role)
        self.db.flush()
        self.admin = User(
            username="occurrence-admin",
            password_hash="hash",
            real_name="Occurrence Admin",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add(self.admin)
        self.db.flush()
        for code in (
            "exception_center.view",
            "inventory_snapshot.view",
            "inventory_check.view",
            "customer.view",
            "supplier.view",
            "product.view",
            "import.view",
        ):
            permission = Permission(
                permission_code=code,
                permission_name=code,
                resource_type=code.split(".")[0],
                action_type=code.split(".")[-1],
            )
            self.db.add(permission)
            self.db.flush()
            self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _inventory_batch(self, batch_no: str = "INV-OCCURRENCE") -> ImportBatch:
        batch = ImportBatch(
            batch_no=batch_no,
            file_name=f"{batch_no}.xlsx",
            file_type="inventory_snapshot",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc),
            status="committed",
            total_rows=1,
            success_rows=1,
            error_rows=0,
            raw_file_path=f"{batch_no}.xlsx",
        )
        self.db.add(batch)
        self.db.flush()
        return batch

    def _negative_snapshot(self, product_code: str = "NEG-OCC") -> InventorySnapshot:
        batch = self._inventory_batch()
        snapshot = InventorySnapshot(
            batch_id=batch.id,
            row_number=1,
            data_date=batch.data_date,
            product_code=product_code,
            product_name=product_code,
            warehouse_name="Main",
            warehouse_scope="specific",
            unit_relation="1:1",
            stock_qty=Decimal("-5"),
            locked_base_qty=Decimal("0"),
            raw_row_json={},
        )
        self.db.add(snapshot)
        self.db.commit()
        return snapshot

    def _scheduled_case(
        self,
        suffix: str,
        *,
        occurrence_type: str,
        severity: str,
        detected_at: datetime,
        last_seen_at: datetime,
    ) -> ExceptionCase:
        case = ExceptionCase(
            case_no=f"EXC-SCHEDULE-{suffix}",
            fingerprint=f"schedule-{suffix}",
            domain="inventory",
            rule_code=f"schedule.{suffix.lower()}",
            title=f"Schedule {suffix}",
            severity=severity,
            status="open",
            occurrence_type=occurrence_type,
            occurrence_cycle=0 if occurrence_type == "baseline" else 1,
            resource_type="product",
            resource_id=suffix,
            resource_code=suffix,
            resource_name=suffix,
            source_type="inventory_snapshot_quality",
            source_id=suffix,
            evidence_version=f"evidence-{suffix}",
            reason="Scheduler ordering regression case",
            detected_at=detected_at,
            last_seen_at=last_seen_at,
        )
        self.db.add(case)
        self.db.flush()
        return case

    def _enable_scheduled_ai_for_test(self) -> None:
        self.db.add(
            ExceptionPolicy(
                policy_key="default",
                is_enabled=True,
                manual_ai_enabled=False,
                scheduled_ai_enabled=True,
                full_scan_enabled=False,
                digest_enabled=False,
                manual_ai_daily_limit=0,
                scheduled_ai_daily_limit=100,
                scheduled_ai_batch_limit=50,
                ai_concurrency=1,
                stale_diagnosis_hours=24,
            )
        )
        self.db.commit()
        ai_enabled_patch = patch(
            "app.services.exception_center_service.settings.exception_ai_enabled",
            True,
        )
        ai_enabled_patch.start()
        self.addCleanup(ai_enabled_patch.stop)

    def test_new_open_update_and_resolved_rehit_classification(self):
        snapshot = self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        self.assertEqual(case.occurrence_type, "new")
        self.assertEqual(case.rule_version, "2026-07-28.v2")
        first_notification_count = self.db.query(ExceptionNotification).filter_by(case_id=case.id).count()
        self.assertEqual(first_notification_count, 1)

        snapshot.stock_qty = Decimal("-6")
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertEqual(case.occurrence_type, "new")

        snapshot.stock_qty = Decimal("5")
        run_full_exception_scan(self.db)
        self.db.commit()
        self.assertEqual(case.status, "resolved")
        snapshot.stock_qty = Decimal("-7")
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertEqual(case.status, "open")
        self.assertEqual(case.occurrence_type, "reopened")
        self.assertGreater(self.db.query(ExceptionNotification).filter_by(case_id=case.id).count(), first_notification_count)

    def test_same_evidence_reopen_uses_new_cycle_and_preserves_notification_history(self):
        snapshot = self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        first_evidence_version = case.evidence_version
        snapshot.stock_qty = Decimal("5")
        run_full_exception_scan(self.db)
        self.db.commit()
        snapshot.stock_qty = Decimal("-5")
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)

        notifications = list(
            self.db.scalars(
                select(ExceptionNotification)
                .where(ExceptionNotification.case_id == case.id)
                .order_by(ExceptionNotification.occurrence_cycle)
            ).all()
        )
        self.assertEqual(case.evidence_version, first_evidence_version)
        self.assertEqual(case.occurrence_type, "reopened")
        self.assertEqual(case.occurrence_cycle, 2)
        self.assertEqual([row.occurrence_cycle for row in notifications], [1, 2])
        self.assertEqual(len({row.evidence_version for row in notifications}), 1)

    def test_changed_baseline_becomes_new_cycle_and_sends_high_risk_notification(self):
        snapshot = self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        self.db.query(ExceptionNotification).filter_by(case_id=case.id).delete()
        case.occurrence_type = "baseline"
        case.occurrence_cycle = 0
        previous_cycle = case.occurrence_cycle
        case.assignee_user_id = None
        case.due_at = None
        snapshot.stock_qty = Decimal("-8")
        self.db.commit()

        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertEqual(case.occurrence_type, "new")
        self.assertEqual(case.occurrence_cycle, previous_cycle + 1)
        self.assertEqual(case.assignee_user_id, self.admin.id)
        self.assertIsNotNone(case.due_at)
        notification = self.db.scalar(select(ExceptionNotification).where(ExceptionNotification.case_id == case.id))
        self.assertIsNotNone(notification)
        self.assertEqual(notification.occurrence_cycle, case.occurrence_cycle)
        event = self.db.scalar(
            select(ExceptionEvent)
            .where(ExceptionEvent.case_id == case.id, ExceptionEvent.event_type == "evidence_changed")
            .order_by(ExceptionEvent.id.desc())
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.detail_json["previous_occurrence_type"], "baseline")
        self.assertEqual(event.detail_json["occurrence_type"], "new")

    def test_legacy_baseline_first_refresh_rehashes_without_notification_flood(self):
        self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        self.db.query(ExceptionNotification).filter_by(case_id=case.id).delete()
        case.occurrence_type = "baseline"
        case.occurrence_cycle = 0
        case.rule_version = "legacy-v1"
        case.evidence_version = "legacy-evidence-without-rule-version"
        previous_status = case.status
        self.db.commit()

        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)

        self.assertEqual(case.occurrence_type, "baseline")
        self.assertEqual(case.occurrence_cycle, 0)
        self.assertEqual(case.status, previous_status)
        self.assertEqual(case.rule_version, "2026-07-28.v2")
        self.assertNotEqual(case.evidence_version, "legacy-evidence-without-rule-version")
        self.assertEqual(self.db.query(ExceptionNotification).filter_by(case_id=case.id).count(), 0)
        refresh_event = self.db.scalar(
            select(ExceptionEvent)
            .where(ExceptionEvent.case_id == case.id, ExceptionEvent.event_type == "baseline_refreshed")
            .order_by(ExceptionEvent.id.desc())
        )
        self.assertIsNotNone(refresh_event)
        self.assertEqual(refresh_event.from_status, previous_status)
        self.assertEqual(refresh_event.to_status, previous_status)
        self.assertEqual(refresh_event.detail_json["previous_rule_version"], "legacy-v1")
        self.assertEqual(refresh_event.detail_json["rule_version"], "2026-07-28.v2")

    def test_legacy_baseline_severity_upgrade_is_immediately_actionable(self):
        self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        self.db.query(ExceptionNotification).filter_by(case_id=case.id).delete()
        case.occurrence_type = "baseline"
        case.occurrence_cycle = 0
        case.rule_version = "legacy-v1"
        case.evidence_version = "legacy-evidence-without-rule-version"
        case.severity = "high"
        self.db.commit()

        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)

        self.assertEqual(case.severity, "critical")
        self.assertEqual(case.occurrence_type, "new")
        self.assertEqual(case.occurrence_cycle, 1)
        notification = self.db.scalar(select(ExceptionNotification).where(ExceptionNotification.case_id == case.id))
        self.assertIsNotNone(notification)
        self.assertEqual(notification.occurrence_cycle, 1)
        event = self.db.scalar(
            select(ExceptionEvent)
            .where(ExceptionEvent.case_id == case.id, ExceptionEvent.event_type == "severity_upgraded")
            .order_by(ExceptionEvent.id.desc())
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.detail_json["previous_occurrence_type"], "baseline")
        self.assertEqual(event.detail_json["occurrence_type"], "new")

    def test_resolved_legacy_baseline_reopens_when_first_refresh_still_detects_it(self):
        self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        self.db.query(ExceptionNotification).filter_by(case_id=case.id).delete()
        case.status = "resolved"
        case.resolved_at = datetime.now(timezone.utc)
        case.occurrence_type = "baseline"
        case.occurrence_cycle = 0
        case.rule_version = "legacy-v1"
        case.evidence_version = "legacy-evidence-without-rule-version"
        self.db.commit()

        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)

        self.assertEqual(case.status, "open")
        self.assertEqual(case.occurrence_type, "reopened")
        self.assertEqual(case.occurrence_cycle, 1)
        notification = self.db.scalar(select(ExceptionNotification).where(ExceptionNotification.case_id == case.id))
        self.assertIsNotNone(notification)
        event = self.db.scalar(
            select(ExceptionEvent)
            .where(ExceptionEvent.case_id == case.id, ExceptionEvent.event_type == "reopened")
            .order_by(ExceptionEvent.id.desc())
        )
        self.assertIsNotNone(event)

    def test_active_evidence_change_keeps_cycle_and_records_accurate_event(self):
        snapshot = self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        previous_cycle = case.occurrence_cycle

        snapshot.stock_qty = Decimal("-6")
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)

        self.assertEqual(case.occurrence_type, "new")
        self.assertEqual(case.occurrence_cycle, previous_cycle)
        latest_event = self.db.scalar(
            select(ExceptionEvent).where(ExceptionEvent.case_id == case.id).order_by(ExceptionEvent.id.desc())
        )
        self.assertEqual(latest_event.event_type, "evidence_changed")
        self.assertEqual(latest_event.from_status, "open")
        self.assertEqual(latest_event.to_status, "open")

    def test_occurrence_filter_summary_and_diagnosis_feedback_serialization(self):
        self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        case.occurrence_type = "baseline"
        diagnosis = ExceptionDiagnosis(
            case_id=case.id,
            evidence_version=case.evidence_version,
            root_cause_code="snapshot_mismatch",
            summary="Summary",
            confidence=Decimal("0.9000"),
            disposition="actionable",
            evidence_refs_json=[],
            impact_json={},
            recommended_steps_json=[],
            missing_evidence_json=[],
            feedback_rating="helpful",
            feedback_note="Useful",
            feedback_by_user_id=self.admin.id,
            feedback_at=datetime.now(timezone.utc),
        )
        self.db.add(diagnosis)
        self.db.commit()

        baseline_cases = list(self.db.scalars(scoped_exception_stmt(self.db, self.admin, "baseline")).all())
        self.assertEqual([row.id for row in baseline_cases], [case.id])
        summary = summary_for_cases(self.db, self.admin, occurrence_type="baseline")
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["by_occurrence"], {"baseline": 1})
        payload = serialize_diagnosis(diagnosis)
        self.assertEqual(payload["feedback_rating"], "helpful")
        self.assertEqual(payload["feedback_note"], "Useful")
        self.assertEqual(payload["feedback_by_user_id"], self.admin.id)
        self.assertIsNotNone(payload["feedback_at"])

    def test_master_completeness_requires_valid_status_and_recent_business(self):
        sales_batch = ImportBatch(
            batch_no="SALES-ACTIVITY",
            file_name="sales.xlsx",
            file_type="sales_detail",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc),
            status="committed",
            total_rows=2,
            success_rows=2,
            error_rows=0,
            raw_file_path="sales.xlsx",
        )
        customers = [
            CustomerMaster(customer_code="CUS-RECENT", customer_name="Recent", status="active"),
            CustomerMaster(customer_code="CUS-OLD", customer_name="Old", status="active"),
            CustomerMaster(customer_code="CUS-INACTIVE", customer_name="Inactive", status="inactive"),
        ]
        self.db.add_all([sales_batch, *customers])
        self.db.flush()
        self.db.add_all(
            [
                SalesDetail(batch_id=sales_batch.id, row_number=1, data_date=date(2026, 7, 28), customer_code="CUS-RECENT"),
                SalesDetail(batch_id=sales_batch.id, row_number=2, data_date=date(2025, 7, 27), customer_code="CUS-OLD"),
            ]
        )
        self.db.add(SupplierMaster(supplier_code="SUP-DISABLED", supplier_name="Disabled", status="disabled"))
        self.db.add(ProductMaster(product_code="PROD-ARCHIVED", product_name="Archived", status="archived"))
        self.db.commit()

        sync_exception_cases(self.db, domains={"master_data"})
        self.db.commit()
        codes = set(
            self.db.scalars(
                select(ExceptionCase.resource_code).where(ExceptionCase.rule_code.like("master_completeness.%"))
            ).all()
        )
        self.assertIn("CUS-RECENT", codes)
        self.assertNotIn("CUS-OLD", codes)
        self.assertNotIn("CUS-INACTIVE", codes)
        self.assertNotIn("SUP-DISABLED", codes)
        self.assertNotIn("PROD-ARCHIVED", codes)

    def test_latest_completed_check_warehouse_sync_lag_and_tolerance(self):
        completed = InventoryCheckBatch(
            batch_no="CHECK-COMPLETED",
            file_name="completed.xlsx",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            status="completed",
            total_rows=3,
            raw_file_path="completed.xlsx",
        )
        self.db.add(completed)
        self.db.flush()
        self.db.add_all(
            [
                InventoryCheckResult(
                    batch_id=completed.id,
                    result_type="quantity_mismatch",
                    product_code="WH-MISSING",
                    warehouse_name="-",
                    diff_qty=Decimal("2"),
                    system_data_date=date(2026, 7, 28),
                ),
                InventoryCheckResult(
                    batch_id=completed.id,
                    result_type="missing_in_system",
                    product_code="WH-MISSING-2",
                    warehouse_name="unknown",
                    diff_qty=Decimal("1"),
                    system_data_date=date(2026, 7, 28),
                ),
                InventoryCheckResult(
                    batch_id=completed.id,
                    result_type="quantity_mismatch",
                    product_code="WITHIN-TOLERANCE",
                    warehouse_name="Main",
                    diff_qty=Decimal("0.0001"),
                    system_data_date=date(2026, 7, 28),
                ),
                InventoryCheckResult(
                    batch_id=completed.id,
                    result_type="quantity_mismatch",
                    product_code="SYNC-LAG",
                    warehouse_name="-",
                    diff_qty=Decimal("3"),
                    system_data_date=date(2026, 7, 27),
                ),
            ]
        )
        pending = InventoryCheckBatch(
            batch_no="CHECK-PENDING",
            file_name="pending.xlsx",
            data_date=date(2026, 7, 29),
            uploaded_by=self.admin.id,
            status="processing",
            total_rows=1,
            raw_file_path="pending.xlsx",
        )
        self.db.add(pending)
        self.db.flush()
        self.db.add(
            InventoryCheckResult(
                batch_id=pending.id,
                result_type="missing_in_system",
                product_code="PENDING-ONLY",
                product_name="Pending only",
                warehouse_name="Main",
                diff_qty=Decimal("1"),
            )
        )
        self.db.commit()

        sync_exception_cases(self.db, domains={"inventory"})
        self.db.commit()
        rule_codes = set(self.db.scalars(select(ExceptionCase.rule_code)).all())
        resource_codes = set(self.db.scalars(select(ExceptionCase.resource_code)).all())
        self.assertIn("inventory_check.warehouse_missing", rule_codes)
        self.assertIn("inventory_check.sync_lag", rule_codes)
        self.assertNotIn("WITHIN-TOLERANCE", resource_codes)
        self.assertNotIn("PENDING-ONLY", resource_codes)
        warehouse_cases = list(
            self.db.scalars(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory_check.warehouse_missing")).all()
        )
        self.assertEqual(len(warehouse_cases), 1)
        self.assertEqual(warehouse_cases[0].severity, "warning")
        self.assertEqual(warehouse_cases[0].affected_rows, 2)
        sync_lag_case = self.db.scalar(
            select(ExceptionCase).where(ExceptionCase.rule_code == "inventory_check.sync_lag")
        )
        sync_lag_evidence = self.db.scalar(
            select(ExceptionEvidence).where(
                ExceptionEvidence.case_id == sync_lag_case.id,
                ExceptionEvidence.evidence_version == sync_lag_case.evidence_version,
            )
        )
        self.assertEqual(sync_lag_evidence.data_json["suppressed_result_ids"]["total"], 1)
        self.assertEqual(len(sync_lag_evidence.data_json["suppressed_result_ids"]["sample"]), 1)
        self.assertFalse(sync_lag_evidence.data_json["suppressed_result_ids"]["truncated"])

    def test_tiny_negative_stock_is_suppressed(self):
        snapshot = self._negative_snapshot()
        snapshot.stock_qty = Decimal("-0.0001")
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        self.assertIsNone(case)

    def test_scheduled_ai_skips_fresh_baseline_but_accepts_change_or_stale_case(self):
        self._enable_scheduled_ai_for_test()
        snapshot = self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        case.occurrence_type = "baseline"
        self.db.commit()

        self.assertEqual(enqueue_due_ai_diagnoses(self.db), [])

        snapshot.stock_qty = Decimal("-6")
        run_full_exception_scan(self.db)
        self.db.commit()
        changed_jobs = enqueue_due_ai_diagnoses(self.db)
        self.assertEqual([job.case_id for job in changed_jobs], [case.id])

        self.db.query(ExceptionDiagnosisJob).filter_by(case_id=case.id).delete()
        case.status = "open"
        case.detected_at = datetime.now(timezone.utc) - timedelta(hours=25)
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertGreater(case.last_seen_at, case.detected_at)
        stale_jobs = enqueue_due_ai_diagnoses(self.db)
        self.assertEqual([job.case_id for job in stale_jobs], [case.id])

    def test_scheduled_ai_prioritizes_occurrences_then_severity_and_freshness(self):
        self._enable_scheduled_ai_for_test()
        now = datetime.now(timezone.utc)
        baseline_critical = self._scheduled_case(
            "BASELINE-CRITICAL",
            occurrence_type="baseline",
            severity="critical",
            detected_at=now - timedelta(hours=30),
            last_seen_at=now,
        )
        reopened_high_older = self._scheduled_case(
            "REOPENED-HIGH-OLDER",
            occurrence_type="reopened",
            severity="high",
            detected_at=now - timedelta(days=3),
            last_seen_at=now - timedelta(hours=2),
        )
        new_high_fresh = self._scheduled_case(
            "NEW-HIGH-FRESH",
            occurrence_type="new",
            severity="high",
            detected_at=now - timedelta(days=1),
            last_seen_at=now - timedelta(minutes=5),
        )
        new_warning = self._scheduled_case(
            "NEW-WARNING",
            occurrence_type="new",
            severity="warning",
            detected_at=now,
            last_seen_at=now,
        )
        self.db.commit()

        jobs = enqueue_due_ai_diagnoses(self.db, limit=4)

        self.assertEqual(
            [job.case_id for job in jobs],
            [new_high_fresh.id, reopened_high_older.id, new_warning.id, baseline_critical.id],
        )
        stale_events = list(
            self.db.scalars(
                select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_stale_backfill_queued")
            ).all()
        )
        self.assertEqual([event.case_id for event in stale_events], [baseline_critical.id])

    def test_ignored_case_reopens_on_evidence_change_before_expiry(self):
        snapshot = self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        case.status = "ignored"
        case.ignored_until = datetime.now(timezone.utc) + timedelta(days=7)
        cycle = case.occurrence_cycle
        snapshot.stock_qty = Decimal("-9")
        self.db.commit()

        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertEqual(case.status, "open")
        self.assertEqual(case.occurrence_type, "reopened")
        self.assertEqual(case.occurrence_cycle, cycle + 1)
        self.assertIsNone(case.ignored_until)

    def test_rule_version_participates_in_evidence_hash(self):
        self._negative_snapshot()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        original_version = case.evidence_version

        with patch.dict(
            "app.services.exception_center_service.CALIBRATED_RULE_VERSIONS",
            {"inventory.negative_stock": "2026-07-28.v3"},
        ):
            run_full_exception_scan(self.db)
            self.db.commit()
        self.db.refresh(case)
        evidence = self.db.scalar(
            select(ExceptionEvidence)
            .where(ExceptionEvidence.case_id == case.id, ExceptionEvidence.evidence_version == case.evidence_version)
        )
        self.assertNotEqual(case.evidence_version, original_version)
        self.assertEqual(case.rule_version, "2026-07-28.v3")
        self.assertEqual(evidence.data_json["rule_version"], "2026-07-28.v3")

    def test_inventory_flow_missing_warehouse_is_aggregated_and_linked_to_source_date(self):
        self.db.add_all(
            [
                InventoryFlowLedger(
                    data_date=date(2026, 7, 28),
                    warehouse_name=warehouse,
                    warehouse_scope="unknown",
                    product_code=f"FLOW-{index}",
                    purchase_qty=Decimal("0"),
                    sales_qty=Decimal("1"),
                    anomaly_type="sales_without_stock",
                    source_batch_ids=[],
                )
                for index, warehouse in enumerate(("-", "-"), start=1)
            ]
        )
        self.db.commit()
        sync_exception_cases(self.db, domains={"inventory"})
        self.db.commit()

        cases = list(
            self.db.scalars(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory_flow.warehouse_missing")).all()
        )
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].affected_rows, 2)
        self.assertEqual(cases[0].severity, "warning")
        query = parse_qs(urlsplit(cases[0].action_path).query)
        self.assertEqual(query["date_from"], ["2026-07-28"])
        self.assertEqual(query["date_to"], ["2026-07-28"])
        self.assertEqual(query["warehouse_name"], ["-"])
        self.assertNotIn("anomaly_type", query)

    def test_snapshot_missing_warehouse_is_one_bounded_batch_warning(self):
        batch = self._inventory_batch("INV-MISSING-WAREHOUSE")
        snapshots = [
            InventorySnapshot(
                batch_id=batch.id,
                row_number=index,
                data_date=batch.data_date,
                product_code=f"MISSING-WH-{index:03d}",
                product_name=f"Missing warehouse {index:03d}",
                warehouse_name="-",
                warehouse_scope="unknown",
                unit_relation="1:1",
                stock_qty=Decimal("1"),
                locked_base_qty=Decimal("0"),
                raw_row_json={},
            )
            for index in range(1, 56)
        ]
        batch.total_rows = len(snapshots)
        batch.success_rows = len(snapshots)
        self.db.add_all(snapshots)
        self.db.commit()

        sync_exception_cases(self.db, domains={"inventory"})
        self.db.commit()
        cases = list(
            self.db.scalars(
                select(ExceptionCase).where(ExceptionCase.rule_code == "inventory_snapshot.warehouse_missing")
            ).all()
        )
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case.severity, "warning")
        self.assertEqual(case.resource_type, "inventory_snapshot_batch")
        self.assertEqual(case.resource_id, str(batch.id))
        self.assertEqual(case.affected_rows, 55)
        self.assertEqual(self.db.query(ExceptionNotification).filter_by(case_id=case.id).count(), 0)

        evidence = self.db.scalar(
            select(ExceptionEvidence).where(
                ExceptionEvidence.case_id == case.id,
                ExceptionEvidence.evidence_version == case.evidence_version,
            )
        )
        evidence_rows = evidence.data_json["rows"]
        self.assertEqual(evidence_rows["total"], 55)
        self.assertEqual(len(evidence_rows["sample"]), 50)
        self.assertTrue(evidence_rows["truncated"])
        original_sample = evidence_rows["sample"]
        original_digest = evidence_rows["digest"]
        original_version = case.evidence_version

        snapshots[-1].product_name = "Changed outside retained sample"
        self.db.commit()
        sync_exception_cases(self.db, domains={"inventory"})
        self.db.commit()
        self.db.refresh(case)
        updated_evidence = self.db.scalar(
            select(ExceptionEvidence).where(
                ExceptionEvidence.case_id == case.id,
                ExceptionEvidence.evidence_version == case.evidence_version,
            )
        )
        self.assertNotEqual(case.evidence_version, original_version)
        self.assertEqual(updated_evidence.data_json["rows"]["sample"], original_sample)
        self.assertNotEqual(updated_evidence.data_json["rows"]["digest"], original_digest)


if __name__ == "__main__":
    unittest.main()
