import unittest
from datetime import date

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.services.import_service import (
    build_field_mapping,
    infer_account_ledger_period_from_table,
    infer_data_date_from_upload,
    insert_account_ledger_entry,
    resolve_file_type,
    table_from_raw,
    validate_rows,
)
from app.models import ImportBatch, AccountLedgerEntry, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class AccountLedgerImportTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()

    def test_account_ledger_detects_period_end_and_inherits_settlement_unit(self):
        raw = pd.DataFrame(
            [
                ["往来对账明细表", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None],
                ["查询日期：", "2025-09-01", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None],
                ["到", "2025-09-30", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None],
                [None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None],
                [
                    "行号",
                    "结算单位编号",
                    "结算单位名称",
                    "单据类型",
                    "单据日期",
                    "单据编号",
                    "经手人",
                    "往来单位",
                    "折前金额",
                    "单据金额",
                    "抹零_优惠金额",
                    "实收金额",
                    "应收金额",
                    "实付金额",
                    "应付金额",
                    "预收金额",
                    "预付金额",
                    "往来余额",
                ],
                [1, "KH001", "客户A", "期初", None, None, None, None, 0, 0, 0, 0, 100, 0, 0, 0, 0, 100],
                [2, None, None, "收款单", "2025-09-01", "XS1", "张三", "客户A", 0, 50, 0, 50, -50, 0, 0, 0, 0, 50],
                [3, None, None, "期末", None, None, None, None, 0, 0, 0, 50, 50, 0, 0, 0, 0, 50],
            ],
            dtype=object,
        )

        file_type = resolve_file_type(raw, "account_ledger")
        inferred_date, source = infer_data_date_from_upload(raw, file_type, "普丰_往来明细_202509.xls")
        period_start, period_end = infer_account_ledger_period_from_table(raw)
        df = table_from_raw(raw, file_type)
        mapping = build_field_mapping(file_type, [str(column).strip() for column in df.columns.tolist()])
        valid_rows, issues = validate_rows(self.db, file_type, df.to_dict(orient="records"), mapping)

        self.assertEqual(file_type, "account_ledger")
        self.assertEqual(inferred_date, date(2025, 9, 30))
        self.assertEqual(source, "table_meta")
        self.assertEqual(period_start, date(2025, 9, 1))
        self.assertEqual(period_end, date(2025, 9, 30))
        self.assertEqual(issues, [])
        self.assertEqual(len(valid_rows), 3)
        self.assertEqual(valid_rows[1]["settlement_unit_code"], "KH001")
        self.assertEqual(valid_rows[1]["settlement_unit_name"], "客户A")
        self.assertEqual(valid_rows[1]["document_type"], "收款单")

        user = User(username="admin", password_hash="hash", real_name="施总", role="admin", status="active", is_active=True)
        self.db.add(user)
        self.db.flush()
        batch = ImportBatch(
            batch_no="LEDGER202509",
            file_name="普丰_往来明细_202509.xls",
            file_type="account_ledger",
            data_date=period_end,
            uploaded_by=user.id,
            status="validated",
            raw_file_path="/tmp/account-ledger.xls",
        )
        self.db.add(batch)
        self.db.flush()
        for row in valid_rows:
            insert_account_ledger_entry(self.db, batch, row, period_start=period_start, period_end=period_end)
        self.db.flush()

        opening = self.db.query(AccountLedgerEntry).filter_by(row_role="opening").one()
        transaction = self.db.query(AccountLedgerEntry).filter_by(row_role="transaction").one()
        closing = self.db.query(AccountLedgerEntry).filter_by(row_role="closing").one()
        self.assertEqual(opening.period_start, date(2025, 9, 1))
        self.assertEqual(opening.period_end, date(2025, 9, 30))
        self.assertEqual(opening.balance_date, date(2025, 8, 31))
        self.assertEqual(transaction.balance_date, date(2025, 9, 1))
        self.assertEqual(closing.balance_date, date(2025, 9, 30))


if __name__ == "__main__":
    unittest.main()
