import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    AccountLedgerEntry,
    ImportBatch,
    ReceivableCheckResult,
    ReceivableSnapshot,
    User,
)
from app.services.receivable_service import rebuild_receivable_checks, receivable_summary
from app.services.import_service import commit_batch


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ReceivableServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(username="admin", password_hash="hash", real_name="施总", role="admin", status="active", is_active=True)
        self.db.add(self.user)
        self.db.flush()
        self.current_batch = ImportBatch(
            batch_no="REC20250831",
            file_name="普丰_应收查询表_20250831_.xls",
            file_type="receivable_snapshot",
            data_date=date(2025, 8, 31),
            uploaded_by=self.user.id,
            status="committed",
            total_rows=5,
            success_rows=5,
            error_rows=0,
            raw_file_path="/tmp/receivable.xls",
        )
        self.previous_batch = ImportBatch(
            batch_no="REC20250830",
            file_name="普丰_应收查询表_20250830_.xls",
            file_type="receivable_snapshot",
            data_date=date(2025, 8, 30),
            uploaded_by=self.user.id,
            status="committed",
            total_rows=1,
            success_rows=1,
            error_rows=0,
            raw_file_path="/tmp/receivable-prev.xls",
        )
        self.account_batch = ImportBatch(
            batch_no="LEDGER202509",
            file_name="普丰_往来明细_202509.xls",
            file_type="account_ledger",
            data_date=date(2025, 9, 30),
            uploaded_by=self.user.id,
            status="committed",
            total_rows=2,
            success_rows=2,
            error_rows=0,
            raw_file_path="/tmp/account-ledger.xls",
        )
        self.db.add_all([self.current_batch, self.previous_batch, self.account_batch])
        self.db.flush()
        self.db.add_all(
            [
                ReceivableSnapshot(
                    batch_id=self.previous_batch.id,
                    row_number=1,
                    data_date=date(2025, 8, 30),
                    customer_code="C001",
                    customer_name="吴江恒力食堂",
                    ar_balance=Decimal("800"),
                    raw_row_json={},
                ),
                ReceivableSnapshot(
                    batch_id=self.current_batch.id,
                    row_number=1,
                    data_date=date(2025, 8, 31),
                    customer_code="C001",
                    customer_name="吴江恒力食堂",
                    ar_balance=Decimal("1200"),
                    raw_row_json={},
                ),
                ReceivableSnapshot(
                    batch_id=self.current_batch.id,
                    row_number=2,
                    data_date=date(2025, 8, 31),
                    customer_code="C002",
                    customer_name="名称不一致客户",
                    ar_balance=Decimal("500"),
                    raw_row_json={},
                ),
                ReceivableSnapshot(
                    batch_id=self.current_batch.id,
                    row_number=3,
                    data_date=date(2025, 8, 31),
                    customer_code=None,
                    customer_name="未知客户",
                    ar_balance=Decimal("300"),
                    raw_row_json={},
                ),
                ReceivableSnapshot(
                    batch_id=self.current_batch.id,
                    row_number=4,
                    data_date=date(2025, 8, 31),
                    customer_code="C004",
                    customer_name="重复客户",
                    ar_balance=Decimal("40"),
                    raw_row_json={},
                ),
                ReceivableSnapshot(
                    batch_id=self.current_batch.id,
                    row_number=5,
                    data_date=date(2025, 8, 31),
                    customer_code="C004",
                    customer_name="重复客户",
                    ar_balance=Decimal("60"),
                    raw_row_json={},
                ),
                AccountLedgerEntry(
                    batch_id=self.account_batch.id,
                    row_number=1,
                    data_date=date(2025, 8, 31),
                    period_start=date(2025, 9, 1),
                    period_end=date(2025, 9, 30),
                    balance_date=date(2025, 8, 31),
                    settlement_unit_code="C001",
                    settlement_unit_name="吴江恒力食堂",
                    document_type="期初",
                    ar_amount=Decimal("1000"),
                    row_role="opening",
                    raw_row_json={},
                ),
                AccountLedgerEntry(
                    batch_id=self.account_batch.id,
                    row_number=2,
                    data_date=date(2025, 8, 31),
                    period_start=date(2025, 9, 1),
                    period_end=date(2025, 9, 30),
                    balance_date=date(2025, 8, 31),
                    settlement_unit_code="C002",
                    settlement_unit_name="往来名称",
                    document_type="期初",
                    ar_amount=Decimal("500"),
                    row_role="opening",
                    raw_row_json={},
                ),
                AccountLedgerEntry(
                    batch_id=self.account_batch.id,
                    row_number=3,
                    data_date=date(2025, 8, 31),
                    period_start=date(2025, 9, 1),
                    period_end=date(2025, 9, 30),
                    balance_date=date(2025, 8, 31),
                    settlement_unit_code="C003",
                    settlement_unit_name="只有往来明细客户",
                    document_type="期初",
                    ar_amount=Decimal("700"),
                    row_role="opening",
                    raw_row_json={},
                ),
                AccountLedgerEntry(
                    batch_id=self.account_batch.id,
                    row_number=4,
                    data_date=date(2025, 8, 31),
                    period_start=date(2025, 9, 1),
                    period_end=date(2025, 9, 30),
                    balance_date=date(2025, 8, 31),
                    settlement_unit_code="C004",
                    settlement_unit_name="重复客户",
                    document_type="期初",
                    ar_amount=Decimal("100"),
                    row_role="opening",
                    raw_row_json={},
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_rebuild_checks_uses_receivable_query_against_ledger_opening_or_closing_rows(self):
        summary = rebuild_receivable_checks(self.db, batch_id=self.current_batch.id)
        self.db.commit()

        self.assertEqual(summary["total_rows"], 5)
        self.assertEqual(summary["unmatched_rows"], 1)
        self.assertGreaterEqual(summary["risk_rows"], 5)

        results = list(
            self.db.scalars(
                select(ReceivableCheckResult)
            ).all()
        )
        result_types = {row.result_type for row in results}
        self.assertIn("amount_mismatch", result_types)
        self.assertIn("missing_in_ledger", result_types)
        self.assertIn("missing_in_receivable_query", result_types)
        self.assertIn("unit_name_mismatch", result_types)
        self.assertIn("duplicate_unit", result_types)
        self.assertNotIn("customer_unmatched", result_types)
        self.assertNotIn("account_balance_mismatch", result_types)
        self.assertNotIn("ar_increased", result_types)
        self.assertNotIn("aging_risk", result_types)
        self.assertNotIn("supply_with_debt", result_types)

        code_matched = self.db.scalar(
            select(ReceivableSnapshot).where(
                ReceivableSnapshot.batch_id == self.current_batch.id,
                ReceivableSnapshot.customer_code == "C002",
            )
        )
        self.assertEqual(code_matched.matched_customer_code, "C002")
        self.assertEqual(code_matched.matched_customer_name, "往来名称")
        self.assertEqual(code_matched.match_status, "matched_by_code")

    def test_receivable_summary_counts_latest_batch_risks(self):
        rebuild_receivable_checks(self.db, batch_id=self.current_batch.id)
        self.db.commit()

        summary = receivable_summary(self.db)

        self.assertEqual(summary["latest_data_date"], "2025-08-31")
        self.assertEqual(summary["rows"], 5)
        self.assertEqual(summary["unmatched_rows"], 1)
        self.assertEqual(summary["ar_balance"], "2100.00")

    def test_commit_receivable_import_inserts_snapshots_and_rebuilds_checks(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "普丰_应收查询表_20250831_.csv"
            csv_path.write_text("结算单位名称,应收余额,账龄\n吴江恒力食堂,1300,45\n未知客户,200,10\n", encoding="utf-8")
            batch = ImportBatch(
                batch_no="REC-COMMIT",
                file_name=csv_path.name,
                file_type="receivable_snapshot",
                data_date=date(2025, 8, 31),
                uploaded_by=self.user.id,
                status="uploaded",
                total_rows=2,
                success_rows=0,
                error_rows=0,
                raw_file_path=str(csv_path),
                mapping_json={"customer_name": "结算单位名称", "ar_balance": "应收余额", "aging_label": "账龄"},
            )
            self.db.add(batch)
            self.db.commit()

            commit_batch(self.db, batch)
            self.db.commit()

            snapshots = list(self.db.scalars(select(ReceivableSnapshot).where(ReceivableSnapshot.batch_id == batch.id)).all())
            self.assertEqual(len(snapshots), 2)
            self.assertEqual(snapshots[0].data_date, date(2025, 8, 31))
            self.assertEqual(snapshots[0].ar_balance, Decimal("1300.00"))
            results = list(self.db.scalars(select(ReceivableCheckResult).where(ReceivableCheckResult.batch_id == batch.id)).all())
            self.assertGreaterEqual(len(results), 1)
            self.assertIn("missing_in_ledger", {row.result_type for row in results})
            self.assertNotIn("customer_unmatched", {row.result_type for row in results})


if __name__ == "__main__":
    unittest.main()
