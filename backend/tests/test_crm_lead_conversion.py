import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.approvals import (
    _approval_public,
    approve_approval,
    create_approval,
    request_approval_supplement,
    reject_approval,
    router as approvals_router,
    supplement_approval,
    update_approval_draft,
)
from app.api.routes.crm_leads import create_lead_conversion_approval_draft
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import ApprovalInstance, AuditLog, CrmLead, CrmProject, CustomerMaster, Permission, Role, RolePermission, User
from app.schemas.crm import ApprovalActionRequest, ApprovalCreate, ApprovalDraftUpdate, CrmLeadConversionApprovalDraftCreate
from app.services.approval_service import create_approval_instance


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CrmLeadConversionTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self.lead = self._lead("江苏恒力纺织", "13800138000")

        app = FastAPI()
        app.include_router(approvals_router, prefix="/api/v1")

        def override_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _seed_identity(self):
        sales_role = Role(role_code="salesperson", role_name="业务员")
        admin_role = Role(role_code="admin", role_name="管理员")
        lead_approver_role = Role(role_code="lead_approver", role_name="线索转正审批人")
        permissions = {
            code: Permission(permission_code=code, permission_name=code, resource_type="approval", action_type="approve")
            for code in ("crm_lead.view", "crm_lead.convert", "crm_lead.approve", "approval.approve")
        }
        self.salesperson = User(
            username="salesperson",
            password_hash="hash",
            real_name="销售员",
            employee_code="S001",
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
        self.lead_approver = User(
            username="lead-approver",
            password_hash="hash",
            real_name="线索审批人",
            employee_code="LEAD-APPROVER",
            role="lead_approver",
            status="active",
            is_active=True,
        )
        self.db.add_all([
            sales_role,
            admin_role,
            lead_approver_role,
            *permissions.values(),
            self.salesperson,
            self.admin,
            self.lead_approver,
        ])
        self.db.flush()
        self.db.add_all([
            RolePermission(role_id=sales_role.id, permission_id=permissions["crm_lead.view"].id),
            RolePermission(role_id=sales_role.id, permission_id=permissions["crm_lead.convert"].id),
            RolePermission(role_id=admin_role.id, permission_id=permissions["crm_lead.view"].id),
            RolePermission(role_id=admin_role.id, permission_id=permissions["approval.approve"].id),
            RolePermission(role_id=lead_approver_role.id, permission_id=permissions["crm_lead.approve"].id),
        ])
        self.db.commit()

    def _headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.username)}"}

    def _action_response(self, action: str, approval: ApprovalInstance, user: User):
        return self.client.post(
            f"/api/v1/approvals/{approval.id}/{action}",
            headers=self._headers(user),
        )

    def _normal_project_extension_approval(self, *, current_handler: User) -> ApprovalInstance:
        project_count = len(list(self.db.scalars(select(CrmProject.id))))
        project = CrmProject(
            project_code=f"CRMP-AUTH-{project_count + 1:03d}",
            project_name="审批权限回归项目",
            status="active",
            approval_status="approved",
            owner_user_id=self.admin.id,
            created_by_user_id=self.salesperson.id,
        )
        self.db.add(project)
        self.db.flush()
        approval = create_approval_instance(
            self.db,
            approval_type="crm_project_extension",
            resource_type="crm_project",
            resource_id=str(project.id),
            title="项目延期审批",
            description=None,
            applicant=self.salesperson,
            current_handler_user_id=current_handler.id,
            priority="normal",
            payload_json={
                "project_id": project.id,
                "requested_due_date": "2030-02-01",
                "reason": "等待客户确认",
                "progress_summary": "已完成现场沟通",
            },
            submit=True,
        )
        self.db.commit()
        return approval

    def _lead(self, lead_name: str, contact_phone: str) -> CrmLead:
        normalized_name = "".join(character for character in lead_name.casefold() if character.isalnum())
        lead_count = len(list(self.db.scalars(select(CrmLead.id))))
        lead = CrmLead(
            lead_no=f"LEAD-{lead_count + 1}",
            lead_name=lead_name,
            normalized_name=normalized_name,
            company_name=lead_name,
            contact_name="王经理",
            contact_phone=contact_phone,
            normalized_phone=contact_phone,
            source="展会",
            region="苏州",
            address="苏州市工业园区星湖街88号",
            customer_group_name="苏州纺织客户群",
            business_line="包装",
            intent_summary="需要帆布袋样品",
            status="qualified",
            owner_user_id=self.salesperson.id,
            assigned_user_id=self.salesperson.id,
            created_by_user_id=self.salesperson.id,
            updated_by_user_id=self.salesperson.id,
        )
        self.db.add(lead)
        self.db.commit()
        return lead

    def _draft(self, *, lead: CrmLead | None = None, submit: bool = True) -> ApprovalInstance:
        lead = lead or self.lead
        return create_lead_conversion_approval_draft(
            lead.id,
            CrmLeadConversionApprovalDraftCreate(submit=submit, note="客户已确认合作意向"),
            request=None,
            db=self.db,
            current_user=self.salesperson,
        )

    def test_draft_keeps_customer_master_empty_until_approval(self):
        approval = self._draft()

        self.assertEqual(approval.approval_type, "crm_lead_convert")
        self.assertEqual(approval.status, "submitted")
        self.assertEqual(approval.current_handler_user_id, self.admin.id)
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)
        self.assertEqual(self.db.get(CrmLead, self.lead.id).status, "conversion_pending")
        self.assertEqual(approval.payload_json["before"]["status"], "qualified")
        self.assertEqual(approval.payload_json["after"]["status"], "converted")

    def test_generic_approval_creation_rejects_lead_conversion_type(self):
        with self.assertRaises(HTTPException) as error:
            create_approval(
                ApprovalCreate(
                    approval_type="crm_lead_convert",
                    resource_type="crm_lead",
                    resource_id=str(self.lead.id),
                    title="Bypass lead conversion approval",
                ),
                request=None,
                db=self.db,
                current_user=self.salesperson,
            )

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("conversion-approval-draft", str(error.exception.detail))
        self.assertEqual(self.db.scalar(select(ApprovalInstance)), None)

    def test_conversion_draft_acquires_a_per_lead_transaction_lock_before_creation(self):
        with patch("app.api.routes.crm_leads.acquire_lead_conversion_draft_lock") as acquire_lock:
            self._draft()

        acquire_lock.assert_called_once_with(self.db, lead_id=self.lead.id)

    def test_rejection_and_supplement_request_do_not_write_customer_master(self):
        rejected = self._draft()
        reject_approval(rejected.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(self.db.get(ApprovalInstance, rejected.id).status, "rejected")
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)
        self.assertEqual(self.db.get(CrmLead, self.lead.id).converted_customer_code, None)

        supplement = self._draft()
        request_approval_supplement(supplement.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(self.db.get(ApprovalInstance, supplement.id).status, "need_supplement")
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)
        self.assertEqual(self.db.get(CrmLead, self.lead.id).converted_customer_code, None)

    def test_approval_creates_customer_marks_lead_converted_and_returns_project_prefill(self):
        approval = self._draft()
        detail = approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        customer = self.db.scalar(select(CustomerMaster))
        lead = self.db.get(CrmLead, self.lead.id)
        result = detail.approval.result_json
        expected_code = f"KHCRM{datetime.now(timezone.utc):%Y%m%d}{self.lead.id:06d}"
        self.assertEqual(customer.customer_code, expected_code)
        self.assertEqual(customer.customer_name, self.lead.company_name)
        self.assertEqual(customer.address, self.lead.address)
        self.assertEqual(customer.customer_group_name, self.lead.customer_group_name)
        self.assertEqual(lead.status, "converted")
        self.assertEqual(lead.converted_customer_code, expected_code)
        self.assertEqual(result["customer_code"], expected_code)
        self.assertEqual(result["master_resource_type"], "customer")
        self.assertEqual(result["master_resource_id"], expected_code)
        self.assertIsNotNone(result["synced_at"])
        self.assertEqual(result["project_prefill"]["customer_code"], expected_code)
        self.assertEqual(self.db.scalar(select(CrmProject)), None)

    def test_repeated_approval_cannot_create_a_duplicate_customer(self):
        approval = self._draft()
        approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        with self.assertRaises(HTTPException) as error:
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(list(self.db.scalars(select(CustomerMaster)))), 1)

    def test_duplicate_master_is_rechecked_during_approval_under_conversion_flow(self):
        approval = self._draft()
        self.db.add(
            CustomerMaster(
                customer_code="EXISTING-001",
                customer_name=self.lead.company_name,
                contact_phone=self.lead.contact_phone,
                status="active",
            )
        )
        self.db.commit()

        with self.assertRaises(HTTPException) as error:
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(list(self.db.scalars(select(CustomerMaster)))), 1)
        self.assertEqual(self.db.get(CrmLead, self.lead.id).status, "conversion_pending")

    def test_conversion_rejects_normalized_company_name_already_in_customer_master(self):
        self.lead.lead_name = "陈经理"
        self.lead.company_name = "苏州恒力纺织有限公司"
        self.lead.normalized_name = "陈经理"
        self.lead.contact_phone = "13900000011"
        self.lead.normalized_phone = "13900000011"
        self.db.add(CustomerMaster(customer_code="C001", customer_name="苏州 恒力 纺织 有限公司", status="active"))
        self.db.commit()
        approval = self._draft()

        with self.assertRaises(HTTPException) as error:
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(list(self.db.scalars(select(CustomerMaster)))), 1)
        self.assertEqual(self.db.get(CrmLead, self.lead.id).status, "conversion_pending")

    def test_duplicate_lead_is_rechecked_during_approval(self):
        approval = self._draft()
        self._lead(self.lead.lead_name, self.lead.contact_phone)

        with self.assertRaises(HTTPException) as error:
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)
        self.assertEqual(self.db.get(CrmLead, self.lead.id).status, "conversion_pending")

    def test_customer_code_collision_retries_with_a_suffix(self):
        approval = self._draft()
        base_code = f"KHCRM{datetime.now(timezone.utc):%Y%m%d}{self.lead.id:06d}"
        self.db.add(CustomerMaster(customer_code=base_code, customer_name="Unrelated customer", status="active"))
        self.db.commit()

        detail = approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(detail.approval.result_json["customer_code"], f"{base_code}-1")
        self.assertEqual(len(list(self.db.scalars(select(CustomerMaster)))), 2)

    def test_approval_result_keeps_server_generated_conversion_identifiers(self):
        approval = self._draft()

        detail = approve_approval(
            approval.id,
            request=None,
            payload=ApprovalActionRequest(result_json={"customer_code": "OVERRIDDEN", "master_resource_id": "OVERRIDDEN"}),
            db=self.db,
            current_user=self.admin,
        )

        customer = self.db.scalar(select(CustomerMaster))
        self.assertEqual(detail.approval.result_json["customer_code"], customer.customer_code)
        self.assertEqual(detail.approval.result_json["master_resource_id"], customer.customer_code)

    def test_draft_payload_cannot_retarget_a_conversion_to_another_pending_lead(self):
        approval = self._draft(submit=False)
        other_lead = self._lead("苏州新客户", "13900000002")
        self._draft(lead=other_lead)

        retargeted_payload = {**approval.payload_json, "lead_id": other_lead.id}
        with self.assertRaises(HTTPException) as error:
            update_approval_draft(
                approval.id,
                ApprovalDraftUpdate(payload_json=retargeted_payload),
                request=None,
                db=self.db,
                current_user=self.salesperson,
            )

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)
        self.assertEqual(self.db.get(CrmLead, other_lead.id).status, "conversion_pending")

    def test_draft_payload_must_remain_a_conversion_object(self):
        approval = self._draft(submit=False)

        with self.assertRaises(HTTPException) as error:
            update_approval_draft(
                approval.id,
                ApprovalDraftUpdate(payload_json=["not", "a", "conversion"]),
                request=None,
                db=self.db,
                current_user=self.salesperson,
            )

        self.assertEqual(error.exception.status_code, 400)

    def test_supplement_payload_cannot_retarget_a_conversion_to_another_pending_lead(self):
        approval = self._draft()
        other_lead = self._lead("无锡新客户", "13900000003")
        self._draft(lead=other_lead)
        request_approval_supplement(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        retargeted_payload = {**approval.payload_json, "lead_id": other_lead.id}
        with self.assertRaises(HTTPException) as error:
            supplement_approval(
                approval.id,
                request=None,
                payload=ApprovalActionRequest(payload_json=retargeted_payload),
                db=self.db,
                current_user=self.salesperson,
            )

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)
        self.assertEqual(self.db.get(CrmLead, other_lead.id).status, "conversion_pending")

    def test_executor_rejects_a_payload_snapshot_bound_to_another_lead(self):
        approval = self._draft()
        other_lead = self._lead("上海新客户", "13900000004")
        self._draft(lead=other_lead)
        approval.payload_json = {**approval.payload_json, "lead_id": other_lead.id}
        self.db.commit()

        with self.assertRaises(HTTPException) as error:
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)
        self.assertEqual(self.db.get(CrmLead, other_lead.id).status, "conversion_pending")

    def test_executor_rejects_a_before_snapshot_bound_to_another_lead(self):
        approval = self._draft()
        other_lead = self._lead("南京新客户", "13900000006")
        approval.payload_json = {
            **approval.payload_json,
            "before": {**approval.payload_json["before"], "id": other_lead.id},
        }
        self.db.commit()

        with self.assertRaises(HTTPException) as error:
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)

    def test_conversion_rejects_a_non_lead_approval_resource_binding(self):
        approval = self._draft()
        approval.resource_type = "customer"
        self.db.commit()

        with self.assertRaises(HTTPException) as error:
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)

    def test_conversion_rejects_an_approval_resource_id_for_another_lead(self):
        approval = self._draft()
        other_lead = self._lead("常州新客户", "13900000005")
        approval.resource_id = str(other_lead.id)
        self.db.commit()

        with self.assertRaises(HTTPException) as error:
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.scalar(select(CustomerMaster)), None)

    def test_lead_approver_can_act_on_assigned_lead_conversion_for_each_action(self):
        expected_statuses = {
            "approve": "completed",
            "reject": "rejected",
            "supplement-request": "need_supplement",
        }
        for action, expected_status in expected_statuses.items():
            with self.subTest(action=action):
                lead = self._lead(f"线索审批-{action}", f"13900000{len(action):03d}")
                approval = self._draft(lead=lead)
                approval.current_handler_user_id = self.lead_approver.id
                self.db.commit()

                response = self._action_response(action, approval, self.lead_approver)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.db.get(ApprovalInstance, approval.id).status, expected_status)
                if action == "approve":
                    self.assertEqual(self.db.get(CrmLead, lead.id).status, "converted")

    def test_lead_approver_cannot_act_on_other_approval_types(self):
        for action in ("approve", "reject", "supplement-request"):
            with self.subTest(action=action):
                approval = self._normal_project_extension_approval(current_handler=self.lead_approver)
                approval.payload_json = {**approval.payload_json, "internal_secret": "do-not-leak"}
                self.db.commit()

                response = self._action_response(action, approval, self.lead_approver)

                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.db.get(ApprovalInstance, approval.id).status, "submitted")
                self.assertNotIn("do-not-leak", response.text)

    def test_broad_approver_can_act_on_each_approval_action(self):
        expected_statuses = {
            "approve": "completed",
            "reject": "rejected",
            "supplement-request": "need_supplement",
        }
        for action, expected_status in expected_statuses.items():
            with self.subTest(action=action):
                approval = self._normal_project_extension_approval(current_handler=self.admin)

                response = self._action_response(action, approval, self.admin)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.db.get(ApprovalInstance, approval.id).status, expected_status)

    def test_non_handler_lead_approver_cannot_act_on_conversion(self):
        for action in ("approve", "reject", "supplement-request"):
            with self.subTest(action=action):
                lead = self._lead(f"非当前处理人-{action}", f"13800000{len(action):03d}")
                approval = self._draft(lead=lead)
                approval.payload_json = {**approval.payload_json, "internal_secret": "do-not-leak"}
                self.db.commit()

                response = self._action_response(action, approval, self.lead_approver)

                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.db.get(ApprovalInstance, approval.id).status, "submitted")
                self.assertNotIn("do-not-leak", response.text)

    def test_no_action_permission_gets_identical_response_for_existing_and_missing_ids(self):
        for action in ("approve", "reject", "supplement-request"):
            with self.subTest(action=action):
                approval = self._normal_project_extension_approval(current_handler=self.admin)

                existing_response = self._action_response(action, approval, self.salesperson)
                missing_response = self.client.post(
                    f"/api/v1/approvals/{approval.id + 10000}/{action}",
                    headers=self._headers(self.salesperson),
                )

                self.assertEqual(existing_response.status_code, 403)
                self.assertEqual(missing_response.status_code, 403)
                self.assertEqual(existing_response.json(), missing_response.json())
                self.assertEqual(self.db.get(ApprovalInstance, approval.id).status, "submitted")

    def test_lead_approval_action_routes_preserve_invalid_state_validation(self):
        for action in ("approve", "reject", "supplement-request"):
            with self.subTest(action=action):
                lead = self._lead(f"无效状态-{action}", f"13700000{len(action):03d}")
                approval = self._draft(lead=lead, submit=False)
                approval.current_handler_user_id = self.lead_approver.id
                self.db.commit()

                response = self._action_response(action, approval, self.lead_approver)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.db.get(ApprovalInstance, approval.id).status, "draft")

    def test_approval_result_and_audit_are_business_readable(self):
        approval = self._draft()
        detail = approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.admin)

        public = _approval_public(self.db, self.db.get(ApprovalInstance, approval.id))
        audit = self.db.scalar(
            select(AuditLog)
            .where(AuditLog.action_type == "approve_crm_lead_convert")
            .order_by(AuditLog.id.desc())
        )
        self.assertEqual(public.business_summary["lead_name"], self.lead.lead_name)
        self.assertEqual(public.business_summary["customer_code"], detail.approval.result_json["customer_code"])
        self.assertEqual(audit.before_data["lead"]["status"], "conversion_pending")
        self.assertEqual(audit.after_data["lead"]["status"], "converted")
        self.assertEqual(audit.after_data["customer"]["customer_name"], self.lead.company_name)


if __name__ == "__main__":
    unittest.main()
