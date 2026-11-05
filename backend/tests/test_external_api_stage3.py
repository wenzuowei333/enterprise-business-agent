import unittest
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.mobile_errors import install_mobile_error_contract
from app.api.routes.external_api import ExternalApiKeyCreate, PERMISSION_OPTIONS
from app.api.routes.external_api_v2 import router as external_v2_router
from app.api.routes.external_api_v2_operations import router as operations_router
from app.core.database import Base, get_db
from app.models import (
    CrmProject,
    CrmProjectCustomerTask,
    CustomerMaster,
    ExternalApiKey,
    ImportBatch,
    InventorySnapshot,
    MasterLinkIssue,
    ProductMaster,
    PurchaseDetail,
    ReceivableSnapshot,
    SalesDetail,
    SupplierMaster,
)
from app.services.external_api_service import hash_external_token


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ExternalApiStage3Test(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.token = "pb-ext-stage3-full"
        self.product_token = "pb-ext-stage3-products"
        self._seed_data()

        app = FastAPI()
        install_mobile_error_contract(app)
        app.include_router(external_v2_router)
        app.include_router(operations_router)

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _seed_data(self):
        now = datetime.now(timezone.utc)
        today = date.today()
        east_a = CustomerMaster(
            customer_code="C-EAST-A",
            customer_name="East customer A",
            customer_short_name="East A",
            customer_type="restaurant",
            region="East",
            salesperson_name="Alice",
            contact_phone="13900000001",
            address="SECRET EAST ADDRESS",
            base_remark="SECRET EAST REMARK",
        )
        east_b = CustomerMaster(
            customer_code="C-EAST-B",
            customer_name="East customer B",
            region="East",
            contact_phone="13900000002",
        )
        west = CustomerMaster(
            customer_code="C-WEST",
            customer_name="WEST SECRET CUSTOMER",
            region="West",
            contact_phone="13999999999",
        )
        self.db.add_all([east_a, east_b, west])
        self.db.flush()

        project = CrmProject(
            project_code="P-STAGE3",
            project_name="Stage 3 scoped project",
            purpose="Validate operation data",
            status="active",
            approval_status="approved",
        )
        hidden_project = CrmProject(
            project_code="P-STAGE3-HIDDEN",
            project_name="Hidden project",
            status="active",
            approval_status="approved",
        )
        self.db.add_all([project, hidden_project])
        self.db.flush()
        self.project_id = project.id
        self.db.add_all(
            [
                CrmProjectCustomerTask(
                    project_id=project.id,
                    task_code="T-EAST-A",
                    customer_code=east_a.customer_code,
                    customer_name_snapshot=east_a.customer_name,
                ),
                CrmProjectCustomerTask(
                    project_id=project.id,
                    task_code="T-EAST-B",
                    customer_code=east_b.customer_code,
                    customer_name_snapshot=east_b.customer_name,
                ),
                CrmProjectCustomerTask(
                    project_id=hidden_project.id,
                    task_code="T-WEST",
                    customer_code=west.customer_code,
                    customer_name_snapshot=west.customer_name,
                ),
            ]
        )

        self.db.add_all(
            [
                ProductMaster(
                    product_code="PR-001",
                    product_name="Safe product",
                    spec="10kg",
                    unit="bag",
                    category="Food",
                    brand="Demo",
                    barcode="690000000001",
                    reference_sale_price=Decimal("120.00"),
                    reference_cost=Decimal("66.66"),
                    source="SECRET PRODUCT SOURCE",
                ),
                ProductMaster(product_code="PR-002", product_name="Second product", status="active"),
                SupplierMaster(
                    supplier_code="S-001",
                    supplier_name="Safe supplier",
                    supplier_short_name="Supplier",
                    supplier_type="manufacturer",
                    region="Jiangsu",
                    contact_name="SECRET CONTACT",
                    contact_phone="13888888888",
                    address="SECRET SUPPLIER ADDRESS",
                    source="SECRET SUPPLIER SOURCE",
                ),
            ]
        )

        old_batch = ImportBatch(
            batch_no="B-OLD",
            file_name="old-sales.xlsx",
            file_type="sales",
            data_date=today - timedelta(days=1),
            raw_file_path="SECRET/old-sales.xlsx",
            status="completed",
            total_rows=1,
            success_rows=1,
            uploaded_at=now - timedelta(days=1),
        )
        sales_batch = ImportBatch(
            batch_no="B-SALES",
            file_name="sales.xlsx",
            file_type="sales",
            data_date=today,
            raw_file_path="SECRET/sales.xlsx",
            status="completed",
            total_rows=2,
            success_rows=2,
            uploaded_at=now,
        )
        purchase_batch = ImportBatch(
            batch_no="B-PURCHASE",
            file_name="purchase.xlsx",
            file_type="purchase",
            data_date=today,
            raw_file_path="SECRET/purchase.xlsx",
            status="partial",
            total_rows=1,
            success_rows=1,
            error_rows=0,
            uploaded_at=now,
        )
        self.db.add_all([old_batch, sales_batch, purchase_batch])
        self.db.flush()

        self.db.add_all(
            [
                SalesDetail(
                    batch_id=sales_batch.id,
                    row_number=1,
                    data_date=today,
                    document_date=today,
                    document_no="SALE-EAST",
                    customer_code=east_a.customer_code,
                    customer_name=east_a.customer_name,
                    product_code="PR-001",
                    product_name="Safe product",
                    sale_qty_base=Decimal("10"),
                    amount_after_discount=Decimal("1000"),
                    gross_profit=Decimal("200"),
                    raw_row_json={"secret": "RAW SALES SECRET"},
                ),
                SalesDetail(
                    batch_id=sales_batch.id,
                    row_number=2,
                    data_date=today,
                    document_date=today,
                    document_no="SALE-WEST",
                    customer_code=west.customer_code,
                    customer_name=west.customer_name,
                    product_code="PR-002",
                    product_name="Second product",
                    sale_qty_base=Decimal("99"),
                    amount_after_discount=Decimal("9999"),
                    gross_profit=Decimal("999"),
                    raw_row_json={"secret": "WEST RAW SALES SECRET"},
                ),
                PurchaseDetail(
                    batch_id=purchase_batch.id,
                    row_number=1,
                    data_date=today,
                    document_date=today,
                    document_no="PURCHASE-1",
                    supplier_code="S-001",
                    supplier_name="Safe supplier",
                    product_code="PR-001",
                    product_name="Safe product",
                    purchase_qty_base=Decimal("30"),
                    purchase_amount=Decimal("1800"),
                    raw_row_json={"secret": "RAW PURCHASE SECRET"},
                ),
            ]
        )

        self.db.add_all(
            [
                InventorySnapshot(
                    batch_id=old_batch.id,
                    row_number=1,
                    data_date=today - timedelta(days=1),
                    product_code="PR-001",
                    product_name="Safe product",
                    warehouse_name="WH-A",
                    stock_qty=Decimal("999"),
                    locked_base_qty=Decimal("0"),
                    cost_amount=Decimal("9999"),
                ),
                InventorySnapshot(
                    batch_id=sales_batch.id,
                    row_number=1,
                    data_date=today,
                    product_code="PR-001",
                    product_name="Safe product",
                    warehouse_name="WH-A",
                    stock_qty=Decimal("50"),
                    locked_base_qty=Decimal("5"),
                    cost_amount=Decimal("3000"),
                    raw_row_json={"secret": "RAW INVENTORY SECRET"},
                ),
            ]
        )

        self.db.add_all(
            [
                ReceivableSnapshot(
                    batch_id=sales_batch.id,
                    row_number=1,
                    data_date=today,
                    customer_code=east_a.customer_code,
                    customer_name=east_a.customer_name,
                    matched_customer_code=east_a.customer_code,
                    matched_customer_name=east_a.customer_name,
                    ar_balance=Decimal("500"),
                    received_amount=Decimal("200"),
                    unreceived_amount=Decimal("300"),
                    aging_label="31-60 days",
                    overdue_days=35,
                    salesperson_name="Alice",
                    raw_row_json={"secret": "RAW RECEIVABLE SECRET"},
                ),
                ReceivableSnapshot(
                    batch_id=sales_batch.id,
                    row_number=2,
                    data_date=today,
                    customer_code=west.customer_code,
                    customer_name=west.customer_name,
                    matched_customer_code=west.customer_code,
                    matched_customer_name=west.customer_name,
                    ar_balance=Decimal("9999"),
                    received_amount=Decimal("0"),
                    unreceived_amount=Decimal("9999"),
                    aging_label="90+ days",
                    overdue_days=100,
                    salesperson_name="Mallory",
                ),
            ]
        )

        self.db.add_all(
            [
                MasterLinkIssue(
                    batch_id=sales_batch.id,
                    source_file_type="sales",
                    issue_type="unmatched_customer",
                    expected_master_kind="customer",
                    reference_code="UNKNOWN-C",
                    affected_rows=3,
                    affected_documents=2,
                    source_json={"secret": "QUALITY SOURCE SECRET"},
                ),
                MasterLinkIssue(
                    batch_id=purchase_batch.id,
                    source_file_type="purchase",
                    issue_type="unmatched_product",
                    expected_master_kind="product",
                    reference_code="UNKNOWN-P",
                    affected_rows=1,
                    affected_documents=1,
                    status="resolved",
                ),
            ]
        )

        full_key = ExternalApiKey(
            key_id="ext_stage3_full",
            name="Stage 3 full agent",
            key_prefix=self.token[:16],
            key_hash=hash_external_token(self.token),
            scope_region="East",
            scope_project_ids=[project.id],
            allowed_customer_fields=["customer_code", "customer_name", "region"],
            can_read_projects=True,
            can_read_customers=True,
            can_read_products=True,
            can_read_suppliers=True,
            can_read_sales_summary=True,
            can_read_purchase_summary=True,
            can_read_inventory_summary=True,
            can_read_receivables=True,
            can_read_data_quality=True,
        )
        product_key = ExternalApiKey(
            key_id="ext_stage3_products",
            name="Stage 3 product agent",
            key_prefix=self.product_token[:16],
            key_hash=hash_external_token(self.product_token),
            allowed_customer_fields=["customer_code", "customer_name"],
            can_read_projects=False,
            can_read_customers=False,
            can_read_products=True,
        )
        self.db.add_all([full_key, product_key])
        self.db.commit()

    def _headers(self, token=None):
        return {"Authorization": f"Bearer {token or self.token}"}

    def test_capabilities_expose_independent_stage3_permissions(self):
        response = self.client.get("/api/external/v2/capabilities", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        capabilities = {item["code"]: item["enabled"] for item in response.json()["data"]["capabilities"]}
        self.assertTrue(capabilities["products.read"])
        self.assertTrue(capabilities["sales.summary.read"])
        self.assertTrue(capabilities["data_quality.read"])

        denied = self.client.get("/api/external/v2/operations/sales-summary", headers=self._headers(self.product_token))
        self.assertEqual(denied.status_code, 403)
        self.assertIn("sales.summary.read", denied.json()["error"]["message"])

    def test_customer_scope_field_policy_and_cursor(self):
        first = self.client.get("/api/external/v2/customers", headers=self._headers(), params={"limit": 1})
        second = self.client.get(
            "/api/external/v2/customers",
            headers=self._headers(),
            params={"limit": 1, "cursor": first.json()["meta"]["next_cursor"]},
        )
        hidden = self.client.get("/api/external/v2/customers/C-WEST", headers=self._headers())

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["meta"]["has_more"])
        self.assertNotEqual(
            first.json()["data"]["items"][0]["customer_code"],
            second.json()["data"]["items"][0]["customer_code"],
        )
        self.assertEqual(first.json()["data"]["items"][0]["fields"].keys(), {"region"})
        self.assertNotIn("contact_phone", first.text)
        self.assertNotIn("SECRET", first.text)
        self.assertEqual(hidden.status_code, 404)

    def test_product_and_supplier_contracts_exclude_sensitive_fields(self):
        products = self.client.get("/api/external/v2/products", headers=self._headers())
        suppliers = self.client.get("/api/external/v2/suppliers", headers=self._headers())

        self.assertEqual(products.status_code, 200)
        self.assertEqual(suppliers.status_code, 200)
        self.assertEqual({item["product_code"] for item in products.json()["data"]["items"]}, {"PR-001", "PR-002"})
        self.assertNotIn("reference_cost", products.text)
        self.assertNotIn("PRODUCT SOURCE", products.text)
        self.assertNotIn("contact_phone", suppliers.text)
        self.assertNotIn("SUPPLIER ADDRESS", suppliers.text)
        self.assertNotIn("SUPPLIER SOURCE", suppliers.text)

    def test_sales_summary_is_scoped_to_visible_customers(self):
        response = self.client.get("/api/external/v2/operations/sales-summary", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["row_count"], 1)
        self.assertEqual(Decimal(data["net_sales"]), Decimal("1000"))
        self.assertEqual(Decimal(data["gross_profit"]), Decimal("200"))
        self.assertEqual(Decimal(data["gross_margin_rate"]), Decimal("20"))
        self.assertEqual([item["key"] for item in data["breakdown"]], ["C-EAST-A"])
        self.assertNotIn("WEST", response.text)
        self.assertNotIn("raw_row_json", response.text)

    def test_purchase_summary_is_global_only_with_explicit_permission(self):
        response = self.client.get("/api/external/v2/operations/purchase-summary", headers=self._headers())
        denied = self.client.get("/api/external/v2/operations/purchase-summary", headers=self._headers(self.product_token))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["row_count"], 1)
        self.assertEqual(Decimal(response.json()["data"]["purchase_amount"]), Decimal("1800"))
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("RAW PURCHASE SECRET", response.text)

    def test_inventory_uses_latest_snapshot_by_default(self):
        latest = self.client.get("/api/external/v2/operations/inventory-summary", headers=self._headers())
        old = self.client.get(
            "/api/external/v2/operations/inventory-summary",
            headers=self._headers(),
            params={"data_date": (date.today() - timedelta(days=1)).isoformat()},
        )

        self.assertEqual(latest.status_code, 200)
        self.assertEqual(Decimal(latest.json()["data"]["stock_quantity"]), Decimal("50"))
        self.assertEqual(Decimal(old.json()["data"]["stock_quantity"]), Decimal("999"))
        self.assertNotIn("RAW INVENTORY SECRET", latest.text)

    def test_receivable_summary_uses_latest_scoped_customer_snapshot(self):
        response = self.client.get("/api/external/v2/operations/receivable-summary", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["customer_count"], 1)
        self.assertEqual(Decimal(data["receivable_amount"]), Decimal("500"))
        self.assertEqual(data["overdue_customer_count"], 1)
        self.assertEqual(Decimal(data["overdue_amount"]), Decimal("500"))
        self.assertNotIn("WEST", response.text)
        self.assertNotIn("RAW RECEIVABLE SECRET", response.text)

    def test_data_quality_returns_aggregates_and_latest_import_only(self):
        response = self.client.get("/api/external/v2/data-quality/summary", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["open_issue_count"], 1)
        self.assertEqual(data["affected_rows"], 3)
        self.assertEqual(data["issue_groups"][0]["issue_type"], "unmatched_customer")
        sales_import = next(item for item in data["latest_imports"] if item["file_type"] == "sales")
        self.assertEqual(sales_import["data_date"], date.today().isoformat())
        self.assertNotIn("raw_file_path", response.text)
        self.assertNotIn("QUALITY SOURCE SECRET", response.text)
        self.assertNotIn("old-sales.xlsx", response.text)

    def test_stage3_validation_and_response_leakage_contract(self):
        invalid_group = self.client.get(
            "/api/external/v2/operations/sales-summary", headers=self._headers(), params={"group_by": "document"}
        )
        invalid_limit = self.client.get(
            "/api/external/v2/operations/inventory-summary", headers=self._headers(), params={"limit": 101}
        )

        self.assertEqual(invalid_group.status_code, 422)
        self.assertEqual(invalid_limit.status_code, 422)
        forbidden = ["raw_row_json", "raw_file_path", "source_json", "reference_cost", "contact_phone", "address"]
        paths = [
            "/api/external/v2/customers",
            "/api/external/v2/products",
            "/api/external/v2/suppliers",
            "/api/external/v2/operations/sales-summary",
            "/api/external/v2/operations/purchase-summary",
            "/api/external/v2/operations/inventory-summary",
            "/api/external/v2/operations/receivable-summary",
            "/api/external/v2/data-quality/summary",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path, headers=self._headers())
                self.assertEqual(response.status_code, 200)
                for field in forbidden:
                    self.assertNotIn(field, response.text)

    def test_permission_columns_are_present_and_default_closed(self):
        columns = ExternalApiKey.__table__.c
        for name in (
            "can_read_products",
            "can_read_suppliers",
            "can_read_sales_summary",
            "can_read_purchase_summary",
            "can_read_inventory_summary",
            "can_read_receivables",
            "can_read_data_quality",
        ):
            self.assertIn(name, columns)
            self.assertFalse(columns[name].default.arg)

    def test_management_create_contract_accepts_independent_permissions(self):
        payload = ExternalApiKeyCreate(
            name="Operations-only agent",
            allowed_customer_fields=["customer_code", "customer_name"],
            can_read_projects=False,
            can_read_customers=False,
            can_read_products=True,
            can_read_sales_summary=True,
            can_read_data_quality=True,
        )
        option_codes = {code for code, _label in PERMISSION_OPTIONS}

        self.assertTrue(payload.can_read_products)
        self.assertTrue(payload.can_read_sales_summary)
        self.assertTrue(payload.can_read_data_quality)
        self.assertIn("can_read_inventory_summary", option_codes)
        self.assertIn("can_read_receivables", option_codes)

    def test_permission_migration_upgrades_and_downgrades_real_database(self):
        permission_columns = {
            "can_read_products",
            "can_read_suppliers",
            "can_read_sales_summary",
            "can_read_purchase_summary",
            "can_read_inventory_summary",
            "can_read_receivables",
            "can_read_data_quality",
        }
        backend_dir = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "migration.db"
            migration_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with migration_engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE external_api_keys (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
                connection.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES ('20260720_0100')")
            environment = os.environ.copy()
            environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"

            upgrade = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(upgrade.returncode, 0, upgrade.stderr)
            upgraded_columns = {column["name"] for column in inspect(migration_engine).get_columns("external_api_keys")}
            self.assertTrue(permission_columns.issubset(upgraded_columns))

            downgrade = subprocess.run(
                [sys.executable, "-m", "alembic", "downgrade", "20260720_0100"],
                cwd=backend_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(downgrade.returncode, 0, downgrade.stderr)
            downgraded_columns = {column["name"] for column in inspect(migration_engine).get_columns("external_api_keys")}
            self.assertTrue(permission_columns.isdisjoint(downgraded_columns))
            migration_engine.dispose()


if __name__ == "__main__":
    unittest.main()
