import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.approvals import _approval_public
from app.models import ApprovalInstance, User


class ApprovalUserLabelTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        User.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.applicant = User(
            username="yaolili",
            password_hash="hash",
            real_name="姚丽莉",
            role="business_middle_office",
            status="active",
            is_active=True,
        )
        self.handler = User(
            username="admin",
            password_hash="hash",
            real_name="施总",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add_all([self.applicant, self.handler])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_approval_public_includes_readable_user_labels(self):
        approval = ApprovalInstance(
            id=1,
            approval_no="APPR001",
            approval_type="crm_project_create",
            resource_type="crm_project",
            resource_id="draft-1",
            title="客户项目立项",
            applicant_user_id=self.applicant.id,
            current_handler_user_id=self.handler.id,
            status="draft",
            priority="normal",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        public = _approval_public(self.db, approval)

        self.assertEqual(public.applicant_user_label, "姚丽莉 / yaolili")
        self.assertEqual(public.current_handler_user_label, "施总 / admin")


if __name__ == "__main__":
    unittest.main()
