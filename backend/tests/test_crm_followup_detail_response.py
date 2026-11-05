import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.crm_projects import get_crm_followup, list_crm_followups_page
from app.core.database import Base
from app.models import CrmFollowup, CrmProject, CrmProjectCustomerTask, CustomerMaster, DataScopeRule, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmFollowupDetailResponseTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.viewer = User(
            username="followup-viewer",
            password_hash="hash",
            real_name="跟进查看人",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.hidden_viewer = User(
            username="hidden-viewer",
            password_hash="hash",
            real_name="无范围用户",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.db.add_all([self.viewer, self.hidden_viewer])
        self.db.flush()
        self.db.add(
            DataScopeRule(
                subject_type="user",
                subject_id=str(self.viewer.id),
                resource_type="crm_followup",
                scope_mode="all",
                is_active=True,
            )
        )
        self.db.add(
            DataScopeRule(
                subject_type="user",
                subject_id=str(self.hidden_viewer.id),
                resource_type="crm_followup",
                scope_mode="own",
                is_active=True,
            )
        )
        self.customer = CustomerMaster(
            customer_code="C-FOLLOWUP-001",
            customer_name="客户当前名称",
            status="active",
        )
        self.project = CrmProject(
            project_code="P-FOLLOWUP-001",
            project_name="客户跟进项目",
            status="active",
            approval_status="approved",
            created_by_user_id=self.viewer.id,
        )
        self.db.add_all([self.customer, self.project])
        self.db.flush()
        self.task = CrmProjectCustomerTask(
            project_id=self.project.id,
            task_code="T-FOLLOWUP-001",
            customer_code=self.customer.customer_code,
            customer_name_snapshot="客户历史名称",
            executor_user_id=self.viewer.id,
            executor_name_snapshot=self.viewer.real_name,
            status="in_progress",
        )
        self.db.add(self.task)
        self.db.flush()
        self.followup = CrmFollowup(
            followup_no="F-FOLLOWUP-001",
            project_id=self.project.id,
            task_id=self.task.id,
            customer_code=self.customer.customer_code,
            executor_user_id=self.viewer.id,
            executor_name_snapshot=self.viewer.real_name,
            review_status="approved",
        )
        self.db.add(self.followup)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_page_and_detail_return_the_same_customer_and_project_names(self):
        page = list_crm_followups_page(db=self.db, current_user=self.viewer)
        detail = get_crm_followup(self.followup.id, db=self.db, current_user=self.viewer)

        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].customer_name, "客户当前名称")
        self.assertEqual(detail.customer_name, page.items[0].customer_name)
        self.assertEqual(detail.project_name, "客户跟进项目")

    def test_detail_falls_back_to_task_customer_name_snapshot(self):
        self.customer.customer_name = ""
        self.db.commit()

        detail = get_crm_followup(self.followup.id, db=self.db, current_user=self.viewer)

        self.assertEqual(detail.customer_name, "客户历史名称")

    def test_detail_keeps_followup_scope_protection(self):
        with self.assertRaises(HTTPException) as caught:
            get_crm_followup(self.followup.id, db=self.db, current_user=self.hidden_viewer)

        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
