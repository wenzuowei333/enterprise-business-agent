import unittest
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.approvals import approve_approval
from app.api.routes import crm_projects as crm_project_routes
from app.api.routes.crm_projects import (
    create_crm_business_profile_approval_draft,
    create_crm_followup_approval_draft,
    get_crm_linked_customer_context,
    get_crm_linked_customer_business_profile,
    list_crm_linked_customers_page,
    list_crm_tasks_page,
)
from app.core.database import Base
from app.models import (
    ApprovalInstance,
    CrmFollowup,
    CustomerBusinessProfile,
    CustomerBusinessProfileHistory,
    CustomerBusinessProduct,
    CustomerMaster,
    DataScopeRule,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.schemas.crm import (
    CrmBusinessProfileApprovalDraftCreate,
    CrmBusinessProfileUpdateResponse,
    CrmFollowupApprovalDraftCreate,
)
from app.schemas.master_data import CustomerBusinessProfileUpsert


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmBusinessProfileSubmitTest(unittest.TestCase):
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
                ("crm_business_profile.view", "查看项目客户经营资料", "crm_business_profile", "view"),
                ("crm_business_profile.submit", "保存项目客户经营资料", "crm_business_profile", "submit"),
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
            RolePermission(role_id=self.sales_role.id, permission_id=self.permissions["crm_business_profile.view"].id),
            RolePermission(role_id=self.sales_role.id, permission_id=self.permissions["crm_business_profile.submit"].id),
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
            customer_short_name="恒力食堂",
            customer_type="餐饮",
            region="苏州",
            salesperson_employee_code="OTHER",
            salesperson_name="其他业务员",
            status="active",
        )
        project = CrmProject(
            project_code="CRM001",
            project_name="客户拜访001",
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
            is_closed=True,
        )
        self.db.add(task)
        self.db.commit()
        self.customer = customer
        self.project = project
        self.task = task

    def test_salesperson_can_read_and_save_business_profile_for_active_linked_customer(self):
        result = get_crm_linked_customer_business_profile(
            "C001",
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertEqual(result["customer"]["customer_code"], "C001")
        self.assertIsNone(result["profile"])

        saved = crm_project_routes.update_crm_linked_customer_business_profile(
            "C001",
            CustomerBusinessProfileUpsert(
                business_customer_type="餐饮",
                confirmed_at=date(2026, 7, 4),
                filled_by="冯阳",
                update_source="现场拜访",
                update_type="新增资料",
                current_salesperson="冯阳",
                latest_update_note="补充经营资料",
                products=[
                    {
                        "product_category": "鸡产品",
                        "spec": "腿类",
                        "monthly_usage": "每月 20 箱",
                        "price_sensitivity": "一般",
                        "cooperation_status": "可开发",
                        "change_type": "新增",
                    }
                ],
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )
        self.assertTrue(saved["synced_to_master"])
        self.assertIn("latest_update_note", saved["changed_fields"])
        self.assertIsNone(
            self.db.scalar(
                select(ApprovalInstance).where(
                    ApprovalInstance.approval_type == "customer_business_profile_update"
                )
            )
        )

        profile = self.db.scalar(select(CustomerBusinessProfile).where(CustomerBusinessProfile.customer_code == "C001"))
        self.assertIsNotNone(profile)
        self.assertEqual(profile.latest_update_note, "补充经营资料")
        products = list(self.db.scalars(select(CustomerBusinessProduct).where(CustomerBusinessProduct.customer_code == "C001")).all())
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].product_category, "鸡产品")

    def test_salesperson_can_save_business_profile_directly_without_creating_approval(self):
        update_business_profile = getattr(crm_project_routes, "update_crm_linked_customer_business_profile", None)
        self.assertIsNotNone(update_business_profile, "CRM 经营资料需要提供直接保存接口")

        result = update_business_profile(
            "C001",
            CustomerBusinessProfileUpsert(
                business_customer_type="餐饮",
                latest_update_note="现场直接补充经营资料",
                recommended_products=[
                    {
                        "product_name": "九联冻120-130g腿",
                        "recommended_quote": "165 元/箱",
                        "customer_feedback": "愿意试单",
                    }
                ],
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

        self.assertTrue(result["synced_to_master"])
        self.assertEqual(result["task_id"], self.task.id)
        self.assertIn("latest_update_note", result["changed_fields"])
        self.assertEqual(self.db.scalar(select(ApprovalInstance).where(ApprovalInstance.approval_type == "customer_business_profile_update")), None)
        profile = self.db.scalar(select(CustomerBusinessProfile).where(CustomerBusinessProfile.customer_code == "C001"))
        self.assertIsNotNone(profile)
        self.assertEqual(profile.latest_update_note, "现场直接补充经营资料")
        history = self.db.scalar(select(CustomerBusinessProfileHistory).where(CustomerBusinessProfileHistory.customer_code == "C001"))
        self.assertEqual(history.snapshot_json["recommended_products"][0]["customer_feedback"], "愿意试单")

    def test_direct_business_profile_save_response_is_fastapi_serializable(self):
        result = crm_project_routes.update_crm_linked_customer_business_profile(
            "C001",
            CustomerBusinessProfileUpsert(
                confirmed_at=date(2026, 7, 16),
                update_source="现场拜访",
                update_type="新增资料",
                latest_update_note="验证保存接口响应序列化",
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )
        route = next(
            route
            for route in crm_project_routes.router.routes
            if route.path == "/crm/linked-customers/{customer_code}/business-profile/update"
            and "POST" in route.methods
        )

        self.assertIs(route.response_model, CrmBusinessProfileUpdateResponse)
        validated, errors = route.response_field.validate(result, {}, loc=("response",))
        self.assertFalse(errors)
        serialized = route.response_field.serialize(validated)
        self.assertEqual(serialized["profile"]["customer_code"], "C001")
        self.assertEqual(serialized["task_id"], self.task.id)
        self.assertTrue(serialized["synced_to_master"])

    def test_legacy_business_profile_approval_endpoint_is_retired(self):
        with self.assertRaises(HTTPException) as caught:
            create_crm_business_profile_approval_draft(
                "C001",
                CrmBusinessProfileApprovalDraftCreate(
                    submit=True,
                    profile={"latest_update_note": "旧客户端审批请求"},
                ),
                request=None,
                db=self.db,
                current_user=self.salesperson,
            )

        self.assertEqual(caught.exception.status_code, status.HTTP_410_GONE)
        self.assertIn("直接保存", str(caught.exception.detail))
        self.assertIsNone(self.db.scalar(select(ApprovalInstance).where(ApprovalInstance.approval_type == "customer_business_profile_update")))

    def test_direct_business_profile_save_updates_task_summary_as_synced(self):
        self.task.is_closed = False
        self.task.status = "not_started"
        self.db.commit()

        crm_project_routes.update_crm_linked_customer_business_profile(
            "C001",
            CustomerBusinessProfileUpsert(latest_update_note="直存后刷新任务摘要"),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

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
        self.assertIsNone(page.items[0].business_profile_approval_id)
        self.assertEqual(page.items[0].business_profile_approval_status, "synced")

    def test_direct_business_profile_save_allows_followup_approval_to_complete(self):
        self.task.is_closed = False
        self.task.status = "in_progress"
        self.db.commit()

        crm_project_routes.update_crm_linked_customer_business_profile(
            "C001",
            CustomerBusinessProfileUpsert(latest_update_note="跟进前已保存经营资料"),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )
        approval = create_crm_followup_approval_draft(
            CrmFollowupApprovalDraftCreate(
                submit=True,
                followup={
                    "project_id": self.project.id,
                    "task_id": self.task.id,
                    "followup_date": date(2026, 7, 13),
                    "method": "电话",
                    "frontline_action": "确认经营情况",
                    "customer_feedback": "资料无误",
                    "business_profile_updated": True,
                },
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

        approved = approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)
        self.assertEqual(approved.approval.status, "completed")
        followup = self.db.scalar(select(CrmFollowup).where(CrmFollowup.approval_id == approval.id))
        self.assertIsNotNone(followup)
        self.assertTrue(followup.business_profile_updated)

    def test_project_closed_removes_crm_business_profile_access(self):
        self.project.status = "closed"
        self.db.commit()

        with self.assertRaises(Exception):
            get_crm_linked_customer_business_profile(
                "C001",
                request=None,
                db=self.db,
                current_user=self.salesperson,
            )

    def test_direct_business_profile_save_marks_task_started_and_returns_flow_node(self):
        self.task.status = "not_started"
        self.task.minimum_action_done = False
        self.task.is_closed = False
        self.task.latest_owner_next_status = None
        self.db.commit()

        crm_project_routes.update_crm_linked_customer_business_profile(
            "C001",
            CustomerBusinessProfileUpsert(
                business_customer_type="餐饮",
                latest_update_note="补充经营资料",
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

        self.db.refresh(self.task)
        self.assertEqual(self.task.status, "in_progress")
        self.assertTrue(self.task.minimum_action_done)
        self.assertEqual(self.task.latest_owner_next_status, "经营资料已保存")

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
        self.assertIsNone(page.items[0].business_profile_approval_id)
        self.assertEqual(page.items[0].business_profile_approval_status, "synced")

        context = crm_project_routes.get_crm_linked_customer_context(
            "C001",
            db=self.db,
            current_user=self.salesperson,
        )
        business_node = next(node for node in context["crm"]["flow_nodes"] if node["key"] == "business_profile_approval")
        self.assertEqual(business_node["label"], "经营资料已保存")
        self.assertEqual(business_node["status"], "done")

    def test_direct_business_profile_save_keeps_visit_recommended_products_as_process_record(self):
        result = crm_project_routes.update_crm_linked_customer_business_profile(
            "C001",
            CustomerBusinessProfileUpsert(
                business_customer_type="餐饮",
                latest_update_note="本次拜访推荐新品",
                recommended_products=[
                    {
                        "product_name": "九联冻120-130g腿",
                        "spec": "120-130g",
                        "recommended_quote": "165 元/箱",
                        "recommend_reason": "客户当前腿类销量稳定，可试推同规格新品。",
                        "customer_feedback": "愿意先试 2 箱",
                        "next_action": "下次拜访带样品和报价单",
                    }
                ],
            ),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

        self.assertTrue(result["synced_to_master"])
        self.assertIn("recommended_products", result["changed_fields"])
        products = list(self.db.scalars(select(CustomerBusinessProduct).where(CustomerBusinessProduct.customer_code == "C001")).all())
        self.assertEqual(products, [])
        history = self.db.scalar(
            select(CustomerBusinessProfileHistory)
            .where(CustomerBusinessProfileHistory.customer_code == "C001")
            .order_by(CustomerBusinessProfileHistory.id.desc())
        )
        self.assertIsNotNone(history)
        self.assertEqual(history.snapshot_json["recommended_products"][0]["next_action"], "下次拜访带样品和报价单")

    def test_linked_customer_search_matches_next_action_and_returns_flow_node(self):
        self.task.is_closed = False
        self.task.status = "in_progress"
        self.task.latest_owner_next_status = "待报价"
        self.task.latest_owner_next_action = "群里正常报价，明天二次跟进"
        self.db.commit()

        page = list_crm_linked_customers_page(
            q="正常报价",
            scope=None,
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.salesperson,
        )

        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].customer_code, "C001")
        self.assertEqual(page.items[0].current_flow_node, "一线已提交跟进")
        self.assertEqual(page.items[0].blocked_reason_summary, "群里正常报价，明天二次跟进")

    def test_business_profile_permission_can_list_active_linked_customers_without_task_view(self):
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

        self.project.status = "closed"
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

    def test_linked_customer_context_includes_business_profile_for_crm_business_permission(self):
        approval_view_grant = self.db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == self.sales_role.id,
                RolePermission.permission_id == self.permissions["approval.view"].id,
            )
        )
        if approval_view_grant is not None:
            self.db.delete(approval_view_grant)
        self.db.add(
            CustomerBusinessProfile(
                customer_code="C001",
                customer_name_snapshot="吴江恒力食堂",
                business_customer_type="餐饮",
                confirmed_at=date(2026, 7, 4),
                filled_by="冯阳",
                update_source="CRM 审批",
                update_type="新增资料",
                current_salesperson="冯阳",
                latest_update_note="客户经营资料已确认",
                version_no=1,
            )
        )
        self.db.add(
            CustomerBusinessProduct(
                customer_code="C001",
                product_category="鸡产品",
                spec="腿类",
                monthly_usage="每月 20 箱",
                is_active=True,
                sort_order=1,
            )
        )
        self.db.commit()

        result = get_crm_linked_customer_context("C001", db=self.db, current_user=self.salesperson)

        self.assertIsNotNone(result["business_profile"])
        self.assertEqual(result["business_profile"]["profile"]["latest_update_note"], "客户经营资料已确认")
        self.assertEqual(result["business_profile"]["products"][0]["product_category"], "鸡产品")
        self.assertIn("flow_nodes", result["crm"])
        self.assertTrue(any(node["label"] == "任务已分配" for node in result["crm"]["flow_nodes"]))


if __name__ == "__main__":
    unittest.main()
