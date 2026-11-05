import unittest
from unittest.mock import MagicMock, patch
from datetime import date, datetime, timezone

from fastapi import HTTPException

from app.api.routes.mobile import _visible_nav
from app.api.routes.mobile_data import mobile_master_data
from app.api.routes.mobile_tools import mobile_dashboard_overview, mobile_notifications, mobile_scan_resolve
from app.main import create_app
from app.models import CustomerMaster, InventoryCheckBatch, ProductMaster, User
from app.schemas.crm import CrmReportNotificationCenter, CrmReportNotificationSummary


class MobileRound3ApiTest(unittest.TestCase):
    def setUp(self):
        self.user = User(
            id=1,
            username="admin",
            password_hash="hash",
            real_name="施总",
            role="admin",
            status="active",
            is_active=True,
        )

    def test_round3_routes_are_registered(self):
        paths = set(create_app().openapi()["paths"])
        expected = {
            "/api/v1/mobile/data/overview",
            "/api/v1/mobile/data/master/{kind}",
            "/api/v1/mobile/data/sales",
            "/api/v1/mobile/data/purchases",
            "/api/v1/mobile/data/account-ledger",
            "/api/v1/mobile/data/inventory-snapshots",
            "/api/v1/mobile/checks/inventory/batches",
            "/api/v1/mobile/checks/inventory/batches/{batch_id}/results",
            "/api/v1/mobile/checks/receivable/uploads",
            "/api/v1/mobile/checks/receivable/uploads/{batch_id}/validate",
            "/api/v1/mobile/checks/receivable/uploads/{batch_id}/commit",
            "/api/v1/mobile/checks/receivable/results",
            "/api/v1/mobile/notifications",
            "/api/v1/mobile/notifications/{notification_id}/process",
            "/api/v1/mobile/scan/resolve",
            "/api/v1/mobile/telemetry/batch",
            "/api/v1/mobile/dashboard/overview",
            "/api/v1/mobile/assistant/runtime",
            "/api/v1/mobile/assistant/messages",
        }
        self.assertTrue(expected.issubset(paths), expected - paths)

    def test_data_navigation_is_permission_driven(self):
        with patch("app.api.routes.mobile.has_permission", side_effect=lambda _db, _user, code: code == "sales_detail.view"):
            keys = [item["key"] for item in _visible_nav(object(), self.user)]
        self.assertIn("data", keys)

    def test_lead_and_fulfillment_permissions_expose_their_parent_navigation(self):
        with patch(
            "app.api.routes.mobile.has_permission",
            side_effect=lambda _db, _user, code: code in {"crm_lead.view", "delivery.view"},
        ):
            keys = [item["key"] for item in _visible_nav(object(), self.user)]
        self.assertIn("customers", keys)
        self.assertIn("projects", keys)

    def test_mobile_navigation_uses_five_business_entries_without_profile_tab(self):
        with patch("app.api.routes.mobile.has_permission", return_value=True):
            navigation = _visible_nav(object(), self.user)
        self.assertEqual(
            [item["key"] for item in navigation],
            ["home", "customers", "projects", "approvals", "data"],
        )
        self.assertEqual([item["label"] for item in navigation], ["首页", "客户", "项目", "审批", "数据"])

    def test_mobile_exception_navigation_replaces_data_when_enabled(self):
        with (
            patch("app.api.routes.mobile.settings.mobile_feature_exception_center", True),
            patch("app.api.routes.mobile.settings.exception_center_enabled", True),
            patch("app.api.routes.mobile.has_permission", return_value=True),
        ):
            navigation = _visible_nav(object(), self.user)
        self.assertEqual([item["key"] for item in navigation], ["home", "customers", "projects", "approvals", "exceptions"])

    def test_mobile_dashboard_keeps_string_conclusion_for_released_clients(self):
        conclusion = {
            "tone": "bad",
            "title": "实时库存校验存在差异，今日优先处理",
            "detail": "最近校验发现 849 条差异，建议按商品逐行核对。",
            "target": {"page": "inventory", "path": "/inventory?tab=check&batch_id=1"},
        }
        with patch(
            "app.api.routes.mobile_tools.dashboard_overview",
            return_value={"range": "today", "conclusion": conclusion, "metrics": [], "actions": []},
        ):
            result = mobile_dashboard_overview(range_key="today", db=object(), current_user=self.user)

        self.assertEqual(result["conclusion"], conclusion["title"])
        self.assertEqual(result["conclusion_card"], conclusion)

    def test_master_data_rejects_unknown_kind(self):
        with self.assertRaises(HTTPException) as error:
            mobile_master_data(kind="employees", db=object(), current_user=self.user)
        self.assertEqual(error.exception.status_code, 400)

    def test_scan_returns_multiple_when_exact_value_matches_product_and_customer(self):
        product = ProductMaster(product_code="P001", product_name="测试商品", barcode="690000000001")
        customer = CustomerMaster(customer_code="690000000001", customer_name="同号客户")
        db = MagicMock()
        db.scalar.side_effect = [product, customer]
        with patch("app.api.routes.mobile_tools.has_permission", return_value=True):
            result = mobile_scan_resolve(value="690000000001", db=db, current_user=self.user)
        self.assertEqual(result["match_type"], "multiple")
        self.assertEqual(result["matches"][0]["code"], "P001")
        self.assertEqual(result["matches"][1]["code"], "690000000001")

    def test_scan_requires_an_exact_supported_value(self):
        db = MagicMock()
        db.scalar.side_effect = [None, None]
        with patch("app.api.routes.mobile_tools.has_permission", return_value=True):
            result = mobile_scan_resolve(value="不存在的模糊名称", db=db, current_user=self.user)
        self.assertEqual(result, {"match_type": "none", "matches": [], "query": "不存在的模糊名称"})

    def test_notifications_include_latest_inventory_and_receivable_risks(self):
        db = MagicMock()
        batch = InventoryCheckBatch(
            id=9,
            batch_no="CHK-9",
            file_name="库存.xls",
            data_date=date(2026, 5, 31),
            raw_file_path="runtime/inventory.xls",
            total_rows=100,
            difference_rows=6,
        )
        db.scalar.side_effect = [batch, date(2026, 5, 31), 4]
        empty_center = CrmReportNotificationCenter(
            summary=CrmReportNotificationSummary(),
            items=[],
            generated_at=datetime.now(timezone.utc),
        )
        with (
            patch("app.api.routes.mobile_tools.crm_report_notifications", return_value=empty_center),
            patch("app.api.routes.mobile_tools.has_permission", return_value=True),
            patch("app.api.routes.mobile_tools._processed_notification_ids", return_value=set()),
        ):
            result = mobile_notifications(db=db, current_user=self.user)
        self.assertEqual(result["summary"]["data_risk"], 2)
        self.assertEqual([item["source_type"] for item in result["items"]], ["inventory_check", "receivable_check"])

    def test_processed_data_risk_is_not_returned_as_pending(self):
        db = MagicMock()
        batch = InventoryCheckBatch(
            id=9,
            batch_no="CHK-9",
            file_name="库存.xls",
            data_date=date(2026, 5, 31),
            raw_file_path="runtime/inventory.xls",
            total_rows=100,
            difference_rows=6,
        )
        db.scalar.side_effect = [batch, None]
        empty_center = CrmReportNotificationCenter(
            summary=CrmReportNotificationSummary(),
            items=[],
            generated_at=datetime.now(timezone.utc),
        )
        with (
            patch("app.api.routes.mobile_tools.crm_report_notifications", return_value=empty_center),
            patch("app.api.routes.mobile_tools.has_permission", return_value=True),
            patch("app.api.routes.mobile_tools._processed_notification_ids", return_value={"data_risk:inventory_check:9"}),
        ):
            result = mobile_notifications(db=db, current_user=self.user)
        self.assertEqual(result["summary"]["pending"], 0)
        self.assertEqual(result["items"][0]["status"], "processed")


if __name__ == "__main__":
    unittest.main()
