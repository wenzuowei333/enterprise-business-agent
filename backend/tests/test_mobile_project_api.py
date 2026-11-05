import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.mobile import mobile_customer_options, mobile_project_submissions, mobile_user_options
from app.models import ApprovalInstance, User


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class MobileProjectApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        User.__table__.create(self.engine)
        ApprovalInstance.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.current_user = User(
            username="applicant",
            password_hash="hash",
            real_name="申请人",
            role="business_middle_office",
            status="active",
            is_active=True,
        )
        self.db.add_all(
            [
                self.current_user,
                User(
                    username="admin",
                    password_hash="hash",
                    real_name="施总",
                    employee_code="ADMIN-001",
                    role="admin",
                    status="active",
                    is_active=True,
                ),
                User(
                    username="disabled",
                    password_hash="hash",
                    real_name="停用人员",
                    role="salesperson",
                    status="disabled",
                    is_active=False,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_user_options_only_include_active_accounts(self):
        with patch("app.api.routes.mobile.has_permission", return_value=True):
            page = mobile_user_options(q=None, limit=20, offset=0, db=self.db, current_user=self.current_user)

        self.assertEqual(page["total"], 2)
        self.assertEqual([item["username"] for item in page["items"]], ["admin", "applicant"])
        self.assertEqual(page["items"][0]["label"], "施总 / admin")

    def test_customer_options_use_scoped_master_data_result(self):
        scoped_result = {
            "items": [
                {
                    "customer_code": "KH001",
                    "customer_name": "测试客户",
                    "customer_short_name": "测试",
                    "salesperson_employee_code": "E001",
                    "salesperson_name": "业务员",
                    "contact_name": "联系人",
                    "contact_phone": "13800000000",
                    "region": "苏州",
                    "customer_type": "普通客户",
                }
            ],
            "total": 1,
            "limit": 20,
            "offset": 0,
        }
        with (
            patch("app.api.routes.mobile.has_permission", return_value=True),
            patch("app.api.routes.mobile.list_customers_page", return_value=scoped_result) as scoped_page,
        ):
            page = mobile_customer_options(q="测试", limit=20, offset=0, db=self.db, current_user=self.current_user)

        scoped_page.assert_called_once()
        self.assertEqual(page["items"][0]["customer_code"], "KH001")
        self.assertEqual(page["items"][0]["salesperson_name"], "业务员")

    def test_project_submission_page_only_contains_current_applicant_projects(self):
        self.db.add_all(
            [
                ApprovalInstance(
                    approval_no="AP-MINE",
                    approval_type="crm_project_create",
                    resource_type="crm_project",
                    resource_id="pending",
                    title="我的项目",
                    applicant_user_id=self.current_user.id,
                    status="draft",
                    priority="normal",
                    payload_json={"project": {"project_name": "我的项目"}, "tasks": []},
                ),
                ApprovalInstance(
                    approval_no="AP-OTHER-TYPE",
                    approval_type="customer_business_profile_update",
                    resource_type="customer_business_profile",
                    resource_id="KH001",
                    title="其他审批",
                    applicant_user_id=self.current_user.id,
                    status="draft",
                    priority="normal",
                ),
            ]
        )
        self.db.commit()

        with patch("app.api.routes.mobile._approval_public", side_effect=lambda _db, row: {"id": row.id, "approval_no": row.approval_no}):
            page = mobile_project_submissions(scope="active", q=None, limit=20, offset=0, db=self.db, current_user=self.current_user)

        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["approval_no"], "AP-MINE")


if __name__ == "__main__":
    unittest.main()
