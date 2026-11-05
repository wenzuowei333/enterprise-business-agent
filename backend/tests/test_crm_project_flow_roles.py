import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.crm_projects import create_crm_project_approval_draft, update_crm_project
from app.core.database import Base
from app.models import CrmProject, CustomerMaster, DataScopeRule, EmployeeProfile, Permission, Role, RolePermission, User
from app.schemas.crm import CrmProjectApprovalDraftCreate, CrmProjectUpdate


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmProjectFlowRolesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self._seed_customer()

    def tearDown(self):
        self.db.close()

    def _seed_identity(self):
        role = Role(role_code="business_middle_office", role_name="业务中台")
        permission = Permission(
            permission_code="crm_project.create",
            permission_name="创建 CRM 项目",
            resource_type="crm_project",
            action_type="create",
        )
        self.applicant = User(
            username="yaolili",
            password_hash="hash",
            real_name="姚丽莉",
            employee_code="YLL001",
            role="business_middle_office",
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
        self.landing_approver = User(
            username="landing",
            password_hash="hash",
            real_name="落地审批",
            employee_code="LD001",
            role="boss",
            status="active",
            is_active=True,
        )
        self.detail_approver = User(
            username="detail",
            password_hash="hash",
            real_name="细节审批",
            employee_code="XD001",
            role="business_middle_office",
            status="active",
            is_active=True,
        )
        self.frontline = User(
            username="sales01",
            password_hash="hash",
            real_name="一线业务",
            employee_code="S001",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.cc_user = User(
            username="cc01",
            password_hash="hash",
            real_name="进展抄送",
            employee_code="CC001",
            role="business_middle_office",
            status="active",
            is_active=True,
        )
        self.db.add_all([
            role,
            permission,
            self.applicant,
            self.admin,
            self.landing_approver,
            self.detail_approver,
            self.frontline,
            self.cc_user,
        ])
        self.db.flush()
        self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        self.db.add(
            DataScopeRule(
                subject_type="user",
                subject_id=str(self.cc_user.id),
                resource_type="crm_project",
                scope_mode="all",
                scope_value=None,
                is_active=True,
            )
        )
        self.db.add(
            EmployeeProfile(
                employee_code=self.frontline.employee_code,
                employee_name=self.frontline.real_name,
                status="active",
            )
        )
        self.db.commit()

    def _seed_customer(self):
        self.customer = CustomerMaster(
            customer_code="C001",
            customer_name="测试客户",
            customer_type="普通客户",
            region="苏州",
            status="active",
        )
        self.db.add(self.customer)
        self.db.commit()

    def test_project_application_uses_selected_landing_approver_and_keeps_flow_roles(self):
        approval = create_crm_project_approval_draft(
            CrmProjectApprovalDraftCreate(
                submit=True,
                priority="normal",
                project={
                    "project_name": "客户拜访流程项目",
                    "owner_user_id": self.detail_approver.id,
                    "landing_approver_user_id": self.landing_approver.id,
                    "participant_user_ids": [self.frontline.id],
                    "progress_cc_user_ids": [self.cc_user.id],
                    "status": "submitted",
                    "approval_status": "submitted",
                },
                tasks=[
                    {
                        "customer_code": self.customer.customer_code,
                        "executor_user_id": self.frontline.id,
                    }
                ],
            ),
            request=None,
            db=self.db,
            current_user=self.applicant,
        )

        self.assertEqual(approval.current_handler_user_id, self.landing_approver.id)
        project_payload = approval.payload_json["project"]
        self.assertEqual(project_payload["applicant_user_id"], self.applicant.id)
        self.assertEqual(project_payload["owner_user_id"], self.detail_approver.id)
        self.assertEqual(project_payload["landing_approver_user_id"], self.landing_approver.id)
        self.assertEqual(project_payload["participant_user_ids"], [self.frontline.id])
        self.assertEqual(project_payload["progress_cc_user_ids"], [self.cc_user.id])

    def test_progress_cc_user_can_see_but_cannot_edit_project(self):
        project = CrmProject(
            project_code="CRMP-CC-001",
            project_name="抄送只读项目",
            applicant_user_id=self.applicant.id,
            landing_approver_user_id=self.landing_approver.id,
            owner_user_id=self.detail_approver.id,
            participant_user_ids=[self.frontline.id],
            progress_cc_user_ids=[self.cc_user.id],
            created_by_user_id=self.applicant.id,
            updated_by_user_id=self.applicant.id,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)

        with self.assertRaises(HTTPException) as caught:
            update_crm_project(
                project.id,
                CrmProjectUpdate(project_name="抄送人误改"),
                request=None,
                db=self.db,
                current_user=self.cc_user,
            )

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "项目进展抄送人只能查看项目进展，不能修改项目")


if __name__ == "__main__":
    unittest.main()
