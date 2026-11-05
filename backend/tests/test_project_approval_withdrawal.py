import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.approvals import (
    approve_approval,
    get_approved_project_withdrawal_preview,
    supplement_approval,
    withdraw_approved_project,
)
from app.api.routes.work_items import update_work_item
from app.core.config import settings
from app.core.database import Base
from app.models import (
    ApprovalInstance,
    CrmProject,
    CrmProjectCustomerTask,
    CustomerMaster,
    Permission,
    Role,
    RolePermission,
    User,
    WorkItem,
)
from app.schemas.crm import ApprovalActionRequest, ApprovalWithdrawalRequest, WorkItemUpdate
from app.services.approval_service import create_approval_instance
from app.services.crm_project_service import ensure_project_operable


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ProjectApprovalWithdrawalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self._seed_customers()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _seed_identity(self) -> None:
        applicant_role = Role(role_code="salesperson", role_name="一线业务")
        approver_role = Role(role_code="boss", role_name="项目审批")
        admin_role = Role(role_code="admin", role_name="管理员")
        self.db.add_all([applicant_role, approver_role, admin_role])
        self.db.flush()

        codes = (
            "approval.view",
            "approval.approve",
            "crm_project.approval_withdraw",
            "crm_project.approval_withdraw_override",
        )
        permissions = {
            code: Permission(
                permission_code=code,
                permission_name=code,
                resource_type="approval" if code.startswith("approval.") else "crm_project",
                action_type="approve",
            )
            for code in codes
        }
        self.db.add_all(permissions.values())
        self.db.flush()
        for code in ("approval.view", "approval.approve", "crm_project.approval_withdraw"):
            self.db.add(RolePermission(role_id=approver_role.id, permission_id=permissions[code].id))
        for code in codes:
            self.db.add(RolePermission(role_id=admin_role.id, permission_id=permissions[code].id))

        self.applicant = User(
            username="sales01",
            password_hash="hash",
            real_name="申请人",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.approver = User(
            username="approver01",
            password_hash="hash",
            real_name="原审批人",
            role="boss",
            status="active",
            is_active=True,
        )
        self.admin = User(
            username="admin",
            password_hash="hash",
            real_name="管理员",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add_all([self.applicant, self.approver, self.admin])
        self.db.commit()

    def _seed_customers(self) -> None:
        self.db.add_all(
            [
                CustomerMaster(customer_code="C001", customer_name="客户一", customer_type="普通客户", status="active"),
                CustomerMaster(customer_code="C002", customer_name="客户二", customer_type="普通客户", status="active"),
            ]
        )
        self.db.commit()

    def _approved_project(self) -> tuple[ApprovalInstance, CrmProject]:
        approval = create_approval_instance(
            self.db,
            approval_type="crm_project_create",
            resource_type="approval_pending",
            resource_id="pending",
            title="项目申请",
            description=None,
            applicant=self.applicant,
            current_handler_user_id=self.approver.id,
            priority="normal",
            payload_json={
                "project": {
                    "project_name": "测试项目",
                    "purpose": "验证撤回审核",
                    "applicant_user_id": self.applicant.id,
                    "landing_approver_user_id": self.approver.id,
                    "owner_user_id": self.approver.id,
                    "status": "submitted",
                    "approval_status": "submitted",
                },
                "tasks": [{"customer_code": "C001", "round_target": "完成首次沟通"}],
            },
            submit=True,
        )
        self.db.commit()
        approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.approver)
        self.db.refresh(approval)
        project = self.db.get(CrmProject, int(approval.result_json["project_id"]))
        assert project is not None
        return approval, project

    def test_withdraw_freezes_and_reapproval_updates_same_project(self) -> None:
        approval, project = self._approved_project()
        original_project_id = project.id
        original_task = self.db.scalar(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project.id))
        assert original_task is not None

        with patch.object(settings, "crm_project_approval_withdraw_enabled", True):
            preview = get_approved_project_withdrawal_preview(approval.id, db=self.db, current_user=self.approver)
            self.assertTrue(preview.can_withdraw)
            self.assertEqual(preview.impact_counts["tasks"], 1)
            withdraw_approved_project(
                approval.id,
                ApprovalWithdrawalRequest(reason="审批条件需要补充确认"),
                request=None,
                db=self.db,
                current_user=self.approver,
            )

            self.db.refresh(approval)
            self.db.refresh(project)
            self.assertEqual(approval.status, "need_supplement")
            self.assertEqual(project.status, "paused")
            self.assertEqual(project.approval_status, "need_supplement")
            self.assertIsNotNone(project.approval_withdrawn_at)
            with self.assertRaises(HTTPException) as frozen:
                ensure_project_operable(project)
            self.assertEqual(frozen.exception.detail["error_code"], "PROJECT_FROZEN")

            payload = copy.deepcopy(approval.payload_json)
            payload["project"]["project_name"] = "补充后的测试项目"
            payload["tasks"][0]["round_target"] = "更新后的沟通目标"
            payload["tasks"].append({"customer_code": "C002", "round_target": "新增客户任务"})
            supplement_approval(
                approval.id,
                request=None,
                payload=ApprovalActionRequest(comment="已完成补充", payload_json=payload),
                db=self.db,
                current_user=self.applicant,
            )
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.approver)

        self.db.refresh(project)
        self.assertEqual(project.id, original_project_id)
        self.assertEqual(project.project_name, "补充后的测试项目")
        self.assertEqual(project.status, "active")
        self.assertEqual(project.approval_status, "approved")
        self.assertIsNone(project.approval_withdrawn_at)
        self.assertEqual(self.db.scalar(select(CrmProject).where(CrmProject.id == original_project_id)).id, original_project_id)
        tasks = list(self.db.scalars(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project.id)).all())
        self.assertEqual({task.customer_code for task in tasks}, {"C001", "C002"})
        self.assertEqual(next(task for task in tasks if task.customer_code == "C001").id, original_task.id)

    def test_cannot_remove_task_with_business_history(self) -> None:
        approval, project = self._approved_project()
        task = self.db.scalar(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project.id))
        assert task is not None
        self.db.add(
            WorkItem(
                item_no="WI-HISTORY",
                source_type="manual",
                source_id=str(task.id),
                resource_type="crm_project_customer_task",
                resource_id=str(task.id),
                project_id=project.id,
                customer_code=task.customer_code,
                item_type="crm_support_needed",
                title="已有支持事项",
                priority="normal",
                status="open",
            )
        )
        self.db.commit()
        with patch.object(settings, "crm_project_approval_withdraw_enabled", True):
            withdraw_approved_project(
                approval.id,
                ApprovalWithdrawalRequest(reason="需要重新核对任务范围"),
                request=None,
                db=self.db,
                current_user=self.approver,
            )
            payload = copy.deepcopy(approval.payload_json)
            payload["tasks"] = []
            with self.assertRaises(HTTPException) as conflict:
                supplement_approval(
                    approval.id,
                    request=None,
                    payload=ApprovalActionRequest(comment="删除任务", payload_json=payload),
                    db=self.db,
                    current_user=self.applicant,
                )
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(conflict.exception.detail["error_code"], "PROJECT_REAPPROVAL_CONFLICT")

    def test_admin_override_can_withdraw_after_original_window(self) -> None:
        approval, project = self._approved_project()
        approval.closed_at = datetime.now(timezone.utc) - timedelta(hours=25)
        approval.reviewed_at = approval.closed_at
        self.db.commit()
        with patch.object(settings, "crm_project_approval_withdraw_enabled", True):
            expired = get_approved_project_withdrawal_preview(approval.id, db=self.db, current_user=self.approver)
            self.assertFalse(expired.can_withdraw)
            self.assertIn("原审批人的24小时撤回时限已过", expired.blockers)
            override = get_approved_project_withdrawal_preview(approval.id, db=self.db, current_user=self.admin)
            self.assertTrue(override.can_withdraw)
            self.assertTrue(override.is_override)
            withdraw_approved_project(
                approval.id,
                ApprovalWithdrawalRequest(reason="管理员纠正历史审批结果"),
                request=None,
                db=self.db,
                current_user=self.admin,
            )
        self.db.refresh(project)
        self.assertEqual(project.approval_withdrawn_by_user_id, self.admin.id)

    def test_feature_flag_and_permission_block_withdrawal(self) -> None:
        approval, _ = self._approved_project()
        with patch.object(settings, "crm_project_approval_withdraw_enabled", False):
            disabled = get_approved_project_withdrawal_preview(approval.id, db=self.db, current_user=self.approver)
            self.assertFalse(disabled.can_withdraw)
            self.assertIn("撤回审核功能尚未启用", disabled.blockers)

        with patch.object(settings, "crm_project_approval_withdraw_enabled", True):
            unauthorized = get_approved_project_withdrawal_preview(approval.id, db=self.db, current_user=self.applicant)
            self.assertFalse(unauthorized.can_withdraw)
            with self.assertRaises(HTTPException) as denied:
                withdraw_approved_project(
                    approval.id,
                    ApprovalWithdrawalRequest(reason="申请人不能撤回已通过审核"),
                    request=None,
                    db=self.db,
                    current_user=self.applicant,
                )
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(denied.exception.detail["error_code"], "APPROVAL_WITHDRAW_NOT_ALLOWED")

    def test_duplicate_and_terminal_withdrawals_are_rejected(self) -> None:
        approval, project = self._approved_project()
        with patch.object(settings, "crm_project_approval_withdraw_enabled", True):
            withdraw_approved_project(
                approval.id,
                ApprovalWithdrawalRequest(reason="首次撤回用于确认重复请求"),
                request=None,
                db=self.db,
                current_user=self.approver,
            )
            with self.assertRaises(HTTPException) as duplicate:
                withdraw_approved_project(
                    approval.id,
                    ApprovalWithdrawalRequest(reason="重复撤回不应再次成功"),
                    request=None,
                    db=self.db,
                    current_user=self.approver,
                )
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertEqual(duplicate.exception.detail["error_code"], "PROJECT_ALREADY_WITHDRAWN")

        self.db.rollback()
        approval2, project2 = self._approved_project()
        project2.status = "closed"
        self.db.commit()
        with patch.object(settings, "crm_project_approval_withdraw_enabled", True):
            with self.assertRaises(HTTPException) as terminal:
                withdraw_approved_project(
                    approval2.id,
                    ApprovalWithdrawalRequest(reason="关闭项目不能撤回审批"),
                    request=None,
                    db=self.db,
                    current_user=self.approver,
                )
        self.assertEqual(terminal.exception.detail["error_code"], "PROJECT_TERMINAL")

    def test_reapproval_soft_cancels_unused_task_and_freezes_work_item_write(self) -> None:
        approval, project = self._approved_project()
        task = self.db.scalar(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project.id))
        assert task is not None
        item = WorkItem(
            item_no="WI-FROZEN",
            source_type="manual",
            source_id="project",
            resource_type="crm_project",
            resource_id="project",
            project_id=project.id,
            customer_code=task.customer_code,
            item_type="crm_support_needed",
            title="冻结校验事项",
            priority="normal",
            status="open",
        )
        self.db.add(item)
        self.db.commit()

        with patch.object(settings, "crm_project_approval_withdraw_enabled", True):
            withdraw_approved_project(
                approval.id,
                ApprovalWithdrawalRequest(reason="重新核对客户任务范围"),
                request=None,
                db=self.db,
                current_user=self.approver,
            )
            with self.assertRaises(HTTPException) as frozen:
                update_work_item(
                    item.id,
                    WorkItemUpdate(title="冻结期间不允许修改"),
                    request=None,
                    db=self.db,
                    current_user=self.approver,
                )
            self.assertEqual(frozen.exception.detail["error_code"], "PROJECT_FROZEN")

            payload = copy.deepcopy(approval.payload_json)
            payload["tasks"] = []
            supplement_approval(
                approval.id,
                request=None,
                payload=ApprovalActionRequest(comment="移除未开展任务", payload_json=payload),
                db=self.db,
                current_user=self.applicant,
            )
            approve_approval(approval.id, request=None, payload=None, db=self.db, current_user=self.approver)

        self.db.refresh(task)
        self.assertEqual(task.status, "cancelled")
        self.assertTrue(task.is_closed)


if __name__ == "__main__":
    unittest.main()
