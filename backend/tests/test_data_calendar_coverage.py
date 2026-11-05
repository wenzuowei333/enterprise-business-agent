import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes import imports as import_routes
from app.api.routes.imports import collect_document_date_coverage
from app.core.database import Base
from app.models import AccountLedgerEntry, ImportBatch, SalesDetail, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class DataCalendarCoverageTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(username="admin", password_hash="hash", real_name="施总", role="admin", status="active", is_active=True)
        self.db.add(self.user)
        self.db.flush()
        self.sales_batch = ImportBatch(
            batch_no="SAL202509",
            file_name="普丰 销售2509.xls",
            file_type="sales_detail",
            data_date=date(2025, 9, 1),
            uploaded_by=self.user.id,
            status="committed",
            total_rows=3,
            success_rows=3,
            error_rows=0,
            raw_file_path="/tmp/sales.xls",
        )
        self.uploaded_batch = ImportBatch(
            batch_no="SAL202509-UPLOADED",
            file_name="未入库销售.xls",
            file_type="sales_detail",
            data_date=date(2025, 9, 2),
            uploaded_by=self.user.id,
            status="uploaded",
            total_rows=1,
            success_rows=0,
            error_rows=0,
            raw_file_path="/tmp/sales-uploaded.xls",
        )
        self.account_batch = ImportBatch(
            batch_no="LEDGER202509",
            file_name="普丰_往来明细_202509.xls",
            file_type="account_ledger",
            data_date=date(2025, 9, 30),
            uploaded_by=self.user.id,
            status="committed",
            total_rows=3,
            success_rows=3,
            error_rows=0,
            raw_file_path="/tmp/account-ledger.xls",
        )
        self.db.add_all([self.sales_batch, self.uploaded_batch, self.account_batch])
        self.db.flush()
        self.db.add_all(
            [
                SalesDetail(batch_id=self.sales_batch.id, row_number=1, data_date=date(2025, 9, 1), document_date=date(2025, 9, 1), raw_row_json={}),
                SalesDetail(batch_id=self.sales_batch.id, row_number=2, data_date=date(2025, 9, 2), document_date=date(2025, 9, 2), raw_row_json={}),
                SalesDetail(batch_id=self.sales_batch.id, row_number=3, data_date=date(2025, 9, 3), document_date=date(2025, 9, 3), raw_row_json={}),
                SalesDetail(batch_id=self.uploaded_batch.id, row_number=1, data_date=date(2025, 9, 4), document_date=date(2025, 9, 4), raw_row_json={}),
                AccountLedgerEntry(
                    batch_id=self.account_batch.id,
                    row_number=1,
                    data_date=date(2025, 8, 31),
                    balance_date=date(2025, 8, 31),
                    row_role="opening",
                    period_start=date(2025, 9, 1),
                    period_end=date(2025, 9, 30),
                    raw_row_json={},
                ),
                AccountLedgerEntry(
                    batch_id=self.account_batch.id,
                    row_number=2,
                    data_date=date(2025, 9, 8),
                    document_date=date(2025, 9, 8),
                    balance_date=date(2025, 9, 8),
                    row_role="transaction",
                    period_start=date(2025, 9, 1),
                    period_end=date(2025, 9, 30),
                    raw_row_json={},
                ),
                AccountLedgerEntry(
                    batch_id=self.account_batch.id,
                    row_number=3,
                    data_date=date(2025, 9, 30),
                    balance_date=date(2025, 9, 30),
                    row_role="closing",
                    period_start=date(2025, 9, 1),
                    period_end=date(2025, 9, 30),
                    raw_row_json={},
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_monthly_sales_batch_covers_each_document_date(self):
        coverage = collect_document_date_coverage(
            self.db,
            model=SalesDetail,
            file_type="sales_detail",
            from_date=date(2025, 9, 1),
            to_date=date(2025, 9, 30),
        )

        by_date = {item.data_date.isoformat(): item for item in coverage}
        self.assertEqual(set(by_date), {"2025-09-01", "2025-09-02", "2025-09-03"})
        self.assertEqual(by_date["2025-09-02"].row_count, 1)
        self.assertEqual(by_date["2025-09-02"].latest_batch_no, "SAL202509")
        self.assertEqual(by_date["2025-09-02"].batch_nos, ["SAL202509"])
        self.assertNotIn("2025-09-04", by_date)

    def test_account_ledger_period_covers_each_day_in_calendar(self):
        coverage = import_routes.collect_account_ledger_coverage(
            self.db,
            from_date=date(2025, 9, 1),
            to_date=date(2025, 9, 30),
        )

        by_date = {item.data_date.isoformat(): item for item in coverage}
        self.assertEqual(len(by_date), 30)
        self.assertEqual(by_date["2025-09-01"].file_type, "account_ledger")
        self.assertEqual(by_date["2025-09-01"].source, "ledger_period")
        self.assertEqual(by_date["2025-09-08"].row_count, 1)
        self.assertEqual(by_date["2025-09-30"].row_count, 1)
        self.assertEqual(by_date["2025-09-30"].latest_batch_no, "LEDGER202509")
        self.assertNotIn("2025-08-31", by_date)


if __name__ == "__main__":
    unittest.main()
