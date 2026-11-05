import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.approvals import approve_approval
from app.api.routes.crm_projects import (
    create_crm_customer_profile_approval_draft,
    get_crm_linked_customer_profile,
    get_crm_task_detail,
    list_crm_linked_customers_page,
    list_crm_project_tasks_page,
    list_crm_tasks_page,
    update_crm_linked_customer_profile,
)
from app.core.database import Base
from app.models import ApprovalInstance, CustomerMaster, DataScopeRule, Permission, Role, RolePermission, User
from app.schemas.crm import CrmCustomerProfileApprovalDraftCreate
from app.schemas.master_data import CustomerMasterUpdate
from app.services.approval_service import create_approval_instance


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmCustomerProfileSubmitTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self._seed_customer_project()

    def tearDown(self):
        self.db.close()

    def _seed_identity(self):
        self.sales_role = Role(role_code="salesperson", role_name="业务员")
        self.admin_role = Role(role_code="admin", role_name="管理员")
        self.permissions = {
            code: Permission(permission_code=code, permission_name=name, resource_type=resource, action_type=action)
            for code, name, resource, action in [
                ("crm_task.view", "查看客户任务", "crm_task", "view"),
                ("crm_customer_profile.view", "查看项目客户基本资料", "crm_customer_profile", "view"),
                ("crm_customer_profile.submit", "保存项目客户基本资料更新", "crm_customer_profile", "submit"),
                ("approval.approve", "处理审批", "approval", "approve"),
                ("approval.view", "查看审批", "approval", "view"),
            ]
        }
        self.salesperson = User(
            username="fengyang",
            password_hash="hash",
            real_name="冯阳",
            employee_code="FY001",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.admin = User(
            username="admin",
            password_hash="hash",
            real_name="施总",
            employee_code="ADMIN",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add_all([self.sales_role, self.admin_role, *self.permissions.values(), self.salesperson, self.admin])
        self.db.flush()
        self.db.add_all([
            RolePermission(role_id=self.sales_role.id, permission_id=self.permissions["crm_task.view"].id),
            RolePermission(role_id=self.sales_role.id, permission_id=self.permissions["crm_customer_profile.view"].id),
            RolePermission(role_id=self.sales_role.id, permission_id=self.permissions["crm_customer_profile.submit"].id),
            RolePermission(role_id=self.sales_role.id, permission_id=self.permissions["approval.view"].id),
            RolePermission(role_id=self.admin_role.id, permission_id=self.permissions["approval.approve"].id),
            RolePermission(role_id=self.admin_role.id, permission_id=self.permissions["approval.view"].id),
        ])
        self.db.add(DataScopeRule(subject_type="role", subject_id="salesperson", resource_type="crm_task", scope_mode="own", scope_value=None))
        self.db.commit()

    def _seed_customer_project(self):
        from app.models import CrmProject, CrmProjectCustomerTask

        customer = CustomerMaster(
            customer_code="C001",
            customer_name="吴江恒力食堂",
            customer_short_name="恒力",
            customer_type="餐饮",
            region="苏州",
            contact_name="王经理",
            contact_phone="13900000001",
            salesperson_employee_code="OTHER",
            salesperson_name="其他业务员",
            status="active",
        )
        project = CrmProject(
            project_code="CRM001",
            project_name="客户拜访001",
            purpose="收集客户基本资料和经营资料",
            status="active",
            approval_status="approved",
            owner_user_id=self.admin.id,
            created_by_user_id=self.admin.id,
        )
        self.db.add_all([customer, project])
        self.db.flush()
        task = CrmProjectCustomerTask(
            project_id=project.id,
            task_code="TASK001",
            customer_code=customer.customer_code,
            customer_name_snapshot=customer.customer_name,
            executor_user_id=self.salesperson.id,
            executor_employee_code=self.salesperson.employee_code,
            executor_name_snapshot=self.salesperson.real_name,
            status="in_progress",
        )
        self.db.add(task)
        self.db.commit()
        self.customer = customer
        self.project = project
        self.task = task

    def test_task_page_exposes_searchable_project_purpose_without_expanding_scope(self):
        from app.models import CrmProject, CrmProjectCustomerTask

        hidden_customer = CustomerMaster(
            customer_code="C002",
            customer_name="不可见客户",
            salesperson_name="其他业务员",
            status="active",
        )
        hidden_project = CrmProject(
            project_code="CRM002",
            project_name="不可见项目",
            purpose="不可见项目目的",
            status="active",
            approval_status="approved",
            owner_user_id=self.admin.id,
            created_by_user_id=self.admin.id,
        )
        second_customer = CustomerMaster(
            customer_code="C003",
            customer_name="第二个可见客户",
            salesperson_name="其他业务员",
            status="active",
        )
        second_project = CrmProject(
            project_code="CRM003",
            project_name="第二个可见项目",
            purpose="补充客户经营现场资料",
            status="active",
            approval_status="approved",
            owner_user_id=self.admin.id,
            created_by_user_id=self.admin.id,
        )
        self.db.add_all([hidden_customer, hidden_project, second_customer, second_project])
        self.db.flush()
        second_task = CrmProjectCustomerTask(
            project_id=second_project.id,
            task_code="TASK003",
            customer_code=second_customer.customer_code,
            customer_name_snapshot=second_customer.customer_name,
            executor_user_id=self.salesperson.id,
            executor_name_snapshot=self.salesperson.real_name,
            status="not_started",
        )
        self.db.add_all([
            CrmProjectCustomerTask(
                project_id=hidden_project.id,
                task_code="TASK002",
                customer_code=hidden_customer.customer_code,
                customer_name_snapshot=hidden_customer.customer_name,
                executor_user_id=self.admin.id,
                executor_name_snapshot=self.admin.real_name,
                status="not_started",
            ),
            second_task,
        ])
        self.db.commit()

        def load_page(*, q=None, limit=50, offset=0):
            return list_crm_tasks_page(
                q=q,
                project_id=None,
                customer_code=None,
                customer_name=None,
                executor_user_id=None,
                status_value=None,
                minimum_action_done=None,
                need_support=None,
                need_manager_support=None,
                need_boss_decision=None,
                is_blocked=None,
                is_closed=None,
                overdue=None,
                due_from=None,
                due_to=None,
                limit=limit,
                offset=offset,
                db=self.db,
                current_user=self.salesperson,
            )

        all_page = load_page()
        self.assertEqual(all_page.total, 2)
        self.assertEqual(
            {task.id: task.project_purpose for task in all_page.items},
            {
                self.task.id: "收集客户基本资料和经营资料",
                second_task.id: "补充客户经营现场资料",
            },
        )

        purpose_page = load_page(q="收集客户基本资料")
        self.assertEqual(purpose_page.total, 1)
        self.assertEqual(purpose_page.items[0].project_purpose, "收集客户基本资料和经营资料")

        hidden_page = load_page(q="不可见项目目的")
        self.assertEqual(hidden_page.total, 0)
        self.assertEqual(hidden_page.items, [])

        paged = load_page(limit=1, offset=2)
        self.assertEqual(paged.total, 2)
        self.assertEqual(paged.items, [])

        project_page = list_crm_project_tasks_page(
            project_id=self.project.id,
            q=None,
            customer_code=None,
            customer_name=None,
            executor_user_id=None,
            status_value=None,
            minimum_action_done=None,
            need_support=None,
            is_blocked=None,
            is_closed=None,
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertEqual(project_page.total, 1)
        self.assertEqual(project_page.items[0].project_purpose, "收集客户基本资料和经营资料")

        self.project.purpose = None
        self.db.commit()
        empty_purpose_page = load_page()
        purpose_by_task_id = {task.id: task.project_purpose for task in empty_purpose_page.items}
        self.assertIsNone(purpose_by_task_id[self.task.id])

    def test_salesperson_saves_customer_profile_update_directly_without_approval(self):
        profile = get_crm_linked_customer_profile(
            "C001",
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertEqual(profile["customer_code"], "C001")
        self.assertEqual(profile["customer_name"], "吴江恒力食堂")

        result = update_crm_linked_customer_profile(
            "C001",
            CustomerMasterUpdate(
                customer_name="吴江恒力食堂更新",
                customer_short_name="恒力更新",
                contact_phone="13900009999",
                contact_name="李经理",
                base_remark="CRM 跟进页提交客户基本资料更新",
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertTrue(result["synced_to_master"])
        self.assertEqual(result["task_id"], self.task.id)
        self.assertIn("contact_phone", result["changed_fields"])
        self.assertEqual(result["customer"]["contact_phone"], "13900009999")
        self.assertIsNotNone(result["audit_log_id"])
        self.assertIsNone(
            self.db.scalar(select(ApprovalInstance).where(ApprovalInstance.approval_type == "customer_profile_update"))
        )

        customer_after = self.db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == "C001"))
        self.assertEqual(customer_after.customer_name, "吴江恒力食堂更新")
        self.assertEqual(customer_after.customer_short_name, "恒力更新")
        self.assertEqual(customer_after.contact_phone, "13900009999")
        self.assertEqual(customer_after.contact_name, "李经理")
        self.assertEqual(customer_after.source, "crm_profile_update")

    def test_customer_profile_direct_updates_merge_distinct_fields_without_overwriting(self):
        customer = self.db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == "C001"))
        customer.contact_phone = None
        customer.customer_group_name = None
        self.db.commit()

        update_crm_linked_customer_profile(
            "C001",
            CustomerMasterUpdate(
                customer_name="吴江恒力食堂",
                customer_short_name="恒力",
                customer_type="餐饮",
                region="苏州",
                contact_name="王经理",
                contact_phone="13900008888",
                customer_group_name=None,
                status="active",
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )
        update_crm_linked_customer_profile(
            "C001",
            CustomerMasterUpdate(
                customer_name="吴江恒力食堂",
                customer_short_name="恒力",
                customer_type="餐饮",
                region="苏州",
                contact_name="王经理",
                contact_phone=None,
                customer_group_name="普丰客户群",
                status="active",
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

        updated = self.db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == "C001"))
        self.assertEqual(updated.contact_phone, "13900008888")
        self.assertEqual(updated.customer_group_name, "普丰客户群")

    def test_customer_profile_direct_update_marks_task_started_and_returns_task_summary(self):
        self.task.status = "not_started"
        self.task.minimum_action_done = False
        self.task.latest_owner_next_status = None
        self.db.commit()

        update_crm_linked_customer_profile(
            "C001",
            CustomerMasterUpdate(contact_phone="13900008888"),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

        self.db.refresh(self.task)
        self.assertEqual(self.task.status, "in_progress")
        self.assertTrue(self.task.minimum_action_done)
        self.assertEqual(self.task.latest_owner_next_status, "资料更新已提交")

        page = list_crm_tasks_page(
            q=None,
            project_id=None,
            customer_code=None,
            customer_name=None,
            executor_user_id=None,
            status_value=None,
            minimum_action_done=None,
            need_support=None,
            need_manager_support=None,
            need_boss_decision=None,
            is_blocked=None,
            is_closed=None,
            overdue=None,
            due_from=None,
            due_to=None,
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertEqual(page.items[0].data_update_total, 1)
        self.assertEqual(page.items[0].data_update_pending, 0)
        self.assertIsNone(page.items[0].customer_profile_approval_id)
        self.assertEqual(page.items[0].customer_profile_approval_status, "synced")

    def test_task_detail_includes_customer_profile_approval_records(self):
        approval = create_crm_customer_profile_approval_draft(
            "C001",
            CrmCustomerProfileApprovalDraftCreate(
                submit=True,
                profile={"contact_phone": "13900008888"},
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

        detail = get_crm_task_detail(
            self.task.id,
            db=self.db,
            current_user=self.salesperson,
        )

        approval_types = {row.approval_type for row in detail.approvals}
        approval_ids = {row.id for row in detail.approvals}
        self.assertIn("customer_profile_update", approval_types)
        self.assertIn(approval.id, approval_ids)

    def test_legacy_customer_profile_approval_uses_change_items_to_avoid_null_overwrite(self):
        customer = self.db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == "C001"))
        customer.contact_phone = "13900007777"
        customer.customer_group_name = None
        self.db.commit()

        approval = create_approval_instance(
            self.db,
            approval_type="customer_profile_update",
            resource_type="crm_customer_profile",
            resource_id="C001",
            title="客户基本资料更新：吴江恒力食堂",
            description=None,
            applicant=self.salesperson,
            current_handler_user_id=self.admin.id,
            priority="normal",
            submit=True,
            payload_json={
                "customer_code": "C001",
                "customer_name": "吴江恒力食堂",
                "project_id": self.project.id,
                "task_id": 1,
                "profile": {
                    "contact_phone": None,
                    "customer_group_name": "普丰客户群",
                    "contact_name": None,
                    "address": None,
                },
                "change_items": [
                    {
                        "field": "customer_group_name",
                        "label": "客户群名称",
                        "before": None,
                        "after": "普丰客户群",
                    }
                ],
            },
        )
        self.db.commit()

        approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        updated = self.db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == "C001"))
        self.assertEqual(updated.contact_phone, "13900007777")
        self.assertEqual(updated.customer_group_name, "普丰客户群")
        self.assertEqual(updated.contact_name, "王经理")

    def test_customer_profile_approval_can_intentionally_clear_existing_field(self):
        customer = self.db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == "C001"))
        self.assertEqual(customer.contact_phone, "13900000001")

        approval = create_crm_customer_profile_approval_draft(
            "C001",
            CrmCustomerProfileApprovalDraftCreate(
                submit=True,
                profile={
                    "customer_name": "吴江恒力食堂",
                    "contact_phone": None,
                },
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

        self.assertEqual(approval.payload_json["profile"], {"contact_phone": None})
        self.assertIn(
            {
                "field": "contact_phone",
                "label": "联系电话",
                "before": "13900000001",
                "after": None,
            },
            approval.payload_json["change_items"],
        )

        approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        updated = self.db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == "C001"))
        self.assertIsNone(updated.contact_phone)

    def test_project_closed_removes_crm_customer_profile_access(self):
        self.project.status = "closed"
        self.db.commit()

        with self.assertRaises(Exception):
            get_crm_linked_customer_profile(
                "C001",
                request=None,
                db=self.db,
                current_user=self.salesperson,
            )

    def test_customer_profile_permission_can_list_active_linked_customers_without_task_view(self):
        task_view_permission = self.permissions["crm_task.view"]
        task_view_grant = self.db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == self.sales_role.id,
                RolePermission.permission_id == task_view_permission.id,
            )
        )
        self.assertIsNotNone(task_view_grant)
        self.db.delete(task_view_grant)
        self.db.commit()

        page = list_crm_linked_customers_page(
            q=None,
            scope="active_project",
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].customer_code, "C001")

        self.project.status = "cancelled"
        self.db.commit()

        closed_page = list_crm_linked_customers_page(
            q=None,
            scope="active_project",
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertEqual(closed_page.total, 0)


if __name__ == "__main__":
    unittest.main()
