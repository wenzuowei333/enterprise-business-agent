import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.approvals import _approval_detail, _approval_public
from app.core.database import Base
from app.models import ApprovalAttachment, ApprovalEvent, ApprovalInstance, CustomerMaster, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ApprovalDetailBusinessSummaryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.applicant = User(
            username="sales01",
            password_hash="hash",
            real_name="一线业务员",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.landing_approver = User(
            username="landing",
            password_hash="hash",
            real_name="落地审批人",
            role="boss",
            status="active",
            is_active=True,
        )
        self.detail_approver = User(
            username="detail",
            password_hash="hash",
            real_name="细节审批人",
            role="business_middle_office",
            status="active",
            is_active=True,
        )
        self.cc_user = User(
            username="cc01",
            password_hash="hash",
            real_name="项目抄送人",
            role="business_middle_office",
            status="active",
            is_active=True,
        )
        self.customer = CustomerMaster(
            customer_code="KH001",
            customer_name="苏州示例客户",
            customer_type="普通客户",
            status="active",
        )
        self.db.add_all([
            self.applicant,
            self.landing_approver,
            self.detail_approver,
            self.cc_user,
            self.customer,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_project_application_summary_contains_business_names_and_task_assignment(self):
        approval = ApprovalInstance(
            approval_no="APPR-PROJECT-001",
            approval_type="crm_project_create",
            resource_type="crm_project",
            resource_id="pending",
            title="客户项目立项：夏季拜访",
            applicant_user_id=self.applicant.id,
            current_handler_user_id=self.landing_approver.id,
            status="submitted",
            priority="high",
            payload_json={
                "project": {
                    "project_name": "夏季拜访",
                    "project_type": "客户推进",
                    "purpose": "补齐客户资料并确认采购计划",
                    "owner_user_id": self.detail_approver.id,
                    "landing_approver_user_id": self.landing_approver.id,
                    "participant_user_ids": [self.applicant.id],
                    "progress_cc_user_ids": [self.cc_user.id],
                    "minimum_action": "完成首次电话沟通",
                    "closure_standard": "客户资料与经营资料齐全",
                },
                "tasks": [{
                    "customer_code": self.customer.customer_code,
                    "executor_user_id": self.applicant.id,
                    "business_issue_point": "缺少采购计划",
                    "round_target": "确认月采购量",
                }],
            },
        )
        self.db.add(approval)
        self.db.commit()

        public = _approval_public(self.db, approval)
        summary = public.business_summary

        self.assertEqual(summary["kind"], "crm_project_create")
        self.assertEqual(summary["project"]["project_name"], "夏季拜访")
        self.assertEqual(summary["people"]["landing_approver"], "落地审批人 / landing")
        self.assertEqual(summary["people"]["detail_approver"], "细节审批人 / detail")
        self.assertEqual(summary["people"]["progress_cc"], ["项目抄送人 / cc01"])
        self.assertEqual(summary["tasks"][0]["customer_name"], "苏州示例客户")
        self.assertEqual(summary["tasks"][0]["executor"], "一线业务员 / sales01")

    def test_followup_summary_and_detail_use_readable_user_labels(self):
        approval = ApprovalInstance(
            approval_no="APPR-FOLLOWUP-001",
            approval_type="crm_followup_submit",
            resource_type="crm_followup",
            resource_id="pending",
            title="跟进事实审核：苏州示例客户",
            applicant_user_id=self.applicant.id,
            current_handler_user_id=self.detail_approver.id,
            status="submitted",
            priority="normal",
            payload_json={
                "followup": {
                    "project_id": 99,
                    "task_id": 101,
                    "customer_code": self.customer.customer_code,
                    "method": "电话",
                    "customer_feedback": "下周确认采购计划",
                    "current_need": "需要价格表",
                    "next_action": "发送报价并回访",
                    "need_type": "价格政策",
                    "need_support": True,
                    "need_manager_support": False,
                    "need_boss_decision": False,
                    "is_closed": False,
                }
            },
        )
        self.db.add(approval)
        self.db.flush()
        self.db.add(ApprovalEvent(
            approval_id=approval.id,
            event_type="submit",
            operator_user_id=self.applicant.id,
            from_status="draft",
            to_status="submitted",
            created_at=datetime.now(timezone.utc),
        ))
        self.db.add(ApprovalAttachment(
            approval_id=approval.id,
            file_name="报价单.pdf",
            storage_path="approvals/test.pdf",
            created_by_user_id=self.applicant.id,
        ))
        self.db.commit()

        detail = _approval_detail(self.db, approval)
        summary = detail.approval.business_summary

        self.assertEqual(summary["kind"], "crm_followup_submit")
        self.assertEqual(summary["customer_name"], "苏州示例客户")
        self.assertEqual(summary["followup"]["customer_feedback"], "下周确认采购计划")
        self.assertEqual(summary["followup"]["next_action"], "发送报价并回访")
        self.assertTrue(summary["followup"]["need_support"])
        self.assertFalse(summary["followup"]["need_manager_support"])
        self.assertFalse(summary["followup"]["need_boss_decision"])
        self.assertFalse(summary["followup"]["is_closed"])
        self.assertEqual(detail.events[0].operator_user_label, "一线业务员 / sales01")
        self.assertEqual(detail.attachments[0].created_by_user_label, "一线业务员 / sales01")


if __name__ == "__main__":
    unittest.main()
