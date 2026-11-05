import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.approvals import get_approval, list_my_approval_submissions
from app.core.database import Base
from app.models import ApprovalEvent, ApprovalInstance, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ApprovalReturnFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.salesperson = User(
            username="sales-return",
            password_hash="hash",
            real_name="销售人员",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.approver = User(
            username="approver-return",
            password_hash="hash",
            real_name="细节审批人",
            role="business_middle_office",
            status="active",
            is_active=True,
        )
        self.other_user = User(
            username="other-return",
            password_hash="hash",
            real_name="其他人员",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.db.add_all([self.salesperson, self.approver, self.other_user])
        self.db.flush()

        self.supplement = self._approval("need_supplement", "APPR-SUPPLEMENT")
        self.rejected = self._approval("rejected", "APPR-REJECTED")
        self.blank_rejected = self._approval("rejected", "APPR-BLANK")
        self.resubmitted = self._approval("submitted", "APPR-RESUBMITTED")
        self.hidden = self._approval(
            "rejected",
            "APPR-HIDDEN",
            applicant_user_id=self.other_user.id,
            handler_user_id=self.other_user.id,
        )

        now = datetime.now(timezone.utc)
        self._event(self.supplement, "supplement_request", "第一次补充要求", now - timedelta(hours=2))
        self._event(self.supplement, "supplement_request", "请补充客户采购计划和联系人", now)
        self._event(self.rejected, "reject", "客户信息与任务不匹配", now)
        self._event(self.blank_rejected, "reject", None, now)
        self._event(self.resubmitted, "supplement_request", "已经处理的旧补充要求", now - timedelta(days=1))
        self._event(self.resubmitted, "supplement", "已补充并重新提交", now)
        self._event(self.hidden, "reject", "不可见原因", now)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _approval(
        self,
        status: str,
        approval_no: str,
        *,
        applicant_user_id: int | None = None,
        handler_user_id: int | None = None,
    ) -> ApprovalInstance:
        approval = ApprovalInstance(
            approval_no=approval_no,
            approval_type="generic_request",
            resource_type="generic",
            resource_id=approval_no,
            title=approval_no,
            applicant_user_id=applicant_user_id or self.salesperson.id,
            current_handler_user_id=handler_user_id or self.approver.id,
            status=status,
            priority="normal",
            payload_json={},
        )
        self.db.add(approval)
        self.db.flush()
        return approval

    def _event(
        self,
        approval: ApprovalInstance,
        event_type: str,
        comment: str | None,
        created_at: datetime,
    ) -> None:
        self.db.add(
            ApprovalEvent(
                approval_id=approval.id,
                event_type=event_type,
                operator_user_id=self.approver.id,
                from_status="under_review",
                to_status="need_supplement" if event_type == "supplement_request" else approval.status,
                comment=comment,
                created_at=created_at,
            )
        )
        self.db.flush()

    def test_my_submissions_returns_latest_current_feedback_without_scope_leak(self):
        page = list_my_approval_submissions(
            q=None,
            scope=None,
            status_value=None,
            approval_type=None,
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.salesperson,
        )

        self.assertEqual(page.total, 4)
        rows = {row.approval_no: row for row in page.items}
        supplement_feedback = rows["APPR-SUPPLEMENT"].latest_return_feedback
        self.assertIsNotNone(supplement_feedback)
        self.assertEqual(supplement_feedback.event_type, "supplement_request")
        self.assertEqual(supplement_feedback.comment, "请补充客户采购计划和联系人")
        self.assertEqual(supplement_feedback.operator_user_label, "细节审批人 / approver-return")

        rejected_feedback = rows["APPR-REJECTED"].latest_return_feedback
        self.assertIsNotNone(rejected_feedback)
        self.assertEqual(rejected_feedback.event_type, "reject")
        self.assertEqual(rejected_feedback.comment, "客户信息与任务不匹配")
        self.assertIsNone(rows["APPR-BLANK"].latest_return_feedback.comment)
        self.assertIsNone(rows["APPR-RESUBMITTED"].latest_return_feedback)
        self.assertNotIn("APPR-HIDDEN", rows)

    def test_detail_uses_same_return_feedback_as_timeline(self):
        detail = get_approval(
            self.supplement.id,
            db=self.db,
            current_user=self.salesperson,
        )

        feedback = detail.approval.latest_return_feedback
        self.assertIsNotNone(feedback)
        self.assertEqual(feedback.comment, "请补充客户采购计划和联系人")
        self.assertEqual(feedback.operator_user_id, self.approver.id)
        self.assertEqual(feedback.created_at, detail.events[-1].created_at)


if __name__ == "__main__":
    unittest.main()
