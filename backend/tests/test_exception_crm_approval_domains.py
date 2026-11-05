import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.exceptions import router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import (
    ApprovalEvent,
    ApprovalInstance,
    AuditLog,
    CrmFollowup,
    CrmProjectCustomerTask,
    DataScopeRule,
    ExceptionBackgroundJob,
    ExceptionCase,
    ExceptionDiagnosisJob,
    ExceptionEvent,
    ExceptionEvidence,
    ExceptionNotification,
    ExceptionPolicy,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.services.exception_center_service import (
    _approval_candidates,
    _crm_followup_candidates,
    _crm_task_candidates,
    create_diagnosis_job,
    enqueue_due_ai_diagnoses,
    enqueue_incremental_exception_scan_safely,
    run_incremental_exception_scan,
    scoped_exception_stmt,
    serialize_case,
    sync_exception_cases,
)
from app.services.exception_task_service import enqueue_incremental_scan, execute_diagnosis_job


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ExceptionCrmApprovalDomainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.SessionLocal()

        self.roles = {
            code: Role(role_code=code, role_name=code)
            for code in (
                "business_middle_office",
                "sales",
                "policy_admin",
                "shadow_reviewer",
                "shadow_approval_handler",
            )
        }
        self.db.add_all(self.roles.values())
        self.db.flush()
        self.owner = self._user("exception-owner", "business_middle_office")
        self.sales_one = self._user("exception-sales-one", "sales", employee_code="E-001")
        self.sales_two = self._user("exception-sales-two", "sales", employee_code="E-002")
        self.policy_admin = self._user("exception-policy-admin", "policy_admin")
        self.shadow_reviewer = self._user(
            "exception-shadow-reviewer",
            "shadow_reviewer",
            employee_code="E-003",
        )
        self.shadow_approval_handler = self._user(
            "exception-shadow-approval-handler",
            "shadow_approval_handler",
            employee_code="E-004",
        )
        for code in ("exception_center.view", "crm_task.view", "crm_followup.view", "approval.view"):
            self._grant(self.roles["sales"], code)
        for code in ("exception_center.view", "exception_center.policy_manage"):
            self._grant(self.roles["policy_admin"], code)
        for code in (
            "exception_center.view",
            "exception_center.policy_manage",
            "crm_task.view",
            "crm_followup.view",
            "approval.view",
        ):
            self._grant(self.roles["shadow_reviewer"], code)
        for code in (
            "exception_center.view",
            "exception_center.policy_manage",
            "approval.approve",
        ):
            self._grant(self.roles["shadow_approval_handler"], code)
        self.db.add_all(
            [
                DataScopeRule(
                    subject_type="role",
                    subject_id="sales",
                    resource_type="crm_task",
                    scope_mode="own",
                ),
                DataScopeRule(
                    subject_type="role",
                    subject_id="sales",
                    resource_type="crm_followup",
                    scope_mode="own",
                ),
                DataScopeRule(
                    subject_type="role",
                    subject_id="sales",
                    resource_type="approval",
                    scope_mode="own",
                ),
                DataScopeRule(
                    subject_type="role",
                    subject_id="shadow_reviewer",
                    resource_type="crm_task",
                    scope_mode="own",
                ),
                DataScopeRule(
                    subject_type="role",
                    subject_id="shadow_reviewer",
                    resource_type="crm_followup",
                    scope_mode="own",
                ),
                DataScopeRule(
                    subject_type="role",
                    subject_id="shadow_reviewer",
                    resource_type="approval",
                    scope_mode="own",
                ),
            ]
        )
        self.policy = ExceptionPolicy(
            policy_key="default",
            is_enabled=True,
            manual_ai_enabled=True,
            scheduled_ai_enabled=False,
            full_scan_enabled=False,
            digest_enabled=False,
            manual_ai_daily_limit=100,
            scheduled_ai_daily_limit=0,
            scheduled_ai_batch_limit=50,
            ai_concurrency=1,
            stale_diagnosis_hours=24,
            settings_json={"domain_modes": {"crm": "shadow", "approval": "shadow"}},
        )
        self.db.add(self.policy)
        self.db.commit()

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.shadow_headers = {
            "Authorization": f"Bearer {create_access_token(self.shadow_reviewer.username)}"
        }

    def tearDown(self) -> None:
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def _user(self, username: str, role: str, *, employee_code: str | None = None) -> User:
        user = User(
            username=username,
            password_hash="hash",
            real_name=username,
            employee_code=employee_code,
            role=role,
            status="active",
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        return user

    def _grant(self, role: Role, code: str) -> None:
        permission = self.db.scalar(select(Permission).where(Permission.permission_code == code))
        if permission is None:
            permission = Permission(
                permission_code=code,
                permission_name=code,
                resource_type=code.split(".", 1)[0],
                action_type=code.rsplit(".", 1)[-1],
            )
            self.db.add(permission)
            self.db.flush()
        self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))

    def _task(
        self,
        suffix: str,
        *,
        project_id: int = 10,
        customer_code: str | None = None,
        status: str = "not_started",
        is_closed: bool = False,
        executor: User | None = None,
    ) -> CrmProjectCustomerTask:
        task = CrmProjectCustomerTask(
            project_id=project_id,
            task_code=f"TASK-{suffix}",
            customer_code=customer_code or f"C-{suffix}",
            customer_name_snapshot=f"Sensitive customer {suffix}",
            executor_user_id=executor.id if executor else None,
            executor_employee_code=executor.employee_code if executor else None,
            executor_name_snapshot=f"Sensitive executor {suffix}",
            business_issue_point="Sensitive business issue",
            round_target="Sensitive round target",
            status=status,
            need_support=True,
            is_blocked=True,
            is_closed=is_closed,
        )
        self.db.add(task)
        self.db.flush()
        return task

    def _followup(
        self,
        suffix: str,
        *,
        task_id: int,
        project_id: int,
        customer_code: str,
        executor: User | None = None,
    ) -> CrmFollowup:
        row = CrmFollowup(
            followup_no=f"FOLLOW-{suffix}",
            project_id=project_id,
            task_id=task_id,
            customer_code=customer_code,
            executor_user_id=executor.id if executor else None,
            executor_name_snapshot=f"Sensitive executor {suffix}",
            followup_date=date(2026, 7, 29),
            frontline_action="Sensitive frontline action",
            customer_feedback="Sensitive customer feedback",
            current_need="Sensitive current need",
            review_note="Sensitive review note",
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _approval(
        self,
        suffix: str,
        *,
        status: str,
        reviewed_at: datetime | None,
        closed_at: datetime | None,
        applicant: User | None = None,
    ) -> ApprovalInstance:
        row = ApprovalInstance(
            approval_no=f"APPROVAL-{suffix}",
            approval_type="crm_followup_submit",
            resource_type="crm_project",
            resource_id=suffix,
            title=f"Sensitive title {suffix}",
            description="Sensitive description",
            applicant_user_id=applicant.id if applicant else None,
            status=status,
            payload_json={"secret": "payload"},
            result_json={"secret": "result"},
            reviewed_at=reviewed_at,
            closed_at=closed_at,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _state_event(
        self,
        approval: ApprovalInstance,
        to_status: str | None,
        *,
        created_at: datetime,
    ) -> ApprovalEvent:
        event = ApprovalEvent(
            approval_id=approval.id,
            event_type="transition",
            from_status="under_review",
            to_status=to_status,
            comment="Sensitive event comment",
            snapshot_json={"secret": "snapshot"},
            created_at=created_at,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def _set_modes(self, *, crm: str, approval: str) -> None:
        self.policy.settings_json = {"domain_modes": {"crm": crm, "approval": approval}}
        self.db.commit()

    def test_task_rule_only_flags_close_state_mismatches(self) -> None:
        first = self._task("CLOSED-FLAG-FALSE", status="closed", is_closed=False)
        second = self._task("OPEN-FLAG-TRUE", status="paused", is_closed=True)
        self._task("CLOSED-CONSISTENT", status="closed", is_closed=True)
        self._task("OPEN-CONSISTENT", status="paused", is_closed=False)
        self.db.commit()

        rows = _crm_task_candidates(self.db)

        self.assertEqual({row["resource_id"] for row in rows}, {str(first.id), str(second.id)})
        self.assertEqual(len({row["fingerprint"] for row in rows}), 2)
        evidence = rows[0]["evidence"]
        self.assertEqual(
            set(evidence),
            {"kind", "task_id", "task_code", "project_id", "customer_code", "status", "is_closed", "updated_at"},
        )
        self.assertNotIn("business_issue_point", str(evidence))
        self.assertNotIn("executor", str(evidence))
        self.assertIn("task_id=", rows[0]["action_path"])

    def test_followup_rule_flags_only_task_project_customer_binding(self) -> None:
        task = self._task("FOLLOWUP-TASK", project_id=20, customer_code="C-20", executor=self.sales_one)
        self._followup("MATCH", task_id=task.id, project_id=20, customer_code="C-20", executor=self.sales_two)
        project_mismatch = self._followup(
            "PROJECT-MISMATCH", task_id=task.id, project_id=21, customer_code="C-20", executor=self.sales_one
        )
        customer_mismatch = self._followup(
            "CUSTOMER-MISMATCH", task_id=task.id, project_id=20, customer_code="C-21", executor=self.sales_one
        )
        missing_task = self._followup(
            "MISSING-TASK", task_id=999999, project_id=20, customer_code="C-20", executor=self.sales_one
        )
        self.db.commit()

        rows = _crm_followup_candidates(self.db)

        self.assertEqual(
            {row["resource_id"] for row in rows},
            {str(project_mismatch.id), str(customer_mismatch.id), str(missing_task.id)},
        )
        evidence_text = str(rows[0]["evidence"])
        for sensitive in ("customer_feedback", "frontline_action", "current_need", "review_note", "executor"):
            self.assertNotIn(sensitive, evidence_text)

    def test_approval_rule_uses_latest_state_event_and_ignores_nonterminal_work(self) -> None:
        now = datetime.now(timezone.utc)
        valid = self._approval("VALID", status="approved", reviewed_at=now, closed_at=now)
        self._state_event(valid, "approved", created_at=now)
        missing_review = self._approval("MISSING-REVIEW", status="rejected", reviewed_at=None, closed_at=now)
        self._state_event(missing_review, "rejected", created_at=now)
        missing_close = self._approval("MISSING-CLOSE", status="cancelled", reviewed_at=now, closed_at=None)
        self._state_event(missing_close, "cancelled", created_at=now)
        no_event = self._approval("NO-EVENT", status="completed", reviewed_at=now, closed_at=now)
        mismatch = self._approval("EVENT-MISMATCH", status="rejected", reviewed_at=now, closed_at=now)
        self._state_event(mismatch, "approved", created_at=now)
        latest_tie = self._approval("LATEST-TIE", status="rejected", reviewed_at=now, closed_at=now)
        self._state_event(latest_tie, "approved", created_at=now)
        self._state_event(latest_tie, "rejected", created_at=now)
        self._approval("SUPPLEMENT", status="need_supplement", reviewed_at=None, closed_at=None)
        self.db.commit()

        rows = _approval_candidates(self.db)

        self.assertEqual(
            {row["resource_id"] for row in rows},
            {str(missing_review.id), str(missing_close.id), str(no_event.id), str(mismatch.id)},
        )
        self.assertNotIn(str(valid.id), {row["resource_id"] for row in rows})
        self.assertNotIn(str(latest_tie.id), {row["resource_id"] for row in rows})
        evidence_text = str(rows[0]["evidence"])
        for sensitive in ("payload", "result", "title", "description", "comment", "snapshot"):
            self.assertNotIn(sensitive, evidence_text)

    def test_explicit_shadow_baseline_then_incremental_new_and_reopened_stays_silent(self) -> None:
        task = self._task("LIFECYCLE", status="closed", is_closed=False)
        self.db.commit()

        created = sync_exception_cases(
            self.db,
            domains={"crm"},
            scan_trigger="baseline",
        )
        case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.resource_id == str(task.id)))
        self.assertEqual(created["created"], 1)
        self.assertEqual((case.occurrence_type, case.occurrence_cycle), ("baseline", 0))
        self.assertEqual(self.db.scalars(select(ExceptionNotification)).all(), [])
        self.policy.settings_json = {
            "domain_modes": {"crm": "shadow", "approval": "shadow"},
            "domain_rollout": {
                "crm": {
                    "shadow_cycle": 1,
                    "shadow_started_at": datetime.now(timezone.utc).isoformat(),
                    "baseline_completed_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        }
        self.db.commit()

        task.status = "paused"
        task.is_closed = True
        self.db.flush()
        previous_evidence = case.evidence_version
        run_incremental_exception_scan(
            self.db,
            {
                "domains": ["crm"],
                "target_resource_type": "crm_project_task",
                "target_resource_id": task.id,
            },
        )
        self.db.refresh(case)
        self.assertNotEqual(case.evidence_version, previous_evidence)
        self.assertEqual((case.occurrence_type, case.occurrence_cycle), ("new", 1))
        self.assertEqual(self.db.scalars(select(ExceptionNotification)).all(), [])

        task.status = "closed"
        task.is_closed = True
        self.db.flush()
        run_incremental_exception_scan(
            self.db,
            {
                "domains": ["crm"],
                "target_resource_type": "crm_project_task",
                "target_resource_id": task.id,
            },
        )
        self.db.refresh(case)
        self.assertEqual(case.status, "resolved")

        task.is_closed = False
        self.db.flush()
        run_incremental_exception_scan(
            self.db,
            {
                "domains": ["crm"],
                "target_resource_type": "crm_project_task",
                "target_resource_id": task.id,
            },
        )
        self.db.refresh(case)
        self.assertEqual((case.status, case.occurrence_type, case.occurrence_cycle), ("open", "reopened", 2))
        self.assertEqual(self.db.scalars(select(ExceptionNotification)).all(), [])

    def test_target_scan_only_resolves_the_requested_resource(self) -> None:
        self._set_modes(crm="visible", approval="off")
        first = self._task("TARGET-ONE", status="closed", is_closed=False)
        second = self._task("TARGET-TWO", status="closed", is_closed=False)
        self.db.commit()
        sync_exception_cases(self.db, domains={"crm"})
        first_case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.resource_id == str(first.id)))
        second_case = self.db.scalar(select(ExceptionCase).where(ExceptionCase.resource_id == str(second.id)))

        first.is_closed = True
        second.is_closed = True
        self.db.flush()
        result = run_incremental_exception_scan(
            self.db,
            {
                "domains": ["crm"],
                "target_resource_type": "crm_project_task",
                "target_resource_id": str(first.id),
            },
        )
        self.db.refresh(first_case)
        self.db.refresh(second_case)

        self.assertEqual(result["resolved"], 1)
        self.assertEqual(first_case.status, "resolved")
        self.assertEqual(second_case.status, "open")

    def test_off_mode_does_not_create_or_resolve_cases(self) -> None:
        self._set_modes(crm="off", approval="off")
        task = self._task("OFF", status="closed", is_closed=False)
        self.db.commit()

        result = sync_exception_cases(
            self.db,
            domains={"crm"},
            target_resource_type="crm_project_task",
            target_resource_id=task.id,
        )

        self.assertEqual(result["domains"], [])
        self.assertEqual(self.db.scalars(select(ExceptionCase)).all(), [])

    def test_shadow_visibility_and_visible_source_scope_are_enforced(self) -> None:
        first_task = self._task(
            "SCOPE-ONE",
            status="closed",
            is_closed=False,
            executor=self.shadow_reviewer,
        )
        second_task = self._task("SCOPE-TWO", status="closed", is_closed=False, executor=self.sales_two)
        first_followup = self._followup(
            "SCOPE-ONE",
            task_id=first_task.id,
            project_id=999,
            customer_code=first_task.customer_code,
            executor=self.shadow_reviewer,
        )
        second_followup = self._followup(
            "SCOPE-TWO", task_id=second_task.id, project_id=999, customer_code=second_task.customer_code, executor=self.sales_two
        )
        now = datetime.now(timezone.utc)
        first_approval = self._approval(
            "SCOPE-ONE",
            status="approved",
            reviewed_at=None,
            closed_at=now,
            applicant=self.shadow_reviewer,
        )
        second_approval = self._approval(
            "SCOPE-TWO",
            status="approved",
            reviewed_at=None,
            closed_at=now,
            applicant=self.sales_two,
        )
        second_approval.current_handler_user_id = self.shadow_approval_handler.id
        personal_approval = self._approval(
            "SCOPE-PERSONAL",
            status="approved",
            reviewed_at=None,
            closed_at=now,
            applicant=self.policy_admin,
        )
        self.db.commit()
        sync_exception_cases(self.db, domains={"crm", "approval"}, scan_trigger="baseline")

        self.assertEqual(list(self.db.scalars(scoped_exception_stmt(self.db, self.sales_one)).all()), [])
        policy_admin_cases = list(self.db.scalars(scoped_exception_stmt(self.db, self.policy_admin)).all())
        self.assertEqual(
            {(case.resource_type, case.resource_id) for case in policy_admin_cases},
            {("approval_instance", str(personal_approval.id))},
        )
        shadow_reviewer_cases = list(
            self.db.scalars(scoped_exception_stmt(self.db, self.shadow_reviewer)).all()
        )
        self.assertEqual(
            {(case.resource_type, case.resource_id) for case in shadow_reviewer_cases},
            {
                ("crm_project_task", str(first_task.id)),
                ("crm_followup", str(first_followup.id)),
                ("approval_instance", str(first_approval.id)),
            },
        )
        handler_cases = list(
            self.db.scalars(scoped_exception_stmt(self.db, self.shadow_approval_handler)).all()
        )
        self.assertEqual(
            {(case.resource_type, case.resource_id) for case in handler_cases},
            {("approval_instance", str(second_approval.id))},
        )

        self._set_modes(crm="visible", approval="visible")
        visible = list(self.db.scalars(scoped_exception_stmt(self.db, self.sales_two)).all())
        visible_resources = {(case.resource_type, case.resource_id) for case in visible}
        self.assertEqual(
            visible_resources,
            {
                ("crm_project_task", str(second_task.id)),
                ("crm_followup", str(second_followup.id)),
                ("approval_instance", str(second_approval.id)),
            },
        )

    def test_safe_incremental_enqueue_skips_off_and_keeps_shadow_visible_payloads(self) -> None:
        self._set_modes(crm="off", approval="off")
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            queued_off = enqueue_incremental_exception_scan_safely(
                self.db,
                domains=["crm"],
                target_resource_type="crm_project_task",
                target_resource_id=7,
            )
        self.assertFalse(queued_off)
        self.assertEqual(list(self.db.scalars(select(ExceptionBackgroundJob)).all()), [])

        self._set_modes(crm="shadow", approval="off")
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            queued_before_baseline = enqueue_incremental_exception_scan_safely(
                self.db,
                domains=["crm"],
                target_resource_type="crm_project_task",
                target_resource_id=7,
            )
        self.assertFalse(queued_before_baseline)
        self.policy.settings_json = {
            "domain_modes": {"crm": "shadow", "approval": "off"},
            "domain_rollout": {
                "crm": {
                    "shadow_cycle": 1,
                    "shadow_started_at": datetime.now(timezone.utc).isoformat(),
                    "baseline_completed_at": datetime.now(timezone.utc).isoformat(),
                }
            },
        }
        self.db.commit()
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            queued_shadow = enqueue_incremental_exception_scan_safely(
                self.db,
                domains=["crm"],
                target_resource_type="crm_project_task",
                target_resource_id=7,
            )
        self.assertTrue(queued_shadow)
        shadow_job = self.db.scalar(select(ExceptionBackgroundJob))
        self.assertEqual(
            shadow_job.payload_json,
            {
                "domains": ["crm"],
                "target_resource_type": "crm_project_task",
                "target_resource_id": "7",
            },
        )

        self._set_modes(crm="off", approval="visible")
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            queued_visible = enqueue_incremental_exception_scan_safely(
                self.db,
                domains=["crm", "approval"],
            )
        self.assertTrue(queued_visible)
        jobs = list(self.db.scalars(select(ExceptionBackgroundJob).order_by(ExceptionBackgroundJob.id)).all())
        self.assertEqual([job.payload_json["domains"] for job in jobs], [["crm"], ["approval"]])

    def test_rule_quality_is_structured_and_respects_shadow_source_scope(self) -> None:
        own_task = self._task(
            "QUALITY-OWN",
            status="closed",
            is_closed=False,
            executor=self.shadow_reviewer,
        )
        other_task = self._task(
            "QUALITY-OTHER",
            status="closed",
            is_closed=False,
            executor=self.sales_two,
        )
        own_followup = self._followup(
            "QUALITY-OWN",
            task_id=own_task.id,
            project_id=999,
            customer_code=own_task.customer_code,
            executor=self.shadow_reviewer,
        )
        other_followup = self._followup(
            "QUALITY-OTHER",
            task_id=other_task.id,
            project_id=999,
            customer_code=other_task.customer_code,
            executor=self.sales_two,
        )
        self.db.commit()
        sync_exception_cases(self.db, domains={"crm"}, scan_trigger="baseline")
        own_task_case = self.db.scalar(
            select(ExceptionCase).where(
                ExceptionCase.resource_type == "crm_project_task",
                ExceptionCase.resource_id == str(own_task.id),
            )
        )
        own_followup_case = self.db.scalar(
            select(ExceptionCase).where(
                ExceptionCase.resource_type == "crm_followup",
                ExceptionCase.resource_id == str(own_followup.id),
            )
        )
        other_followup_case = self.db.scalar(
            select(ExceptionCase).where(
                ExceptionCase.resource_type == "crm_followup",
                ExceptionCase.resource_id == str(other_followup.id),
            )
        )
        own_followup_case.status = "resolved"
        own_followup_case.occurrence_type = "new"
        own_followup_case.occurrence_cycle = 1
        self.db.add_all(
            [
                ExceptionEvent(case_id=own_task_case.id, event_type="evidence_changed"),
                ExceptionEvent(case_id=own_task_case.id, event_type="evidence_changed"),
                ExceptionEvent(case_id=other_followup_case.id, event_type="evidence_changed"),
            ]
        )
        now = datetime.now(timezone.utc)
        self.db.add_all(
            [
                ExceptionBackgroundJob(
                    job_no="BG-QUALITY-QUEUED",
                    job_type="incremental_scan",
                    payload_json={"domains": ["crm"]},
                    status="queued",
                    available_at=now,
                ),
                ExceptionBackgroundJob(
                    job_no="BG-QUALITY-FAILED",
                    job_type="incremental_scan",
                    payload_json={"domains": ["crm"]},
                    status="failed",
                    available_at=now,
                    error_message="scan failed",
                ),
                ExceptionBackgroundJob(
                    job_no="BG-QUALITY-FAST",
                    job_type="full_scan",
                    payload_json={"input": {"domains": ["crm"]}, "result": {"scanned": 2}},
                    status="completed",
                    available_at=now,
                    started_at=now,
                    completed_at=now + timedelta(milliseconds=100),
                ),
                ExceptionBackgroundJob(
                    job_no="BG-QUALITY-SLOW",
                    job_type="full_scan",
                    payload_json={"input": {"domains": ["crm"]}, "result": {"scanned": 2}},
                    status="completed",
                    available_at=now,
                    started_at=now,
                    completed_at=now + timedelta(milliseconds=500),
                ),
                ExceptionBackgroundJob(
                    job_no="BG-QUALITY-OTHER-DOMAIN",
                    job_type="incremental_scan",
                    payload_json={"input": {"domains": ["approval"]}, "result": {"scanned": 1}},
                    status="completed",
                    available_at=now,
                    started_at=now,
                    completed_at=now + timedelta(milliseconds=900),
                ),
            ]
        )
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.get(
                "/api/v1/exceptions/rule-quality?domain=crm",
                headers=self.shadow_headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["scan_job_window_days"], 30)
        self.assertEqual(payload["scan_job_sample_limit"], 10_000)
        self.assertEqual(payload["scan_job_sample_size"], 0)
        self.assertFalse(payload["scan_job_metrics_truncated"])
        self.assertLessEqual(payload["scan_job_window_start"], payload["scan_job_window_end"])
        self.assertEqual(len(payload["domains"]), 1)
        domain_quality = payload["domains"][0]
        self.assertEqual(domain_quality["domain"], "crm")
        self.assertEqual(domain_quality["domain_mode"], "shadow")
        self.assertEqual(domain_quality["total"], 2)
        self.assertEqual(domain_quality["active"], 1)
        self.assertEqual(domain_quality["baseline"], 1)
        self.assertEqual(domain_quality["new"], 1)
        self.assertEqual(domain_quality["resolved"], 1)
        self.assertEqual(domain_quality["evidence_changed_events"], 2)
        self.assertFalse(domain_quality["scan_job_metrics_available"])
        self.assertIsNone(domain_quality["queued_scan_jobs"])
        self.assertIsNone(domain_quality["failed_scan_jobs"])
        self.assertIsNone(domain_quality["scan_latency_p95_ms"])
        self.assertIsNone(domain_quality["false_positive_rate"])
        self.assertEqual(sum(item["total"] for item in payload["rules"]), 2)
        self.assertEqual(
            {item["rule_code"] for item in payload["rules"]},
            {"crm.task_close_state_mismatch", "crm.followup_binding_mismatch"},
        )
        payload_text = str(payload)
        for forbidden in ("customer_feedback", "frontline_action", "resource_id", "reason", "title"):
            self.assertNotIn(forbidden, payload_text)

        scope_rules = list(
            self.db.scalars(
                select(DataScopeRule).where(
                    DataScopeRule.subject_type == "role",
                    DataScopeRule.subject_id == "shadow_reviewer",
                    DataScopeRule.resource_type.in_(("crm_task", "crm_followup")),
                )
            ).all()
        )
        for scope_rule in scope_rules:
            scope_rule.scope_mode = "all"
        self.db.commit()
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            global_response = self.client.get(
                "/api/v1/exceptions/rule-quality?domain=crm",
                headers=self.shadow_headers,
            )
        self.assertEqual(global_response.status_code, 200, global_response.text)
        global_quality = global_response.json()["domains"][0]
        self.assertEqual(global_quality["total"], 4)
        self.assertTrue(global_quality["scan_job_metrics_available"])
        self.assertEqual(global_quality["queued_scan_jobs"], 1)
        self.assertEqual(global_quality["failed_scan_jobs"], 1)
        self.assertEqual(global_quality["scan_latency_p95_ms"], 500)
        self.assertEqual(global_response.json()["scan_job_sample_size"], 5)
        self.assertFalse(global_response.json()["scan_job_metrics_truncated"])
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.services.exception_center_service.RULE_QUALITY_SCAN_JOB_SAMPLE_LIMIT", 2),
        ):
            truncated_response = self.client.get(
                "/api/v1/exceptions/rule-quality?domain=crm",
                headers=self.shadow_headers,
            )
        self.assertEqual(truncated_response.status_code, 200, truncated_response.text)
        self.assertEqual(truncated_response.json()["scan_job_sample_limit"], 2)
        self.assertEqual(truncated_response.json()["scan_job_sample_size"], 2)
        self.assertTrue(truncated_response.json()["scan_job_metrics_truncated"])
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            invalid_window = self.client.get(
                "/api/v1/exceptions/rule-quality?domain=crm&scan_window_days=91",
                headers=self.shadow_headers,
            )
        self.assertEqual(invalid_window.status_code, 422, invalid_window.text)

    def test_target_queue_validates_pairs_and_has_stable_dedupe(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be provided together"):
            enqueue_incremental_scan(
                self.db,
                domains=["crm"],
                target_resource_type="crm_project_task",
            )
        with self.assertRaisesRegex(ValueError, "exactly one domain"):
            enqueue_incremental_scan(
                self.db,
                domains=["crm", "approval"],
                target_resource_type="crm_project_task",
                target_resource_id=1,
            )
        with self.assertRaisesRegex(ValueError, "Unsupported target resource"):
            enqueue_incremental_scan(
                self.db,
                domains=["crm"],
                target_resource_type="approval_instance",
                target_resource_id=1,
            )

        first, reused = enqueue_incremental_scan(
            self.db,
            domains=["crm"],
            target_resource_type="crm_project_task",
            target_resource_id=7,
        )
        second, reused_second = enqueue_incremental_scan(
            self.db,
            domains=["crm"],
            target_resource_type="crm_project_task",
            target_resource_id="7",
        )
        self.assertFalse(reused)
        self.assertTrue(reused_second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.dedupe_key, "incremental:target:crm:crm_project_task:7")

        first.status = "processing"
        self.db.flush()
        followup, reused_followup = enqueue_incremental_scan(
            self.db,
            domains=["crm"],
            target_resource_type="crm_project_task",
            target_resource_id=7,
        )
        self.assertFalse(reused_followup)
        self.assertNotEqual(followup.id, first.id)
        self.assertIsNone(first.dedupe_key)
        self.assertEqual(followup.dedupe_key, "incremental:target:crm:crm_project_task:7")

    def _case(self, suffix: str, *, domain: str) -> ExceptionCase:
        now = datetime.now(timezone.utc)
        case = ExceptionCase(
            case_no=f"EXC-{suffix}",
            fingerprint=f"fingerprint-{suffix}",
            domain=domain,
            rule_code=f"{domain}.test",
            title=suffix,
            severity="high",
            status="open",
            occurrence_type="new",
            occurrence_cycle=1,
            rule_version="test-v1",
            resource_type="test",
            resource_id=suffix,
            source_type="test",
            source_id=suffix,
            evidence_version=f"evidence-{suffix}",
            reason="test",
            detected_at=now,
            last_seen_at=now,
        )
        self.db.add(case)
        self.db.flush()
        self.db.add(ExceptionEvidence(case_id=case.id, evidence_version=case.evidence_version, data_json={"kind": "test"}))
        self.db.flush()
        return case

    def test_ai_boundary_rejects_crm_and_unknown_domains_without_creating_jobs(self) -> None:
        crm_case = self._case("CRM-AI", domain="crm")
        unknown_case = self._case("UNKNOWN-AI", domain="unknown")
        inventory_case = self._case("INVENTORY-AI", domain="inventory")
        self.db.commit()

        self.assertFalse(serialize_case(self.db, crm_case)["diagnosis_supported"])
        self.assertFalse(serialize_case(self.db, unknown_case)["diagnosis_supported"])
        self.assertTrue(serialize_case(self.db, inventory_case)["diagnosis_supported"])
        for case in (crm_case, unknown_case):
            with self.assertRaises(HTTPException) as raised:
                create_diagnosis_job(self.db, case, self.policy_admin.id)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(raised.exception.detail["error_code"], "exception_diagnosis_not_supported")
        self.assertEqual(self.db.scalars(select(ExceptionDiagnosisJob)).all(), [])
        self.assertEqual(self.db.scalars(select(ExceptionEvent)).all(), [])

    def test_scheduled_ai_excludes_unsupported_domains(self) -> None:
        crm_case = self._case("CRM-SCHEDULED", domain="crm")
        approval_case = self._case("APPROVAL-SCHEDULED", domain="approval")
        inventory_case = self._case("INVENTORY-SCHEDULED", domain="inventory")
        self.policy.scheduled_ai_enabled = True
        self.policy.scheduled_ai_daily_limit = 10
        self.db.commit()

        with patch("app.services.exception_center_service.settings.exception_ai_enabled", True):
            jobs = enqueue_due_ai_diagnoses(self.db, limit=10)

        self.assertEqual([job.case_id for job in jobs], [inventory_case.id])
        self.assertNotIn(crm_case.id, [job.case_id for job in jobs])
        self.assertNotIn(approval_case.id, [job.case_id for job in jobs])

    def test_worker_fails_closed_for_unknown_domain_without_provider_call(self) -> None:
        case = self._case("UNKNOWN-WORKER", domain="unknown")
        case.status = "processing"
        job = ExceptionDiagnosisJob(
            job_no="EXJOB-UNKNOWN-WORKER",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="processing",
            attempts=1,
            available_at=datetime.now(timezone.utc),
            lease_owner="worker-1",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        self.db.add(job)
        self.db.commit()

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
            patch("app.services.exception_task_service.call_hermes_exception_diagnosis") as provider,
        ):
            result = execute_diagnosis_job(job_id=job.id, worker_id="worker-1")

        self.assertEqual(result, "failed")
        provider.assert_not_called()
        self.db.expire_all()
        self.assertEqual(self.db.get(ExceptionDiagnosisJob, job.id).status, "failed")
        self.assertEqual(self.db.get(ExceptionCase, case.id).status, "blocked")
        event = self.db.scalar(select(ExceptionEvent).where(ExceptionEvent.case_id == case.id))
        self.assertEqual(event.detail_json["reason_code"], "exception_diagnosis_not_supported")

    def test_retry_api_rejects_unsupported_domain_before_budget_without_mutation(self) -> None:
        task = self._task(
            "UNSUPPORTED-RETRY",
            status="closed",
            is_closed=False,
            executor=self.shadow_reviewer,
        )
        case = self._case("UNSUPPORTED-RETRY", domain="crm")
        case.resource_type = "crm_project_task"
        case.resource_id = str(task.id)
        case.status = "blocked"
        job = ExceptionDiagnosisJob(
            job_no="EXJOB-UNSUPPORTED-RETRY",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="failed",
            attempts=2,
            available_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            error_message="Historical failure",
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        self.db.refresh(case)
        before_job = (job.status, job.attempts, job.available_at, job.completed_at, job.error_message)
        before_case = (case.status, case.evidence_version)
        before_events = int(self.db.query(ExceptionEvent).count())

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
            patch("app.api.routes.exceptions.ai_budget_status") as budget,
        ):
            response = self.client.post(
                f"/api/v1/exception-jobs/{job.id}/retry",
                json={"reason": "Must remain deterministic", "reset_attempts": True},
                headers=self.shadow_headers,
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["error_code"], "exception_diagnosis_not_supported")
        budget.assert_not_called()
        self.db.refresh(job)
        self.db.refresh(case)
        self.assertEqual(
            (job.status, job.attempts, job.available_at, job.completed_at, job.error_message),
            before_job,
        )
        self.assertEqual((case.status, case.evidence_version), before_case)
        self.assertEqual(int(self.db.query(ExceptionEvent).count()), before_events)


class ExceptionDomainModePolicyApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        role = Role(role_code="admin", role_name="Admin")
        self.db.add(role)
        self.db.flush()
        user = User(
            username="domain-policy-admin",
            password_hash="hash",
            real_name="Domain Policy Admin",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        for code in (
            "exception_center.view",
            "exception_center.manage",
            "exception_center.policy_manage",
            "crm_task.view",
            "crm_followup.view",
            "approval.view",
        ):
            permission = Permission(
                permission_code=code,
                permission_name=code,
                resource_type=code.split(".", 1)[0],
                action_type=code.rsplit(".", 1)[-1],
            )
            self.db.add(permission)
            self.db.flush()
            self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        self.user = user
        self.policy = ExceptionPolicy(
            policy_key="default",
            is_enabled=True,
            manual_ai_enabled=False,
            scheduled_ai_enabled=False,
            full_scan_enabled=False,
            digest_enabled=False,
            manual_ai_daily_limit=20,
            scheduled_ai_daily_limit=0,
            scheduled_ai_batch_limit=20,
            ai_concurrency=1,
            stale_diagnosis_hours=24,
            settings_json={"retained": True},
        )
        self.db.add(self.policy)
        self.db.commit()

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(user.username)}"}

    def tearDown(self) -> None:
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def _set_domain_modes_via_api(self, *, crm: str, approval: str) -> dict:
        self.db.refresh(self.policy)
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.patch(
                "/api/v1/exception-policies",
                headers=self.headers,
                json={
                    "expected_updated_at": self.policy.updated_at.isoformat(),
                    "domain_modes": {"crm": crm, "approval": approval},
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.db.refresh(self.policy)
        return response.json()

    def test_policy_get_and_patch_expose_validated_domain_modes_with_audit(self) -> None:
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            initial = self.client.get("/api/v1/exception-policies", headers=self.headers)
            updated = self.client.patch(
                "/api/v1/exception-policies",
                headers=self.headers,
                json={
                    "expected_updated_at": initial.json()["updated_at"],
                    "domain_modes": {"crm": "shadow", "approval": "shadow"},
                },
            )

        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual(initial.json()["domain_modes"], {"crm": "off", "approval": "off"})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["domain_modes"], {"crm": "shadow", "approval": "shadow"})
        self.assertTrue(updated.json()["settings"]["retained"])
        self.assertEqual(
            updated.json()["settings"]["domain_modes"],
            {"crm": "shadow", "approval": "shadow"},
        )
        audit = self.db.scalar(
            select(AuditLog)
            .where(AuditLog.action_type == "update_exception_policy")
            .order_by(AuditLog.id.desc())
        )
        self.assertEqual(audit.before_data["domain_modes"], {"crm": "off", "approval": "off"})
        self.assertEqual(audit.after_data["domain_modes"], {"crm": "shadow", "approval": "shadow"})

    def test_policy_patch_requires_current_shadow_baseline_before_visible(self) -> None:
        expected = self.policy.updated_at.isoformat()
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            direct_visible = self.client.patch(
                "/api/v1/exception-policies",
                headers=self.headers,
                json={
                    "expected_updated_at": expected,
                    "domain_modes": {"crm": "visible", "approval": "off"},
                },
            )
        self.assertEqual(direct_visible.status_code, 409, direct_visible.text)
        self.assertEqual(direct_visible.json()["detail"]["error_code"], "exception_baseline_required")
        self.db.refresh(self.policy)
        self.assertNotIn("domain_modes", self.policy.settings_json)

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            current = self.client.get("/api/v1/exception-policies", headers=self.headers).json()
            direct_put = self.client.put(
                "/api/v1/exception-policies",
                headers=self.headers,
                json={
                    key: current[key]
                    for key in (
                        "is_enabled",
                        "manual_ai_enabled",
                        "scheduled_ai_enabled",
                        "full_scan_enabled",
                        "digest_enabled",
                        "full_scan_cron",
                        "digest_cron",
                        "ai_daily_limit",
                        "ai_batch_limit",
                        "manual_ai_daily_limit",
                        "scheduled_ai_daily_limit",
                        "scheduled_ai_batch_limit",
                        "ai_concurrency",
                        "stale_diagnosis_hours",
                        "settings",
                    )
                }
                | {"domain_modes": {"crm": "visible", "approval": "off"}},
            )
        self.assertEqual(direct_put.status_code, 409, direct_put.text)
        self.assertEqual(direct_put.json()["detail"]["error_code"], "exception_baseline_required")
        self.db.refresh(self.policy)
        self.assertNotIn("domain_modes", self.policy.settings_json)

        shadow_policy = self._set_domain_modes_via_api(crm="shadow", approval="off")
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            visible_without_baseline = self.client.patch(
                "/api/v1/exception-policies",
                headers=self.headers,
                json={
                    "expected_updated_at": shadow_policy["updated_at"],
                    "domain_modes": {"crm": "visible", "approval": "off"},
                },
            )
        self.assertEqual(visible_without_baseline.status_code, 409, visible_without_baseline.text)
        self.assertEqual(
            visible_without_baseline.json()["detail"]["error_code"],
            "exception_baseline_required",
        )
        self.db.refresh(self.policy)
        self.assertEqual(self.policy.settings_json["domain_modes"], {"crm": "shadow", "approval": "off"})

    def test_policy_patch_rejects_invalid_or_stale_domain_modes(self) -> None:
        expected = self.policy.updated_at.isoformat()
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            invalid = self.client.patch(
                "/api/v1/exception-policies",
                headers=self.headers,
                json={
                    "expected_updated_at": expected,
                    "domain_modes": {"crm": "automatic", "approval": "off"},
                },
            )
            first = self.client.patch(
                "/api/v1/exception-policies",
                headers=self.headers,
                json={
                    "expected_updated_at": expected,
                    "domain_modes": {"crm": "shadow", "approval": "off"},
                },
            )
            stale = self.client.patch(
                "/api/v1/exception-policies",
                headers=self.headers,
                json={
                    "expected_updated_at": expected,
                    "domain_modes": {"crm": "visible", "approval": "visible"},
                },
            )

        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["error_code"], "exception_policy_version_conflict")

    def test_baseline_scan_is_audited_sanitized_and_idempotent_per_shadow_cycle(self) -> None:
        shadow_policy = self._set_domain_modes_via_api(crm="shadow", approval="off")
        scan_result = {
            "scanned": 0,
            "created": 0,
            "new": 0,
            "reopened": 0,
            "evidence_updated": 0,
            "resolved": 0,
            "evidence": {"customer_feedback": "must-not-be-audited"},
        }
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            queued_before_baseline = enqueue_incremental_exception_scan_safely(
                self.db,
                domains=["crm"],
                target_resource_type="crm_project_task",
                target_resource_id=101,
            )
        self.assertFalse(queued_before_baseline)
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases") as regular_scan,
        ):
            blocked_regular_scan = self.client.post(
                "/api/v1/exceptions/scan?domains=crm",
                headers=self.headers,
            )
        self.assertEqual(blocked_regular_scan.status_code, 409, blocked_regular_scan.text)
        self.assertEqual(blocked_regular_scan.json()["detail"]["error_code"], "exception_baseline_required")
        regular_scan.assert_not_called()
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases", return_value=scan_result) as scan,
        ):
            first = self.client.post(
                "/api/v1/exceptions/baseline-scan",
                headers=self.headers,
                json={
                    "domain": "crm",
                    "expected_policy_updated_at": shadow_policy["updated_at"],
                },
            )
        self.assertEqual(first.status_code, 200, first.text)
        scan.assert_called_once_with(self.db, domains={"crm"}, scan_trigger="baseline")
        first_payload = first.json()
        self.assertEqual(first_payload["domain"], "crm")
        self.assertEqual(first_payload["domain_mode"], "shadow")
        self.assertEqual(first_payload["shadow_cycle"], 1)
        self.assertEqual(first_payload["result"]["scanned"], 0)
        self.assertNotEqual(first_payload["policy_updated_at"], shadow_policy["updated_at"])

        audit = self.db.get(AuditLog, first_payload["audit_id"])
        self.assertEqual(audit.action_type, "run_exception_baseline_scan")
        self.assertEqual(audit.resource_type, "exception_domain")
        self.assertEqual(audit.resource_id, "crm")
        self.assertNotIn("must-not-be-audited", str(audit.after_data))
        self.assertNotIn("customer_feedback", str(audit.after_data))
        self.db.refresh(self.policy)
        rollout = self.policy.settings_json["domain_rollout"]["crm"]
        self.assertEqual(rollout["shadow_cycle"], 1)
        self.assertEqual(rollout["baseline_audit_id"], audit.id)
        self.assertEqual(rollout["baseline_result_summary"]["scanned"], 0)
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            queued_after_baseline = enqueue_incremental_exception_scan_safely(
                self.db,
                domains=["crm"],
                target_resource_type="crm_project_task",
                target_resource_id=101,
            )
        self.assertTrue(queued_after_baseline)

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases") as repeated_scan,
        ):
            repeated = self.client.post(
                "/api/v1/exceptions/baseline-scan",
                headers=self.headers,
                json={
                    "domain": "crm",
                    "expected_policy_updated_at": first_payload["policy_updated_at"],
                },
            )
        self.assertEqual(repeated.status_code, 409, repeated.text)
        self.assertEqual(repeated.json()["detail"]["error_code"], "exception_baseline_already_completed")
        repeated_scan.assert_not_called()

        visible_policy = self._set_domain_modes_via_api(crm="visible", approval="off")
        second_shadow = self._set_domain_modes_via_api(crm="shadow", approval="off")
        self.assertNotEqual(visible_policy["updated_at"], second_shadow["updated_at"])
        self.assertEqual(second_shadow["settings"]["domain_rollout"]["crm"]["shadow_cycle"], 2)
        self.assertNotIn(
            "baseline_completed_at",
            second_shadow["settings"]["domain_rollout"]["crm"],
        )
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            queued_before_second_baseline = enqueue_incremental_exception_scan_safely(
                self.db,
                domains=["crm"],
                target_resource_type="crm_project_task",
                target_resource_id=102,
            )
        self.assertFalse(queued_before_second_baseline)
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases", return_value=scan_result) as second_scan,
        ):
            second = self.client.post(
                "/api/v1/exceptions/baseline-scan",
                headers=self.headers,
                json={
                    "domain": "crm",
                    "expected_policy_updated_at": second_shadow["updated_at"],
                },
            )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["shadow_cycle"], 2)
        second_scan.assert_called_once_with(self.db, domains={"crm"}, scan_trigger="baseline")

    def test_baseline_scan_rejects_stale_policy_non_shadow_and_restricted_scope(self) -> None:
        current_updated_at = self.policy.updated_at
        stale_expected = current_updated_at - timedelta(seconds=1)
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases") as scan,
        ):
            stale = self.client.post(
                "/api/v1/exceptions/baseline-scan",
                headers=self.headers,
                json={"domain": "crm", "expected_policy_updated_at": stale_expected.isoformat()},
            )
            non_shadow = self.client.post(
                "/api/v1/exceptions/baseline-scan",
                headers=self.headers,
                json={"domain": "crm", "expected_policy_updated_at": current_updated_at.isoformat()},
            )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["error_code"], "exception_policy_version_conflict")
        self.assertEqual(non_shadow.status_code, 409, non_shadow.text)
        self.assertEqual(non_shadow.json()["detail"]["error_code"], "exception_baseline_requires_shadow_domain")
        scan.assert_not_called()

        shadow_policy = self._set_domain_modes_via_api(crm="shadow", approval="off")
        self.db.add(
            DataScopeRule(
                subject_type="user",
                subject_id=str(self.user.id),
                resource_type="crm_task",
                scope_mode="own",
            )
        )
        self.db.commit()
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases") as restricted_scan,
        ):
            restricted = self.client.post(
                "/api/v1/exceptions/baseline-scan",
                headers=self.headers,
                json={
                    "domain": "crm",
                    "expected_policy_updated_at": shadow_policy["updated_at"],
                },
            )
        self.assertEqual(restricted.status_code, 403, restricted.text)
        self.assertEqual(restricted.json()["detail"]["error_code"], "exception_global_scan_scope_required")
        restricted_scan.assert_not_called()
        self.assertIsNone(
            self.db.scalar(select(AuditLog).where(AuditLog.action_type == "run_exception_baseline_scan"))
        )


if __name__ == "__main__":
    unittest.main()
