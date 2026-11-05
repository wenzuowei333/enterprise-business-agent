import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.exceptions import router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import (
    ExceptionCase,
    ExceptionEvidence,
    ExceptionDiagnosisJob,
    ExceptionEvent,
    ExceptionPolicy,
    CustomerMaster,
    DataScopeRule,
    DataCalendarRule,
    ImportBatch,
    ImportError,
    InventoryFlowLedger,
    InventoryCheckBatch,
    InventoryCheckResult,
    InventorySnapshot,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.services.exception_center_service import (
    _alert_candidate,
    _action_path,
    run_full_exception_scan,
    run_incremental_exception_scan,
    sync_exception_cases,
    scoped_exception_stmt,
    serialize_case,
    summary_for_cases,
    execute_action,
    configured_exception_action_types,
    validate_action,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ExceptionCenterTest(unittest.TestCase):
    def setUp(self):
        self.actions_enabled_patch = patch(
            "app.services.exception_center_service.settings.exception_actions_enabled",
            True,
        )
        self.actions_enabled_patch.start()
        self.addCleanup(self.actions_enabled_patch.stop)
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.admin_role = Role(role_code="admin", role_name="Admin")
        self.limited_role = Role(role_code="limited", role_name="Limited")
        self.db.add_all([self.admin_role, self.limited_role])
        self.db.flush()
        self.admin = User(
            username="exception-admin",
            password_hash="hash",
            real_name="Exception Admin",
            role="admin",
            status="active",
            is_active=True,
        )
        self.limited = User(
            username="exception-limited",
            password_hash="hash",
            real_name="Exception Limited",
            role="limited",
            status="active",
            is_active=True,
        )
        self.db.add_all([self.admin, self.limited])
        self.db.flush()
        self._grant(self.admin_role, "exception_center.view")
        self._grant(self.admin_role, "exception_center.diagnose")
        self._grant(self.admin_role, "exception_center.manage")
        self._grant(self.admin_role, "exception_center.action_execute")
        self._grant(self.admin_role, "exception_center.policy_manage")
        self._grant(self.admin_role, "inventory_snapshot.view")
        self._grant(self.admin_role, "inventory_check.view")
        self._grant(self.admin_role, "inventory_check.upload")
        self._grant(self.admin_role, "import.view")
        self._grant(self.admin_role, "import.commit")
        self._grant(self.admin_role, "receivable.view")
        self._grant(self.admin_role, "receivable.check")
        self._grant(self.admin_role, "customer.view")
        self._grant(self.admin_role, "supplier.view")
        self._grant(self.admin_role, "product.view")
        self._grant(self.limited_role, "exception_center.view")
        self.db.add(
            ExceptionPolicy(
                policy_key="default",
                is_enabled=True,
                manual_ai_enabled=True,
                scheduled_ai_enabled=False,
                full_scan_enabled=False,
                digest_enabled=False,
                full_scan_cron="30 2 * * *",
                digest_cron="30 8 * * *",
                ai_daily_limit=100,
                ai_batch_limit=50,
                manual_ai_daily_limit=100,
                scheduled_ai_daily_limit=0,
                scheduled_ai_batch_limit=20,
                ai_concurrency=1,
                stale_diagnosis_hours=24,
            )
        )
        self.db.commit()

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.admin.username)}"}

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _grant(self, role: Role, code: str) -> None:
        permission = self.db.scalar(select(Permission).where(Permission.permission_code == code))
        if permission is None:
            permission = Permission(
                permission_code=code,
                permission_name=code,
                resource_type=code.split(".")[0],
                action_type=code.split(".")[-1],
            )
            self.db.add(permission)
            self.db.flush()
        self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))

    def _seed_negative_inventory(self) -> InventorySnapshot:
        batch = ImportBatch(
            batch_no="INV-EXCEPTION",
            file_name="inventory.xlsx",
            file_type="inventory_snapshot",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc),
            status="committed",
            total_rows=1,
            success_rows=1,
            error_rows=0,
            raw_file_path="inventory.xlsx",
        )
        self.db.add(batch)
        self.db.flush()
        snapshot = InventorySnapshot(
            batch_id=batch.id,
            row_number=1,
            data_date=batch.data_date,
            product_code="NEG-001",
            product_name="Negative stock",
            warehouse_name="Main",
            warehouse_scope="specific",
            stock_qty=Decimal("-5"),
            locked_base_qty=Decimal("0"),
            raw_row_json={},
        )
        self.db.add(snapshot)
        self.db.commit()
        return snapshot

    def assert_action_path(self, action_path: str, expected_path: str, expected_query: dict[str, str]) -> None:
        parsed = urlsplit(action_path)
        self.assertEqual(parsed.path, expected_path)
        self.assertEqual(parse_qs(parsed.query), {key: [value] for key, value in expected_query.items()})

    def test_scan_creates_stable_case_evidence_and_reopens(self):
        snapshot = self._seed_negative_inventory()
        first = run_full_exception_scan(self.db)
        self.db.commit()
        self.assertGreaterEqual(first["created"], 1)
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        self.assertIsNotNone(case)
        self.assertEqual(case.severity, "critical")
        self.assertEqual(case.status, "open")
        self.assertTrue(case.action_path.startswith("/inventory?attention_state=needs_attention"))
        evidence = self.db.scalar(select(ExceptionEvidence).where(ExceptionEvidence.case_id == case.id))
        self.assertEqual(evidence.data_json["product"]["code"], "NEG-001")
        original_case_no = case.case_no

        snapshot.stock_qty = Decimal("5")
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertEqual(case.status, "resolved")

        snapshot.stock_qty = Decimal("-7")
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertEqual(case.case_no, original_case_no)
        self.assertEqual(case.status, "open")
        self.assertEqual(case.affected_quantity, Decimal("-7"))

    def test_import_error_becomes_case_and_metadata_is_serialized(self):
        batch = ImportBatch(
            batch_no="FAILED-IMPORT",
            file_name="bad.xlsx",
            file_type="sales_detail",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc),
            status="failed",
            total_rows=3,
            success_rows=1,
            error_rows=2,
            raw_file_path="bad.xlsx",
        )
        self.db.add(batch)
        self.db.flush()
        self.db.add(ImportError(batch_id=batch.id, row_number=2, error_type="invalid_number", error_message="Quantity is invalid"))
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "import.batch_failed"))
        payload = serialize_case(self.db, case)
        self.assertEqual(payload["metadata"]["file_type"], "sales_detail")
        self.assertNotIn("metadata_json", payload)
        self.assertEqual(case.source_batch_kind, "import")
        self.assertEqual(payload["source_batch_kind"], "import")
        self.assertEqual(case.source_batch_id, batch.id)
        self.assertEqual(case.action_path, f"/imports?batch={batch.id}&tab=history")

    def test_identical_import_content_creates_stable_warning_against_earlier_committed_batch(self):
        content_sha256 = "a" * 64
        original = ImportBatch(
            batch_no="ORIGINAL-IMPORT",
            file_name="original.xlsx",
            file_type="sales_detail",
            data_date=date(2026, 7, 27),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc) - timedelta(hours=1),
            status="committed",
            total_rows=10,
            success_rows=10,
            error_rows=0,
            raw_file_path="original.xlsx",
            content_sha256=content_sha256,
        )
        duplicate = ImportBatch(
            batch_no="DUPLICATE-IMPORT",
            file_name="renamed-copy.xlsx",
            file_type="sales_detail",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc),
            status="uploaded",
            total_rows=10,
            success_rows=0,
            error_rows=0,
            raw_file_path="renamed-copy.xlsx",
            content_sha256=content_sha256,
        )
        self.db.add_all([original, duplicate])
        self.db.commit()

        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(
            select(ExceptionCase).where(
                ExceptionCase.rule_code == "import.duplicate_content",
                ExceptionCase.source_batch_id == duplicate.id,
            )
        )
        self.assertIsNotNone(case)
        self.assertEqual(case.severity, "warning")
        self.assertEqual(case.resource_code, duplicate.batch_no)
        evidence = self.db.scalar(select(ExceptionEvidence).where(ExceptionEvidence.case_id == case.id))
        self.assertEqual(evidence.data_json["original_batch"]["id"], original.id)
        self.assertEqual(evidence.data_json["duplicate_batch"]["id"], duplicate.id)
        self.assertEqual(evidence.data_json["content_sha256"], content_sha256)

        duplicate.content_sha256 = "b" * 64
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertEqual(case.status, "resolved")

    def test_daily_required_data_creates_one_stable_freshness_case(self):
        self.db.add(
            DataCalendarRule(
                rule_code="daily-sales",
                file_type="sales_detail",
                label="Sales detail",
                action_layer="blue",
                frequency="daily",
                deadline_hour=18,
                owner_role="Data",
                is_required=True,
                is_enabled=True,
                sort_order=1,
            )
        )
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "import.data_stale"))
        self.assertIsNotNone(case)
        case_no = case.case_no
        run_full_exception_scan(self.db)
        self.db.commit()
        cases = list(self.db.scalars(select(ExceptionCase).where(ExceptionCase.rule_code == "import.data_stale")).all())
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].case_no, case_no)

    def test_latest_inventory_flow_anomaly_is_scanned_with_calculation_evidence(self):
        self.db.add(
            InventoryFlowLedger(
                data_date=date(2026, 7, 28),
                warehouse_name="Main",
                warehouse_scope="specific",
                product_code="FLOW-001",
                product_name="Flow product",
                opening_stock_qty=Decimal("10"),
                purchase_qty=Decimal("2"),
                sales_qty=Decimal("3"),
                calculated_closing_qty=Decimal("9"),
                snapshot_stock_qty=Decimal("7"),
                diff_qty=Decimal("2"),
                anomaly_type="closing_mismatch",
                anomaly_flags=["closing_mismatch"],
                source_batch_ids=[],
                source_counts={"sales": 1, "purchase": 1},
            )
        )
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory_flow.closing_mismatch"))
        self.assertIsNotNone(case)
        self.assertEqual(case.severity, "high")
        evidence = self.db.scalar(select(ExceptionEvidence).where(ExceptionEvidence.case_id == case.id))
        self.assertEqual(evidence.data_json["calculation"]["diff_qty"], "2.0000")
        self.assert_action_path(
            case.action_path,
            "/inventory",
            {
                "tab": "check",
                "check_tab": "flow",
                "product_code": "FLOW-001",
                "warehouse_name": "Main",
                "anomaly_type": "closing_mismatch",
            },
        )

    def test_summary_does_not_leak_cases_without_source_permission(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        self.assertGreater(summary_for_cases(self.db, self.admin)["total"], 0)
        limited_summary = summary_for_cases(self.db, self.limited)
        self.assertEqual(limited_summary["total"], 0)
        self.assertEqual(limited_summary["by_domain"], {})

    def test_summary_exposes_independent_ai_and_action_capabilities(self):
        with (
            patch("app.services.exception_center_service.settings.exception_ai_enabled", True),
            patch("app.services.exception_center_service.settings.exception_actions_enabled", False),
        ):
            summary = summary_for_cases(self.db, self.admin)

        self.assertIs(summary["ai_enabled"], True)
        self.assertIs(summary["manual_ai_enabled"], True)
        self.assertIs(summary["scheduled_ai_enabled"], False)
        self.assertIs(summary["full_scan_enabled"], False)
        self.assertIs(summary["digest_enabled"], False)
        self.assertIs(summary["actions_enabled"], False)

    def test_inventory_check_cases_require_inventory_check_permission(self):
        self._grant(self.limited_role, "inventory_snapshot.view")
        batch = InventoryCheckBatch(
            batch_no="CHECK-SCOPE",
            file_name="check.xlsx",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            status="completed",
            total_rows=1,
            difference_rows=1,
            raw_file_path="check.xlsx",
        )
        self.db.add(batch)
        self.db.flush()
        self.db.add(
            InventoryCheckResult(
                batch_id=batch.id,
                result_type="quantity_mismatch",
                product_code="CHECK-001",
                product_name="Check product",
                warehouse_name="Main",
                platform_stock_qty=Decimal("3"),
                system_stock_qty=Decimal("1"),
                diff_qty=Decimal("2"),
            )
        )
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.source_type == "inventory_check_result"))
        self.assertEqual(case.source_batch_kind, "inventory_check")
        self.assert_action_path(
            case.action_path,
            "/inventory",
            {
                "tab": "check",
                "batch_id": str(batch.id),
                "result_type": "quantity_mismatch",
                "q": "CHECK-001",
            },
        )
        visible_before = list(self.db.scalars(scoped_exception_stmt(self.db, self.limited)).all())
        self.assertNotIn("inventory_check_result", {case.source_type for case in visible_before})
        self._grant(self.limited_role, "inventory_check.view")
        self.db.commit()
        visible_after = list(self.db.scalars(scoped_exception_stmt(self.db, self.limited)).all())
        self.assertIn("inventory_check_result", {case.source_type for case in visible_after})

    def test_non_customer_source_scopes_apply_custom_none_and_assigned_as_source_queries_do(self):
        for permission in ("inventory_snapshot.view", "product.view", "supplier.view", "import.view"):
            self._grant(self.limited_role, permission)

        cases = []
        definitions = (
            ("inventory", "inventory_snapshot", "inventory_anomaly_case", "INV"),
            ("master_data", "product", "product_master", "PROD"),
            ("master_data", "supplier", "supplier_master", "SUP"),
            ("import", "import_batch", "import_batch", "BATCH"),
        )
        for domain, resource_type, source_type, prefix in definitions:
            for suffix in ("ALLOWED", "HIDDEN"):
                code = f"{prefix}-{suffix}"
                cases.append(
                    ExceptionCase(
                        case_no=f"EXC-SCOPE-{code}",
                        fingerprint=f"scope-{code}",
                        domain=domain,
                        rule_code=f"scope.{resource_type}",
                        title=code,
                        severity="warning",
                        status="open",
                        resource_type=resource_type,
                        resource_id=code,
                        resource_code=code,
                        resource_name=code,
                        source_type=source_type,
                        source_id=code,
                        evidence_version="scope-v1",
                        reason="scope regression",
                    )
                )
        self.db.add_all(cases)
        rules = [
            DataScopeRule(
                subject_type="user",
                subject_id=str(self.limited.id),
                resource_type=resource_type,
                scope_mode="custom",
                scope_value={"mode": "none"},
            )
            for resource_type in ("inventory_snapshot", "product", "supplier", "import_batch")
        ]
        self.db.add_all(rules)
        self.db.commit()

        self.assertEqual(list(self.db.scalars(scoped_exception_stmt(self.db, self.limited)).all()), [])

        for rule in rules:
            rule.scope_mode = "assigned"
            rule.scope_value = {"values": [f"{rule.resource_type}-ALLOWED"]}
        self.db.commit()

        visible = list(self.db.scalars(scoped_exception_stmt(self.db, self.limited)).all())
        self.assertEqual(visible, [])

        for scope_mode, scope_value in (
            ("own", None),
            ("department", {"values": ["Sales"]}),
            ("custom", {"mode": "territory", "values": ["South"]}),
        ):
            for rule in rules:
                rule.scope_mode = scope_mode
                rule.scope_value = scope_value
            self.db.commit()
            with self.subTest(scope_mode=scope_mode):
                self.assertEqual(
                    list(self.db.scalars(scoped_exception_stmt(self.db, self.limited)).all()),
                    [],
                )

    def test_customer_own_scope_without_employee_code_matches_unassigned_source_rows(self):
        self._grant(self.limited_role, "customer.view")
        customer = CustomerMaster(
            customer_code="CUS-UNASSIGNED",
            customer_name="Unassigned customer",
            status="active",
            salesperson_employee_code=None,
        )
        case = ExceptionCase(
            case_no="EXC-SCOPE-CUS-UNASSIGNED",
            fingerprint="scope-CUS-UNASSIGNED",
            domain="master_data",
            rule_code="scope.customer",
            title="Unassigned customer",
            severity="warning",
            status="open",
            resource_type="customer",
            resource_id="CUS-UNASSIGNED",
            resource_code="CUS-UNASSIGNED",
            resource_name="Unassigned customer",
            source_type="customer_master",
            source_id="CUS-UNASSIGNED",
            evidence_version="scope-v1",
            reason="scope regression",
        )
        self.db.add_all(
            [
                customer,
                case,
                DataScopeRule(
                    subject_type="user",
                    subject_id=str(self.limited.id),
                    resource_type="customer",
                    scope_mode="own",
                    scope_value=None,
                ),
            ]
        )
        self.db.commit()

        visible = list(self.db.scalars(scoped_exception_stmt(self.db, self.limited)).all())
        self.assertEqual([item.case_no for item in visible], [case.case_no])

    def test_unmappable_customer_scope_modes_fail_closed(self):
        self._grant(self.limited_role, "customer.view")
        customer = CustomerMaster(
            customer_code="CUS-SCOPE-CLOSED",
            customer_name="Scoped customer",
            status="active",
            salesperson_employee_code="EMP-1",
        )
        case = ExceptionCase(
            case_no="EXC-SCOPE-CUS-CLOSED",
            fingerprint="scope-CUS-CLOSED",
            domain="master_data",
            rule_code="scope.customer.closed",
            title="Scoped customer",
            severity="warning",
            status="open",
            resource_type="customer",
            resource_id=customer.customer_code,
            resource_code=customer.customer_code,
            resource_name=customer.customer_name,
            source_type="customer_master",
            source_id=customer.customer_code,
            evidence_version="scope-v1",
            reason="scope regression",
        )
        rule = DataScopeRule(
            subject_type="user",
            subject_id=str(self.limited.id),
            resource_type="customer",
            scope_mode="department",
            scope_value={"values": ["Sales"]},
        )
        self.db.add_all([customer, case, rule])
        self.db.commit()

        self.assertEqual(list(self.db.scalars(scoped_exception_stmt(self.db, self.limited)).all()), [])
        rule.scope_mode = "custom"
        rule.scope_value = {"mode": "territory", "values": ["South"]}
        self.db.commit()
        self.assertEqual(list(self.db.scalars(scoped_exception_stmt(self.db, self.limited)).all()), [])

    def test_incremental_scan_rejects_untyped_or_invalid_batch_references(self):
        for payload in (
            {"domains": ["import"], "source_batch_id": 9},
            {"domains": ["import"], "source_batch_kind": "import"},
            {"domains": ["import"], "source_batch_kind": "unknown", "source_batch_id": 9},
            {"domains": ["import"], "source_batch_kind": "import", "source_batch_id": 0},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                run_incremental_exception_scan(self.db, payload)

    def test_snapshot_quality_path_does_not_apply_attention_filter(self):
        snapshot = self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(
            select(ExceptionCase).where(
                ExceptionCase.source_type == "inventory_snapshot_quality",
                ExceptionCase.resource_id == str(snapshot.id),
            )
        )
        self.assertIsNotNone(case)
        self.assert_action_path(
            case.action_path,
            "/inventory",
            {"batch_id": str(snapshot.batch_id), "product_code": "NEG-001"},
        )
        self.assertNotIn("attention_state", parse_qs(urlsplit(case.action_path).query))

    def test_data_quality_action_paths_open_exact_source_records(self):
        examples = (
            ("customer", "customers", "CUS 001"),
            ("supplier", "suppliers", "SUP/001"),
            ("product", "products", "PROD+001"),
        )
        for resource_type, kind, code in examples:
            with self.subTest(resource_type=resource_type):
                action_path = _action_path("master_data", {"resource_type": resource_type, "code": code})
                self.assert_action_path(action_path, "/master-data", {"kind": kind, "open": code})

        receivable_path = _action_path(
            "receivable",
            {
                "code": "CUS 001",
                "metadata": {"result_type": "amount_mismatch"},
            },
        )
        self.assert_action_path(
            receivable_path,
            "/account-balance",
            {"tab": "check", "q": "CUS 001", "result_type": "amount_mismatch"},
        )

    def test_risk_case_fingerprint_is_stable_across_batches(self):
        alert = {
            "rule_code": "check.receivable_amount_mismatch",
            "rule_name": "应收金额不一致",
            "resource_type": "settlement_unit",
            "code": "CUS-001",
            "name": "测试客户",
            "source": "latest_receivable_check",
            "metadata": {"batch_id": 101, "result_type": "amount_mismatch"},
        }
        first = _alert_candidate(alert)
        second = _alert_candidate({**alert, "metadata": {**alert["metadata"], "batch_id": 102}})

        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertNotEqual(first["evidence"], second["evidence"])

    def test_inventory_risk_fingerprint_keeps_warehouse_identity(self):
        alert = {
            "rule_code": "check.inventory_missing_product_master",
            "rule_name": "库存核验商品档案待补",
            "resource_type": "product",
            "code": "P-001",
            "name": "测试商品",
            "source": "latest_inventory_check",
            "metadata": {"batch_id": 101, "warehouse_name": "一号仓"},
        }
        first = _alert_candidate(alert)
        second = _alert_candidate({**alert, "metadata": {**alert["metadata"], "warehouse_name": "二号仓"}})

        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_master_data_case_closes_after_customer_is_completed(self):
        customer = CustomerMaster(customer_code="CUS-MISSING", customer_name="Missing customer", status="active")
        self.db.add(customer)
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(
            select(ExceptionCase).where(
                ExceptionCase.rule_code == "master_completeness.customer",
                ExceptionCase.resource_code == customer.customer_code,
            )
        )
        self.assertEqual(case.status, "open")
        customer.salesperson_name = "Sales"
        customer.contact_name = "Contact"
        customer.contact_phone = "13800000000"
        customer.address = "Address"
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertEqual(case.status, "resolved")

    def test_feature_gate_and_list_api(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", False):
            response = self.client.get("/api/v1/exceptions/summary", headers=self.headers)
            self.assertEqual(response.status_code, 404)
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.get("/api/v1/exceptions/page?domain=inventory", headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertGreaterEqual(response.json()["total"], 1)
            self.assertEqual(response.json()["items"][0]["domain"], "inventory")

    def test_notification_read_and_acknowledgement_are_independent(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            listed = self.client.get("/api/v1/exception-notifications", headers=self.headers)
            self.assertEqual(listed.status_code, 200, listed.text)
            notification = listed.json()[0]
            self.assertFalse(notification["is_read"])
            self.assertIsNone(notification["acknowledged_at"])

            read = self.client.post(
                f"/api/v1/exception-notifications/{notification['id']}/read",
                headers=self.headers,
            )
            self.assertEqual(read.status_code, 200, read.text)
            self.assertTrue(read.json()["is_read"])
            self.assertIsNone(read.json()["acknowledged_at"])

            acknowledged = self.client.post(
                f"/api/v1/exception-notifications/{notification['id']}/acknowledge",
                headers=self.headers,
            )
            self.assertEqual(acknowledged.status_code, 200, acknowledged.text)
            self.assertTrue(acknowledged.json()["is_read"])
            self.assertIsNotNone(acknowledged.json()["acknowledged_at"])

    def test_ai_and_action_feature_gates(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", False),
        ):
            response = self.client.post(f"/api/v1/exceptions/{case.case_no}/diagnoses", json={}, headers=self.headers)
            self.assertEqual(response.status_code, 503)
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_actions_enabled", False),
        ):
            response = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/actions/validate",
                json={"action_type": "rebuild_inventory_flow", "parameters": {}},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 503)

    def test_action_service_layer_feature_gate(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))

        with patch("app.services.exception_center_service.settings.exception_actions_enabled", False):
            with self.assertRaises(HTTPException) as raised:
                validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)

        self.assertEqual(raised.exception.status_code, 503)

    def test_action_request_schema_rejects_unsafe_values(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            invalid_validation = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/actions/validate",
                json={"action_type": "rebuild_inventory_flow", "parameters": {"command": "drop"}},
                headers=self.headers,
            )
            invalid_batch = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/actions/validate",
                json={"action_type": "rebuild_inventory_flow", "parameters": {"batch_id": 0}},
                headers=self.headers,
            )
            invalid_execute = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/actions",
                json={"validation_token": "unsafe token with spaces", "idempotency_key": "unsafe\nkey"},
                headers=self.headers,
            )

        self.assertEqual(invalid_validation.status_code, 422)
        self.assertEqual(invalid_batch.status_code, 422)
        self.assertEqual(invalid_execute.status_code, 422)

    def test_action_policy_can_narrow_release_action_allowlist(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        policy = self.db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
        policy.settings_json = {
            "allowed_action_types": [
                "rebuild_inventory_flow",
                "rerun_inventory_check",
                "rebuild_master_link_issues",
            ]
        }
        self.db.commit()

        self.assertEqual(
            configured_exception_action_types(self.db),
            frozenset({"rebuild_inventory_flow", "rerun_inventory_check", "rebuild_master_link_issues"}),
        )
        blocked, _token = validate_action(self.db, case, "rebuild_receivable_checks", {}, self.admin)
        self.assertFalse(blocked.allowed)
        self.assertIn("action_disabled_by_policy", blocked.blockers_json)
        blocked_import, _token = validate_action(self.db, case, "revalidate_import_batch", {}, self.admin)
        self.assertFalse(blocked_import.allowed)
        self.assertIn("action_disabled_by_policy", blocked_import.blockers_json)

    def test_manual_diagnosis_refreshes_evidence_before_queueing(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
            patch(
                "app.api.routes.exceptions.sync_exception_cases",
                wraps=sync_exception_cases,
            ) as refresh,
        ):
            response = self.client.post(f"/api/v1/exceptions/{case.case_no}/diagnoses", json={}, headers=self.headers)

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["evidence_version"], case.evidence_version)
        self.assertEqual(refresh.call_args.kwargs["target_fingerprint"], case.fingerprint)

    def test_manual_diagnosis_stops_when_refresh_resolves_case(self):
        snapshot = self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        snapshot.stock_qty = Decimal("2")
        self.db.commit()

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
        ):
            response = self.client.post(f"/api/v1/exceptions/{case.case_no}/diagnoses", json={}, headers=self.headers)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["error_code"], "exception_already_resolved")
        self.db.refresh(case)
        self.assertEqual(case.status, "resolved")

    def test_manual_policy_gate_and_budget_do_not_create_jobs(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        policy = self.db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))

        policy.manual_ai_enabled = False
        self.db.commit()
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
        ):
            disabled = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/diagnoses",
                json={},
                headers=self.headers,
            )
        self.assertEqual(disabled.status_code, 503, disabled.text)
        self.assertEqual(disabled.json()["detail"]["error_code"], "exception_manual_ai_disabled")
        self.assertEqual(self.db.scalar(select(func.count(ExceptionDiagnosisJob.id))), 0)

        policy.manual_ai_enabled = True
        policy.manual_ai_daily_limit = 0
        self.db.commit()
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
        ):
            unlimited = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/diagnoses",
                json={},
                headers=self.headers,
            )
        self.assertEqual(unlimited.status_code, 202, unlimited.text)
        self.assertEqual(self.db.scalar(select(func.count(ExceptionDiagnosisJob.id))), 1)

    def test_detail_exposes_active_job_and_manual_processing_kind(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
        ):
            queued = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/diagnoses",
                json={},
                headers=self.headers,
            )
            detail = self.client.get(f"/api/v1/exceptions/{case.case_no}", headers=self.headers)
            jobs = self.client.get("/api/v1/exception-jobs/page?job_kind=diagnosis", headers=self.headers)

        self.assertEqual(queued.status_code, 202, queued.text)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(jobs.status_code, 200, jobs.text)
        self.assertEqual(detail.json()["processing_kind"], "manual_diagnosis")
        self.assertEqual(detail.json()["active_diagnosis_job"]["job_no"], queued.json()["job_no"])
        self.assertEqual(jobs.json()["items"][0]["job_no"], queued.json()["job_no"])

    def test_diagnose_permission_can_request_and_read_own_case_job_but_not_global_queue(self):
        role = Role(role_code="diagnosis-operator", role_name="Diagnosis operator")
        self.db.add(role)
        self.db.flush()
        operator = User(
            username="diagnosis-operator",
            password_hash="hash",
            real_name="Diagnosis Operator",
            role=role.role_code,
            status="active",
            is_active=True,
        )
        self.db.add(operator)
        self.db.flush()
        for permission in (
            "exception_center.view",
            "exception_center.diagnose",
            "inventory_snapshot.view",
        ):
            self._grant(role, permission)
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        headers = {"Authorization": f"Bearer {create_access_token(operator.username)}"}

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
        ):
            queued = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/diagnoses",
                json={},
                headers=headers,
            )
            job_detail = self.client.get(
                f"/api/v1/exception-jobs/{queued.json()['id']}",
                headers=headers,
            ) if queued.status_code == 202 else queued
            global_queue = self.client.get("/api/v1/exception-jobs/page", headers=headers)

        self.assertEqual(queued.status_code, 202, queued.text)
        self.assertEqual(job_detail.status_code, 200, job_detail.text)
        self.assertEqual(global_queue.status_code, 403, global_queue.text)

    def test_ops_and_aggregation_routes_validate_their_public_contracts(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            ops = self.client.get("/api/v1/exception-ops/summary", headers=self.headers)
            aggregations = self.client.get(
                "/api/v1/exceptions/aggregations?group_by=rule",
                headers=self.headers,
            )

        self.assertEqual(ops.status_code, 200, ops.text)
        self.assertIn("manual_budget", ops.json())
        self.assertIn("policy", ops.json())
        self.assertEqual(aggregations.status_code, 200, aggregations.text)
        self.assertEqual(aggregations.json()["group_by"], "rule")
        self.assertGreaterEqual(len(aggregations.json()["groups"]), 1)
        self.assertIn("count", aggregations.json()["groups"][0])

    def test_aggregation_search_uses_the_same_text_predicate_as_case_page(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            matching_page = self.client.get(
                "/api/v1/exceptions/page?q=NEG-001",
                headers=self.headers,
            )
            matching_groups = self.client.get(
                "/api/v1/exceptions/aggregations?group_by=rule&q=NEG-001",
                headers=self.headers,
            )
            empty_page = self.client.get(
                "/api/v1/exceptions/page?q=definitely-not-present",
                headers=self.headers,
            )
            empty_groups = self.client.get(
                "/api/v1/exceptions/aggregations?group_by=rule&q=definitely-not-present",
                headers=self.headers,
            )

        self.assertEqual(matching_page.status_code, 200, matching_page.text)
        self.assertEqual(matching_groups.status_code, 200, matching_groups.text)
        self.assertEqual(
            sum(group["count"] for group in matching_groups.json()["groups"]),
            matching_page.json()["total"],
        )
        self.assertEqual(empty_page.json()["total"], 0)
        self.assertEqual(empty_groups.json()["groups"], [])

    def test_manual_verify_refreshes_latest_domain_data_instead_of_old_source_batch(self):
        old_snapshot = self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        old_batch_id = old_snapshot.batch_id
        self.assertEqual(case.source_batch_id, old_batch_id)

        latest_batch = ImportBatch(
            batch_no="INV-VERIFY-LATEST",
            file_name="inventory-latest.xlsx",
            file_type="inventory_snapshot",
            data_date=date(2026, 7, 29),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            status="committed",
            total_rows=1,
            success_rows=1,
            error_rows=0,
            raw_file_path="inventory-latest.xlsx",
        )
        self.db.add(latest_batch)
        self.db.flush()
        self.db.add(
            InventorySnapshot(
                batch_id=latest_batch.id,
                row_number=1,
                data_date=latest_batch.data_date,
                product_code="NEG-001",
                product_name="Negative stock",
                warehouse_name="Main",
                warehouse_scope="specific",
                stock_qty=Decimal("-8"),
                locked_base_qty=Decimal("0"),
                raw_row_json={},
            )
        )
        self.db.commit()

        expected_version = case.evidence_version
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            stale_response = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/verify",
                json={
                    "expected_evidence_version": expected_version,
                    "note": "Verify against latest committed snapshot",
                },
                headers=self.headers,
            )

        self.assertEqual(stale_response.status_code, 409, stale_response.text)
        self.assertEqual(stale_response.json()["detail"]["error_code"], "exception_evidence_version_conflict")
        self.db.refresh(case)
        self.assertEqual(case.source_batch_id, latest_batch.id)
        self.assertEqual(case.affected_quantity, Decimal("-8"))
        self.assertNotEqual(case.evidence_version, expected_version)
        self.assertEqual(
            self.db.scalar(
                select(func.count(ExceptionEvent.id)).where(
                    ExceptionEvent.event_type.in_(("verified", "verification_failed"))
                )
            ),
            0,
        )

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/verify",
                json={
                    "expected_evidence_version": case.evidence_version,
                    "note": "Verify the refreshed evidence",
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["case"]["status"], "action_required")
        self.db.refresh(case)
        self.assertEqual(case.status, "action_required")

    def test_verify_post_refresh_version_conflict_writes_no_verification_event(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        expected_version = case.evidence_version

        def change_version_during_refresh(db, **kwargs):  # noqa: ANN001, ARG001
            refreshed = db.scalar(select(ExceptionCase).where(ExceptionCase.id == case.id))
            refreshed.evidence_version = "concurrent-evidence-version"
            db.flush()
            return {"scanned": 1, "evidence_updated": 1}

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases", side_effect=change_version_during_refresh),
        ):
            response = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/verify",
                json={"expected_evidence_version": expected_version, "note": "concurrent verification"},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["current_evidence_version"], "concurrent-evidence-version")
        self.assertEqual(
            self.db.scalar(
                select(func.count(ExceptionEvent.id)).where(
                    ExceptionEvent.event_type.in_(("verified", "verification_failed"))
                )
            ),
            0,
        )

    def test_manual_verify_rejects_stale_expected_evidence_without_scanning(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        event_count = self.db.scalar(select(func.count(ExceptionEvent.id)))

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases") as scan,
        ):
            response = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/verify",
                json={"expected_evidence_version": "stale-version", "note": "stale verification"},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["error_code"], "exception_evidence_version_conflict")
        scan.assert_not_called()
        self.assertEqual(self.db.scalar(select(func.count(ExceptionEvent.id))), event_count)

    def test_manual_verify_preserves_valid_ignored_and_processing_states(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        case.status = "ignored"
        case.ignored_until = datetime.now(timezone.utc) + timedelta(days=1)
        case.resolution_note = "Approved temporary exception"
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            ignored = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/verify",
                json={
                    "expected_evidence_version": case.evidence_version,
                    "note": "Anomaly remains during the approved ignore window",
                },
                headers=self.headers,
            )

        self.assertEqual(ignored.status_code, 200, ignored.text)
        self.assertEqual(ignored.json()["case"]["status"], "ignored")
        self.db.refresh(case)
        self.assertEqual(case.status, "ignored")
        self.assertEqual(case.resolution_note, "Approved temporary exception")

        case.status = "processing"
        case.ignored_until = None
        job = ExceptionDiagnosisJob(
            job_no="EXJOB-VERIFY-PROCESSING",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="queued",
            attempts=0,
            available_at=datetime.now(timezone.utc),
        )
        self.db.add(job)
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            processing = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/verify",
                json={
                    "expected_evidence_version": case.evidence_version,
                    "note": "Anomaly remains while diagnosis is running",
                },
                headers=self.headers,
            )

        self.assertEqual(processing.status_code, 200, processing.text)
        self.assertEqual(processing.json()["case"]["status"], "processing")
        self.db.refresh(case)
        self.assertEqual(case.status, "processing")
        event = self.db.scalar(
            select(ExceptionEvent)
            .where(ExceptionEvent.case_id == case.id, ExceptionEvent.event_type == "verification_failed")
            .order_by(ExceptionEvent.id.desc())
        )
        self.assertTrue(event.detail_json["status_preserved"])

    def test_page_exposes_personal_assignment_and_no_due_date_filter(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        case.assignee_user_id = self.admin.id
        case.due_at = None
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.get(
                "/api/v1/exceptions/page?assignment=mine&sla_status=no_due_date",
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        item = next(row for row in response.json()["items"] if row["case_no"] == case.case_no)
        self.assertTrue(item["is_mine"])
        self.assertEqual(item["sla_status"], "no_due_date")

    def test_policy_roundtrip_persists_phase_three_switches_and_budgets(self):
        payload = {
            "is_enabled": True,
            "manual_ai_enabled": True,
            "scheduled_ai_enabled": True,
            "full_scan_enabled": True,
            "digest_enabled": True,
            "full_scan_cron": "15 3 * * *",
            "digest_cron": "45 8 * * *",
            "ai_daily_limit": 75,
            "ai_batch_limit": 30,
            "manual_ai_daily_limit": 25,
            "scheduled_ai_daily_limit": 10,
            "scheduled_ai_batch_limit": 7,
            "ai_concurrency": 2,
            "stale_diagnosis_hours": 12,
            "settings": {"sla_hours": {"critical": 2}},
        }
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            updated = self.client.put("/api/v1/exception-policies", json=payload, headers=self.headers)
            loaded = self.client.get("/api/v1/exception-policies", headers=self.headers)

        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(loaded.status_code, 200, loaded.text)
        for field, expected in payload.items():
            if field == "settings":
                expected = {
                    **expected,
                    "domain_modes": {"crm": "off", "approval": "off"},
                }
            self.assertEqual(updated.json()[field], expected)
            self.assertEqual(loaded.json()[field], expected)

    def test_policy_rejects_invalid_cron(self):
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.put(
                "/api/v1/exception-policies",
                json={
                    "is_enabled": True,
                    "full_scan_cron": "not a cron",
                    "digest_cron": "30 8 * * *",
                    "ai_daily_limit": 100,
                    "ai_batch_limit": 50,
                    "ai_concurrency": 2,
                    "stale_diagnosis_hours": 24,
                    "settings": {},
                },
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 422)

    def test_assign_rejects_user_without_source_access(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.post(
                f"/api/v1/exceptions/{case.case_no}/assign",
                json={"assignee_user_id": self.limited.id},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 400)

    def test_inventory_check_action_requires_explicit_check_batch_for_snapshot_case(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        action, _token = validate_action(self.db, case, "rerun_inventory_check", {}, self.admin)
        self.assertFalse(action.allowed)
        self.assertIn("batch_id_required", action.blockers_json)
        self.assertIn("batch_kind_incompatible", action.blockers_json)

    def test_action_validation_rejects_batch_id_from_another_case(self):
        snapshot = self._seed_negative_inventory()
        other_batch = ImportBatch(
            batch_no="INV-OTHER-BATCH",
            file_name="other-inventory.xlsx",
            file_type="inventory_snapshot",
            data_date=date(2026, 7, 27),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc) - timedelta(days=1),
            status="committed",
            total_rows=1,
            success_rows=1,
            error_rows=0,
            raw_file_path="other-inventory.xlsx",
        )
        self.db.add(other_batch)
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))

        action, _token = validate_action(
            self.db,
            case,
            "rebuild_inventory_flow",
            {"batch_id": other_batch.id},
            self.admin,
        )

        self.assertFalse(action.allowed)
        self.assertIn("batch_id_mismatch", action.blockers_json)
        self.assertEqual(action.impact_json["batch_id"], snapshot.batch_id)
        self.assertEqual(action.impact_json["source_batch_kind"], "import")
        self.assertEqual(action.impact_json["scope"], "global_derived_inventory")

    def test_batch_required_action_cannot_target_arbitrary_batch_for_unbatched_case(self):
        batch = ImportBatch(
            batch_no="IMPORT-UNRELATED",
            file_name="unrelated.xlsx",
            file_type="sales_detail",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc),
            status="uploaded",
            total_rows=1,
            success_rows=0,
            error_rows=0,
            raw_file_path="unrelated.xlsx",
        )
        case = ExceptionCase(
            case_no="EXC-UNBATCHED",
            fingerprint="unbatched-action-case",
            domain="import",
            rule_code="import.data_stale",
            title="Unbatched import issue",
            severity="warning",
            status="open",
            occurrence_type="new",
            occurrence_cycle=1,
            rule_version="test-v1",
            source_type="data_calendar_rule",
            source_batch_id=None,
            evidence_version="unbatched-v1",
            reason="No source batch is associated with this case",
        )
        self.db.add_all([batch, case])
        self.db.commit()

        action, _token = validate_action(
            self.db,
            case,
            "revalidate_import_batch",
            {"batch_id": batch.id},
            self.admin,
        )

        self.assertFalse(action.allowed)
        self.assertIn("batch_id_mismatch", action.blockers_json)
        self.assertIn("batch_id_required", action.blockers_json)
        self.assertIsNone(action.impact_json["batch_id"])

    def test_global_rebuild_action_is_blocked_without_case_source_batch(self):
        case = ExceptionCase(
            case_no="EXC-UNBATCHED-MASTER",
            fingerprint="unbatched-master-action-case",
            domain="master_data",
            rule_code="master_data.unlinked_product",
            title="Unbatched master-data issue",
            severity="warning",
            status="open",
            occurrence_type="new",
            occurrence_cycle=1,
            rule_version="test-v1",
            source_type="master_link_issue",
            source_batch_id=None,
            evidence_version="unbatched-master-v1",
            reason="No source batch is associated with this case",
        )
        self.db.add(case)
        self.db.commit()

        action, _token = validate_action(self.db, case, "rebuild_master_link_issues", {}, self.admin)

        self.assertFalse(action.allowed)
        self.assertIn("source_batch_id_required", action.blockers_json)
        self.assertIsNone(action.impact_json["batch_id"])

    def test_action_is_blocked_by_newer_pending_source_import(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        self.db.add(
            ImportBatch(
                batch_no="INV-PENDING",
                file_name="pending.xlsx",
                file_type="inventory_snapshot",
                data_date=date(2026, 7, 29),
                uploaded_by=self.admin.id,
                uploaded_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                status="uploaded",
                total_rows=1,
                success_rows=0,
                error_rows=0,
                raw_file_path="pending.xlsx",
            )
        )
        self.db.commit()
        action, _token = validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)
        self.assertFalse(action.allowed)
        self.assertIn("source_import_in_progress", action.blockers_json)

    def test_committed_import_batch_cannot_be_revalidated(self):
        batch = ImportBatch(
            batch_no="IMPORT-COMMITTED",
            file_name="committed.xlsx",
            file_type="sales_detail",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc),
            status="failed",
            total_rows=1,
            success_rows=0,
            error_rows=1,
            raw_file_path="committed.xlsx",
        )
        self.db.add(batch)
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "import.batch_failed"))
        batch.status = "committed"
        self.db.commit()

        action, _token = validate_action(self.db, case, "revalidate_import_batch", {}, self.admin)

        self.assertFalse(action.allowed)
        self.assertIn("import_batch_already_committed", action.blockers_json)

    def test_revalidation_rechecks_batch_status_at_execution_time(self):
        batch = ImportBatch(
            batch_no="IMPORT-PENDING",
            file_name="pending.xlsx",
            file_type="sales_detail",
            data_date=date(2026, 7, 28),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc) - timedelta(days=2),
            status="uploaded",
            total_rows=1,
            success_rows=0,
            error_rows=0,
            raw_file_path="pending.xlsx",
        )
        self.db.add(batch)
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "import.not_committed"))
        action, token = validate_action(self.db, case, "revalidate_import_batch", {}, self.admin)
        self.assertTrue(action.allowed)
        batch.status = "committed"
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            execute_action(self.db, case, token, "import-status-race", self.admin)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(batch.status, "committed")

    def test_validation_token_is_bound_to_requesting_user(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        other = User(
            username="exception-other-admin",
            password_hash="hash",
            real_name="Other Admin",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add(other)
        self.db.commit()
        _action, token = validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)

        with self.assertRaises(HTTPException) as raised:
            execute_action(self.db, case, token, "stolen-token-key", other)

        self.assertEqual(raised.exception.status_code, 403)

    def test_action_execution_rechecks_evidence_and_pending_imports(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        _action, evidence_token = validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)
        case.evidence_version = "changed-after-validation"
        self.db.commit()

        with (
            patch("app.services.exception_center_service._acquire_exception_sync_lock") as sync_lock,
            self.assertRaises(HTTPException) as evidence_raised,
        ):
            execute_action(self.db, case, evidence_token, "changed-evidence", self.admin)
        self.assertEqual(evidence_raised.exception.status_code, 409)
        sync_lock.assert_not_called()

        case.evidence_version = "stable-evidence"
        self.db.commit()
        _action, pending_token = validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)
        self.db.add(
            ImportBatch(
                batch_no="INV-PENDING-AFTER-VALIDATION",
                file_name="pending-after-validation.xlsx",
                file_type="inventory_snapshot",
                data_date=date(2026, 7, 29),
                uploaded_by=self.admin.id,
                uploaded_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                status="uploaded",
                total_rows=1,
                success_rows=0,
                error_rows=0,
                raw_file_path="pending-after-validation.xlsx",
            )
        )
        self.db.commit()

        with self.assertRaises(HTTPException) as pending_raised:
            execute_action(self.db, case, pending_token, "pending-import", self.admin)
        self.assertEqual(pending_raised.exception.status_code, 409)
        self.assertIn("source_import_in_progress", pending_raised.exception.detail["blockers"])

    def test_action_execution_rejects_cross_batch_parameters_after_validation(self):
        self._seed_negative_inventory()
        other_batch = ImportBatch(
            batch_no="INV-FORGED-TARGET",
            file_name="forged-target.xlsx",
            file_type="inventory_snapshot",
            data_date=date(2026, 7, 27),
            uploaded_by=self.admin.id,
            uploaded_at=datetime.now(timezone.utc) - timedelta(days=1),
            status="committed",
            total_rows=1,
            success_rows=1,
            error_rows=0,
            raw_file_path="forged-target.xlsx",
        )
        self.db.add(other_batch)
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        action, token = validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)
        self.assertTrue(action.allowed)
        action.parameters_json = {"batch_id": other_batch.id}
        self.db.commit()

        with (
            patch("app.services.exception_center_service._run_action") as run_action,
            self.assertRaises(HTTPException) as raised,
        ):
            execute_action(self.db, case, token, "cross-batch-execution", self.admin)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("batch_id_mismatch", raised.exception.detail["blockers"])
        run_action.assert_not_called()

    def test_action_execution_acquires_sync_lock_before_case_row_lock(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        _action, token = validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)
        lock_order: list[str] = []

        def acquire_sync_lock(db):  # noqa: ANN001, ARG001
            lock_order.append("sync")

        def lock_case(db, case_id):  # noqa: ANN001
            lock_order.append("case")
            return db.get(ExceptionCase, case_id)

        with (
            patch("app.services.exception_center_service._acquire_exception_sync_lock", side_effect=acquire_sync_lock),
            patch("app.services.exception_center_service._lock_exception_case_for_action", side_effect=lock_case),
            patch("app.services.exception_center_service._run_action", return_value={"rebuilt": True}),
            patch("app.services.exception_center_service.run_full_exception_scan", return_value={"resolved": 0}),
        ):
            executed = execute_action(self.db, case, token, "lock-order", self.admin)

        self.assertEqual(executed.status, "completed")
        self.assertEqual(lock_order, ["sync", "case"])

    def test_action_execution_rechecks_case_visibility_under_row_lock(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        _action, token = validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)

        with (
            patch("app.services.exception_center_service.can_view_case", return_value=False),
            patch("app.services.exception_center_service._run_action") as run_action,
            self.assertRaises(HTTPException) as raised,
        ):
            execute_action(self.db, case, token, "visibility-recheck", self.admin)

        self.assertEqual(raised.exception.status_code, 404)
        run_action.assert_not_called()

    def test_action_execution_rechecks_case_is_still_active(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        _action, token = validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)
        case.status = "resolved"
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            execute_action(self.db, case, token, "inactive-case", self.admin)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("case_not_active", raised.exception.detail["blockers"])

    def test_action_idempotency_reuses_original_and_rejects_conflict(self):
        snapshot = self._seed_negative_inventory()
        snapshot_two = InventorySnapshot(
            batch_id=snapshot.batch_id,
            row_number=2,
            data_date=snapshot.data_date,
            product_code="NEG-002",
            product_name="Second negative stock",
            warehouse_name="Main",
            warehouse_scope="specific",
            stock_qty=Decimal("-2"),
            locked_base_qty=Decimal("0"),
            raw_row_json={},
        )
        self.db.add(snapshot_two)
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        cases = list(
            self.db.scalars(
                select(ExceptionCase)
                .where(ExceptionCase.rule_code == "inventory.negative_stock")
                .order_by(ExceptionCase.resource_code)
            ).all()
        )
        _first_action, first_token = validate_action(self.db, cases[0], "rebuild_inventory_flow", {}, self.admin)
        _second_action, second_token = validate_action(self.db, cases[1], "rebuild_inventory_flow", {}, self.admin)

        with (
            patch("app.services.exception_center_service._run_action", return_value={"rebuilt": True}),
            patch("app.services.exception_center_service.run_full_exception_scan", return_value={"resolved": 0}),
        ):
            first = execute_action(self.db, cases[0], first_token, "shared-idempotency", self.admin)
            repeated = execute_action(self.db, cases[0], first_token, "shared-idempotency", self.admin)
            with (
                patch("app.services.exception_center_service.can_view_case", return_value=False),
                self.assertRaises(HTTPException) as hidden_replay,
            ):
                execute_action(self.db, cases[0], first_token, "shared-idempotency", self.admin)
            with self.assertRaises(HTTPException) as conflict:
                execute_action(self.db, cases[1], second_token, "shared-idempotency", self.admin)

        self.assertEqual(first.id, repeated.id)
        self.assertEqual(hidden_replay.exception.status_code, 404)
        self.assertEqual(conflict.exception.status_code, 409)

    def test_action_failure_persists_only_safe_error_code(self):
        self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        _action, token = validate_action(self.db, case, "rebuild_inventory_flow", {}, self.admin)

        with patch(
            "app.services.exception_center_service._run_action",
            side_effect=RuntimeError("password=do-not-store; /private/path; customer secret"),
        ):
            executed = execute_action(self.db, case, token, "safe-error-message", self.admin)
        self.db.flush()
        event = self.db.scalar(
            select(ExceptionEvent)
            .where(ExceptionEvent.case_id == case.id, ExceptionEvent.event_type == "action_failed")
            .order_by(ExceptionEvent.id.desc())
        )

        self.assertEqual(executed.status, "failed")
        self.assertEqual(executed.error_message, "action_execution_failed")
        self.assertNotIn("do-not-store", str(event.detail_json))

    def test_scan_resolves_expired_ignored_case_when_anomaly_disappears(self):
        snapshot = self._seed_negative_inventory()
        run_full_exception_scan(self.db)
        self.db.commit()
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.rule_code == "inventory.negative_stock"))
        case.status = "ignored"
        case.ignored_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        snapshot.stock_qty = Decimal("2")
        self.db.commit()
        run_full_exception_scan(self.db)
        self.db.commit()
        self.db.refresh(case)
        self.assertEqual(case.status, "resolved")


if __name__ == "__main__":
    unittest.main()
