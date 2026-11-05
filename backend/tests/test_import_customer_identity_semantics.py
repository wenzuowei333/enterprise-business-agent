import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.models import ApprovalInstance, CrmLead, CustomerMaster, ImportBatch, User
from app.core.database import Base
from app.services.approval_service import execute_crm_lead_convert
from app.services.import_service import commit_batch, upsert_customer


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class _RowsTable:
    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, *, orient):
        assert orient == "records"
        return self._rows


class CustomerImportIdentitySemanticsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_import_allows_distinct_customer_codes_with_shared_identity(self):
        shared_identity = {
            "customer_name": "苏州恒力纺织有限公司",
            "contact_phone": "13800138000",
        }

        upsert_customer(self.db, {"customer_code": "C001", **shared_identity})
        upsert_customer(self.db, {"customer_code": "C002", **shared_identity})
        self.db.flush()

        self.assertEqual(
            [customer.customer_code for customer in self.db.scalars(select(CustomerMaster).order_by(CustomerMaster.customer_code))],
            ["C001", "C002"],
        )

    def test_large_customer_batch_does_not_scan_customer_identity_for_each_row(self):
        rows = [
            {
                "customer_code": f"C{index:04d}",
                "customer_name": "共享身份客户",
                "contact_phone": "13800138000",
            }
            for index in range(250)
        ]
        batch = ImportBatch(
            batch_no="IMP-CUSTOMER-IDENTITY-SEMANTICS",
            file_name="customers.csv",
            file_type="customer_master",
            raw_file_path="/tmp/customers.csv",
            status="validated",
            total_rows=len(rows),
            success_rows=len(rows),
        )
        self.db.add(batch)
        self.db.flush()

        with (
            patch("app.services.import_service.read_upload_table", return_value=_RowsTable(rows)),
            patch("app.services.import_service.validate_rows", return_value=(rows, [])),
            patch(
                "app.services.customer_identity_service.find_customer_identity_matches",
                side_effect=AssertionError("customer identity scan must not run for imported rows"),
            ) as find_matches,
        ):
            commit_batch(self.db, batch)

        self.assertEqual(batch.status, "committed")
        self.assertEqual(find_matches.call_count, 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(CustomerMaster)), 250)

    def test_conversion_blocks_after_imported_duplicate_is_committed(self):
        upsert_customer(
            self.db,
            {
                "customer_code": "C001",
                "customer_name": "苏州恒力纺织有限公司",
                "contact_phone": "13800138000",
            },
        )
        operator = User(
            username="conversion-operator",
            password_hash="hash",
            real_name="审批人",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add(operator)
        self.db.flush()
        lead = CrmLead(
            lead_no="LEAD-IDENTITY-001",
            lead_name="苏州恒力纺织有限公司",
            normalized_name="苏州恒力纺织有限公司",
            company_name="苏州恒力纺织有限公司",
            contact_phone="13800138000",
            normalized_phone="13800138000",
            status="conversion_pending",
            owner_user_id=operator.id,
            assigned_user_id=operator.id,
            created_by_user_id=operator.id,
            updated_by_user_id=operator.id,
        )
        self.db.add(lead)
        self.db.flush()
        approval = ApprovalInstance(
            approval_no="APR-IDENTITY-001",
            approval_type="crm_lead_convert",
            resource_type="crm_lead",
            resource_id=str(lead.id),
            title="客户线索转正",
            status="submitted",
            payload_json={
                "lead_id": lead.id,
                "lead": {"id": lead.id},
                "before": {"id": lead.id},
            },
        )
        self.db.add(approval)
        self.db.commit()

        with self.assertRaises(HTTPException) as error:
            execute_crm_lead_convert(self.db, approval, operator)

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(CustomerMaster)), 1)


if __name__ == "__main__":
    unittest.main()
