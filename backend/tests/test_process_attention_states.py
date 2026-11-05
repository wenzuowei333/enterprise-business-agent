import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes import dashboard
from app.api.routes.process_data import account_ledger_hierarchy, list_account_ledger_page, list_inventory_snapshots_page
from app.core.database import Base
from app.models import AccountLedgerEntry, ImportBatch, InventorySnapshot, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ProcessAttentionStateTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(username="attention-admin", password_hash="hash", real_name="管理员", role="admin", status="active", is_active=True)
        self.db.add(self.user)
        self.db.flush()

        self.inventory_old = self._batch("INV-OLD", "inventory_snapshot", date(2025, 8, 31), datetime(2026, 7, 10, tzinfo=timezone.utc))
        self.inventory_old_revision = self._batch("INV-OLD-REV", "inventory_snapshot", date(2025, 8, 31), datetime(2026, 7, 30, tzinfo=timezone.utc))
        self.inventory_current = self._batch("INV-CURRENT", "inventory_snapshot", date(2025, 9, 30), datetime(2026, 7, 20, tzinfo=timezone.utc))
        self.inventory_draft = self._batch("INV-DRAFT", "inventory_snapshot", date(2025, 10, 31), datetime(2026, 8, 1, tzinfo=timezone.utc), status="uploaded")
        self.ledger_old_revision = self._batch("LEDGER-OLD-REV", "account_ledger", date(2025, 8, 31), datetime(2026, 7, 30, tzinfo=timezone.utc))
        self.ledger_previous = self._batch("LEDGER-PREVIOUS", "account_ledger", date(2025, 9, 29), datetime(2026, 7, 19, tzinfo=timezone.utc))
        self.ledger_current = self._batch("LEDGER-CURRENT", "account_ledger", date(2025, 9, 30), datetime(2026, 7, 20, tzinfo=timezone.utc))

        self.db.add_all(
            [
                InventorySnapshot(batch_id=self.inventory_old.id, row_number=1, data_date=date(2025, 8, 31), product_code="OLD", stock_qty=1, locked_base_qty=0, raw_row_json={}),
                InventorySnapshot(batch_id=self.inventory_old_revision.id, row_number=1, data_date=date(2025, 8, 31), product_code="OLD-REV", stock_qty=-1, locked_base_qty=0, raw_row_json={}),
                InventorySnapshot(batch_id=self.inventory_current.id, row_number=1, data_date=date(2025, 9, 30), product_code="BOTH", stock_qty=-2, locked_base_qty=3, raw_row_json={}),
                InventorySnapshot(batch_id=self.inventory_current.id, row_number=2, data_date=date(2025, 9, 30), product_code="NORMAL", stock_qty=4, locked_base_qty=0, raw_row_json={}),
                InventorySnapshot(batch_id=self.inventory_draft.id, row_number=1, data_date=date(2025, 10, 31), product_code="DRAFT", stock_qty=-9, locked_base_qty=0, raw_row_json={}),
                AccountLedgerEntry(batch_id=self.ledger_old_revision.id, row_number=1, data_date=date(2025, 8, 31), balance_date=date(2025, 8, 31), row_role="closing", settlement_unit_code="OLD", ar_amount=9, raw_row_json={}),
                AccountLedgerEntry(batch_id=self.ledger_previous.id, row_number=1, data_date=date(2025, 9, 29), balance_date=date(2025, 9, 29), row_role="closing", settlement_unit_code="PREVIOUS-CLOSING", ar_amount=8, current_balance=8, raw_row_json={}),
                AccountLedgerEntry(batch_id=self.ledger_current.id, row_number=1, data_date=date(2025, 9, 29), balance_date=date(2025, 9, 29), row_role="opening", settlement_unit_code="OPEN", ar_amount=99, raw_row_json={}),
                AccountLedgerEntry(batch_id=self.ledger_current.id, row_number=2, data_date=date(2025, 9, 30), balance_date=date(2025, 9, 30), row_role="transaction", settlement_unit_code="TX", ap_amount=99, raw_row_json={}),
                AccountLedgerEntry(batch_id=self.ledger_current.id, row_number=3, data_date=date(2025, 9, 30), balance_date=date(2025, 9, 30), row_role="closing", settlement_unit_code="A", ar_amount=1, ap_amount=2, current_balance=10, raw_row_json={}),
                AccountLedgerEntry(batch_id=self.ledger_current.id, row_number=4, data_date=date(2025, 9, 30), balance_date=date(2025, 9, 30), row_role="closing", settlement_unit_code="B", ar_amount=0, ap_amount=0, current_balance=0, raw_row_json={}),
                AccountLedgerEntry(batch_id=self.ledger_current.id, row_number=5, data_date=date(2025, 9, 30), balance_date=date(2025, 9, 30), row_role="closing", settlement_unit_code="C", advance_receipt_amount=3, advance_payment_amount=4, current_balance=5, raw_row_json={}),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _batch(self, batch_no, file_type, data_date, uploaded_at, *, status="committed"):
        batch = ImportBatch(
            batch_no=batch_no,
            file_name=f"{batch_no}.xlsx",
            file_type=file_type,
            data_date=data_date,
            uploaded_by=self.user.id,
            uploaded_at=uploaded_at,
            status=status,
            total_rows=1,
            success_rows=1 if status == "committed" else 0,
            error_rows=0,
            raw_file_path=f"/tmp/{batch_no}.xlsx",
        )
        self.db.add(batch)
        self.db.flush()
        return batch

    def test_inventory_latest_uses_effective_date_and_deduplicates_attention_rows(self):
        result = list_inventory_snapshots_page(snapshot_scope="latest", db=self.db, current_user=self.user)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["attention_summary"]["batch_id"], self.inventory_current.id)
        self.assertEqual(result["attention_summary"]["effective_date"], "2025-09-30")
        self.assertEqual(result["attention_summary"]["needs_attention"], 1)
        self.assertEqual(result["attention_summary"]["normal"], 1)
        reason_counts = {item["code"]: item["count"] for item in result["attention_summary"]["by_reason"]}
        self.assertEqual(reason_counts, {"negative_stock": 1, "locked_stock": 1})
        both = next(item for item in result["items"] if item["product_code"] == "BOTH")
        self.assertEqual(both["attention_state"], "needs_attention")
        self.assertEqual({item["code"] for item in both["attention_reasons"]}, {"negative_stock", "locked_stock"})

    def test_daily_latest_and_explicit_batch_only_use_committed_matching_batches(self):
        daily = list_inventory_snapshots_page(
            snapshot_scope="daily_latest",
            date_from=date(2025, 8, 1),
            date_to=date(2025, 9, 30),
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual({item["product_code"] for item in daily["items"]}, {"OLD-REV", "BOTH", "NORMAL"})

        draft = list_inventory_snapshots_page(batch_id=self.inventory_draft.id, db=self.db, current_user=self.user)
        wrong_type = list_inventory_snapshots_page(batch_id=self.ledger_current.id, db=self.db, current_user=self.user)
        self.assertEqual(draft["total"], 0)
        self.assertEqual(wrong_type["total"], 0)

    def test_account_attention_only_counts_closing_rows_and_filters_are_stable(self):
        result = list_account_ledger_page(snapshot_scope="latest", db=self.db, current_user=self.user)

        self.assertEqual(result["total"], 5)
        self.assertEqual(result["attention_summary"]["total"], 3)
        self.assertEqual(result["attention_summary"]["needs_attention"], 2)
        self.assertEqual(result["attention_summary"]["normal"], 1)
        reason_counts = {item["code"]: item["count"] for item in result["attention_summary"]["by_reason"]}
        self.assertEqual(reason_counts, {
            "ar_non_zero": 1,
            "ap_non_zero": 1,
            "advance_receipt_non_zero": 1,
            "advance_payment_non_zero": 1,
        })
        opening = next(item for item in result["items"] if item["row_role"] == "opening")
        self.assertIsNone(opening["attention_state"])
        self.assertEqual(opening["attention_reasons"], [])

        filtered = list_account_ledger_page(
            snapshot_scope="latest",
            attention_state="needs_attention",
            attention_reason="ar_non_zero",
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["attention_summary"], result["attention_summary"])
        self.assertEqual(filtered["items"][0]["row_role"], "closing")

        normal = list_account_ledger_page(
            snapshot_scope="latest",
            attention_state="normal",
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(normal["total"], 1)
        self.assertEqual(normal["items"][0]["row_role"], "closing")
        self.assertEqual(normal["items"][0]["settlement_unit_code"], "B")
        hierarchy = account_ledger_hierarchy(
            row_role="closing",
            snapshot_scope="latest",
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(hierarchy["count"], 3)
        self.assertEqual(hierarchy["abnormal_count"], 2)

        daily_previous = list_account_ledger_page(
            snapshot_scope="daily_latest",
            date_from=date(2025, 9, 29),
            date_to=date(2025, 9, 29),
            row_role="closing",
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(daily_previous["total"], 1)
        self.assertEqual(daily_previous["items"][0]["settlement_unit_code"], "PREVIOUS-CLOSING")

    def test_dashboard_uses_latest_batches_outside_range_and_exact_drilldowns(self):
        def can_view(_db, _user, *codes):
            return "inventory_snapshot.view" in codes or "account_ledger.view" in codes

        with patch.object(dashboard, "has_permission", return_value=True), patch.object(dashboard, "_can", side_effect=can_view):
            result = dashboard.dashboard_overview(range_key="7d", db=self.db, current_user=self.user)

        inventory_row = next(item for item in result["risk_matrix"]["rows"] if item["key"] == "inventory")
        account_row = next(item for item in result["risk_matrix"]["rows"] if item["key"] == "account")
        inventory_abnormal = next(item for item in inventory_row["cells"] if item["key"] == "abnormal")
        account_abnormal = next(item for item in account_row["cells"] if item["key"] == "abnormal")
        self.assertEqual(inventory_abnormal["value"], 1)
        self.assertEqual(inventory_abnormal["label"], "库存风险")
        self.assertEqual(inventory_abnormal["effective_date"], "2025-09-30")
        self.assertIn(f"batch_id={self.inventory_current.id}", inventory_abnormal["target"]["path"])
        self.assertEqual(account_abnormal["value"], 2)
        self.assertEqual(account_abnormal["label"], "余额待核对")
        self.assertEqual(account_abnormal["effective_date"], "2025-09-30")
        self.assertIn("row_role=closing", account_abnormal["target"]["path"])
        self.assertIn(f"batch_id={self.ledger_current.id}", account_abnormal["target"]["path"])
        account_metric = next(item for item in result["metrics"] if item["key"] == "account")
        self.assertEqual(Decimal(str(account_metric["value"])), Decimal("15"))
        query = parse_qs(urlparse(account_abnormal["target"]["path"]).query)
        drilled = list_account_ledger_page(
            snapshot_scope=query["snapshot_scope"][0],
            attention_state=query["attention_state"][0],
            row_role=query["row_role"][0],
            batch_id=int(query["batch_id"][0]),
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(drilled["total"], account_abnormal["value"])


if __name__ == "__main__":
    unittest.main()
