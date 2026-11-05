import unittest

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.master_data import list_customers_page
from app.core.database import Base
from app.models import CrmProject, CrmProjectCustomerTask, CustomerBusinessProfile, CustomerMaster, Permission, Role, RolePermission, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CustomerMasterCrmSummaryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self._seed_data()

    def tearDown(self):
        self.db.close()

    def _seed_identity(self):
        role = Role(role_code="admin", role_name="管理员")
        permission = Permission(
            permission_code="customer.view",
            permission_name="查看客户",
            resource_type="customer",
            action_type="view",
        )
        self.user = User(
            username="admin",
            password_hash="hash",
            real_name="施总",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add_all([role, permission, self.user])
        self.db.flush()
        self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        self.db.commit()

    def _seed_data(self):
        assigned_customer = CustomerMaster(
            customer_code="C001",
            customer_name="已分配客户",
            contact_name="张三",
            contact_phone="13900000001",
            address="苏州",
            customer_group_name="客户群",
            status="active",
        )
        missing_customer = CustomerMaster(
            customer_code="C002",
            customer_name="缺资料客户",
            status="active",
        )
        project = CrmProject(
            project_code="CRM001",
            project_name="客户拜访项目",
            status="active",
            approval_status="approved",
            owner_user_id=self.user.id,
            created_by_user_id=self.user.id,
        )
        self.db.add_all([assigned_customer, missing_customer, project])
        self.db.flush()
        self.db.add(
            CrmProjectCustomerTask(
                project_id=project.id,
                task_code="TASK001",
                customer_code="C001",
                customer_name_snapshot="已分配客户",
                executor_user_id=self.user.id,
                executor_name_snapshot="施总",
                status="in_progress",
            )
        )
        self.db.add(
            CustomerBusinessProfile(
                customer_code="C001",
                customer_name_snapshot="已分配客户",
                business_customer_type="餐饮",
                version_no=1,
            )
        )
        self.db.commit()

    def test_customer_page_returns_crm_assignment_summary_and_missing_field_filters(self):
        assigned_page = list_customers_page(
            q=None,
            category_path=None,
            portrait_scale=None,
            portrait_payment_level=None,
            portrait_category=None,
            portrait_margin=None,
            portrait_return=None,
            portrait_growth=None,
            customer_tags=None,
            assignment_scope="assigned",
            missing_phone=None,
            missing_contact=None,
            missing_address=None,
            missing_group=None,
            missing_business_profile=None,
            missing_business_products=None,
            second_assignment_candidate=None,
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(assigned_page["total"], 1)
        assigned = assigned_page["items"][0]
        self.assertEqual(assigned["customer_code"], "C001")
        self.assertEqual(assigned["crm_project_count"], 1)
        self.assertEqual(assigned["crm_active_project_count"], 1)
        self.assertEqual(assigned["latest_crm_project_name"], "客户拜访项目")

        missing_page = list_customers_page(
            q=None,
            category_path=None,
            portrait_scale=None,
            portrait_payment_level=None,
            portrait_category=None,
            portrait_margin=None,
            portrait_return=None,
            portrait_growth=None,
            customer_tags=None,
            assignment_scope="unassigned",
            missing_phone=True,
            missing_contact=True,
            missing_address=True,
            missing_group=True,
            missing_business_profile=True,
            missing_business_products=None,
            second_assignment_candidate=None,
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(missing_page["total"], 1)
        missing = missing_page["items"][0]
        self.assertEqual(missing["customer_code"], "C002")
        self.assertIn("缺电话", missing["missing_fields"])
        self.assertIn("缺联系人", missing["missing_fields"])
        self.assertIn("缺地址", missing["missing_fields"])
        self.assertIn("缺客户群", missing["missing_fields"])
        self.assertIn("缺经营资料", missing["missing_fields"])


if __name__ == "__main__":
    unittest.main()
