import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.crm_projects import get_crm_task_detail, list_crm_project_tasks_page, list_crm_tasks_page
from app.core.database import Base
from app.models import (
    ApprovalInstance,
    CrmFollowup,
    CrmProject,
    CrmProjectCustomerTask,
    CustomerMaster,
    DataScopeRule,
    Permission,
    Role,
    RolePermission,
    User,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmTaskSubmissionStatusTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self._seed_tasks()

    def tearDown(self):
        self.db.close()

    def _seed_identity(self):
        sales_role = Role(role_code="salesperson", role_name="Salesperson")
        admin_role = Role(role_code="admin", role_name="Admin")
        task_view = Permission(
            permission_code="crm_task.view",
            permission_name="View CRM tasks",
            resource_type="crm_task",
            action_type="view",
        )
        self.salesperson = User(
            username="salesperson",
            password_hash="hash",
            real_name="Sales User",
            employee_code="SALE001",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.admin = User(
            username="admin",
            password_hash="hash",
            real_name="Admin User",
            employee_code="ADMIN",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add_all([sales_role, admin_role, task_view, self.salesperson, self.admin])
        self.db.flush()
        self.db.add(RolePermission(role_id=sales_role.id, permission_id=task_view.id))
        self.db.add(
            DataScopeRule(
                subject_type="role",
                subject_id="salesperson",
                resource_type="crm_task",
                scope_mode="own",
                scope_value=None,
            )
        )
        self.db.commit()

    def _seed_tasks(self):
        self.project = CrmProject(
            project_code="PROJECT-SUBMISSION",
            project_name="Submission status project",
            status="active",
            approval_status="approved",
            owner_user_id=self.admin.id,
            created_by_user_id=self.admin.id,
        )
        self.db.add(self.project)
        self.db.flush()
        self.tasks = {}
        for index, key in enumerate(
            ["unsubmitted", "pending", "completed", "needs_action", "draft_only", "legacy"],
            start=1,
        ):
            customer = CustomerMaster(
                customer_code=f"C-SUB-{index}",
                customer_name=f"Customer {index}",
                status="active",
            )
            self.db.add(customer)
            self.db.flush()
            task = CrmProjectCustomerTask(
                project_id=self.project.id,
                task_code=f"TASK-SUB-{index}",
                customer_code=customer.customer_code,
                customer_name_snapshot=customer.customer_name,
                executor_user_id=self.salesperson.id,
                executor_employee_code=self.salesperson.employee_code,
                executor_name_snapshot=self.salesperson.real_name,
                status="in_progress",
            )
            self.db.add(task)
            self.db.flush()
            self.tasks[key] = task

        hidden_customer = CustomerMaster(customer_code="C-HIDDEN", customer_name="Hidden customer", status="active")
        self.db.add(hidden_customer)
        self.db.flush()
        self.hidden_task = CrmProjectCustomerTask(
            project_id=self.project.id,
            task_code="TASK-HIDDEN",
            customer_code=hidden_customer.customer_code,
            customer_name_snapshot=hidden_customer.customer_name,
            executor_user_id=self.admin.id,
            executor_employee_code=self.admin.employee_code,
            executor_name_snapshot=self.admin.real_name,
            status="in_progress",
        )
        self.db.add(self.hidden_task)
        self.db.flush()

        self._add_approval(self.tasks["pending"], "submitted", "A-PENDING")
        self._add_approval(self.tasks["completed"], "completed", "A-COMPLETED")
        self._add_approval(self.tasks["needs_action"], "completed", "A-OLDER-COMPLETED")
        self._add_approval(self.tasks["needs_action"], "rejected", "A-LATEST-REJECTED")
        self._add_approval(self.tasks["draft_only"], "draft", "A-DRAFT")
        self._add_approval(self.hidden_task, "submitted", "A-HIDDEN")

        legacy_followup = CrmFollowup(
            followup_no="FOLLOWUP-LEGACY",
            project_id=self.project.id,
            task_id=self.tasks["legacy"].id,
            customer_code=self.tasks["legacy"].customer_code,
            executor_user_id=self.salesperson.id,
            executor_name_snapshot=self.salesperson.real_name,
            review_status="approved",
        )
        self.db.add(legacy_followup)
        self.db.flush()
        self.tasks["legacy"].latest_followup_id = legacy_followup.id
        self.tasks["legacy"].last_followup_at = datetime.now(timezone.utc)
        self.db.commit()

    def _add_approval(self, task: CrmProjectCustomerTask, status: str, approval_no: str):
        self.db.add(
            ApprovalInstance(
                approval_no=approval_no,
                approval_type="crm_followup_submit",
                resource_type="crm_followup",
                resource_id="pending",
                title=approval_no,
                applicant_user_id=self.salesperson.id,
                current_handler_user_id=self.admin.id,
                status=status,
                priority="normal",
                payload_json={"followup": {"project_id": self.project.id, "task_id": task.id}},
                submitted_at=None if status == "draft" else datetime.now(timezone.utc),
            )
        )
        self.db.flush()

    def _page(self, submission_state=None, *, limit=50, offset=0):
        return list_crm_tasks_page(
            followup_submission_state=submission_state,
            limit=limit,
            offset=offset,
            db=self.db,
            current_user=self.salesperson,
        )

    def test_task_page_returns_submission_states_and_scope_safe_summary(self):
        page = self._page()

        self.assertEqual(page.total, 6)
        self.assertEqual(page.submission_summary.total, 6)
        self.assertEqual(page.submission_summary.submitted, 3)
        self.assertEqual(page.submission_summary.unsubmitted, 2)
        self.assertEqual(page.submission_summary.needs_action, 1)
        states = {task.task_code: task.followup_submission_state for task in page.items}
        self.assertEqual(states["TASK-SUB-1"], "unsubmitted")
        self.assertEqual(states["TASK-SUB-2"], "submitted")
        self.assertEqual(states["TASK-SUB-3"], "submitted")
        self.assertEqual(states["TASK-SUB-4"], "needs_action")
        self.assertEqual(states["TASK-SUB-5"], "unsubmitted")
        self.assertEqual(states["TASK-SUB-6"], "submitted")
        self.assertNotIn(self.hidden_task.task_code, states)

        needs_action = next(task for task in page.items if task.task_code == "TASK-SUB-4")
        self.assertEqual(needs_action.latest_followup_approval_status, "rejected")
        self.assertIsNotNone(needs_action.latest_followup_submitted_at)

    def test_submission_filter_paginates_without_changing_summary(self):
        submitted = self._page("submitted", limit=1)
        self.assertEqual(submitted.total, 3)
        self.assertEqual(len(submitted.items), 1)
        self.assertEqual(submitted.items[0].followup_submission_state, "submitted")
        self.assertEqual(submitted.submission_summary.total, 6)
        self.assertEqual(submitted.submission_summary.unsubmitted, 2)

        unsubmitted = self._page("unsubmitted")
        self.assertEqual(unsubmitted.total, 2)
        self.assertEqual({task.task_code for task in unsubmitted.items}, {"TASK-SUB-1", "TASK-SUB-5"})

        needs_action = self._page("needs_action")
        self.assertEqual(needs_action.total, 1)
        self.assertEqual(needs_action.items[0].task_code, "TASK-SUB-4")

    def test_project_page_and_task_detail_use_same_submission_state(self):
        project_page = list_crm_project_tasks_page(
            project_id=self.project.id,
            followup_submission_state="needs_action",
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertEqual(project_page.total, 1)
        self.assertEqual(project_page.submission_summary.total, 6)
        self.assertEqual(project_page.items[0].followup_submission_state, "needs_action")

        detail = get_crm_task_detail(
            self.tasks["needs_action"].id,
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertEqual(detail.task.followup_submission_state, "needs_action")
        self.assertEqual(detail.task.latest_followup_approval_status, "rejected")


if __name__ == "__main__":
    unittest.main()
