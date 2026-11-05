import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import exceptions as exception_routes
from app.api.routes.exceptions import router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import (
    AuditLog,
    DataScopeRule,
    ExceptionBackgroundJob,
    ExceptionCase,
    ExceptionDiagnosis,
    ExceptionDiagnosisJob,
    ExceptionEvent,
    ExceptionNotification,
    ExceptionPolicy,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.services.exception_center_service import _assign_and_notify_case


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ExceptionWorkflowApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.admin_role = Role(role_code="workflow-admin", role_name="Workflow admin")
        self.limited_role = Role(role_code="workflow-limited", role_name="Workflow limited")
        self.receiver_role = Role(role_code="workflow-receiver", role_name="Workflow receiver")
        self.db.add_all([self.admin_role, self.limited_role, self.receiver_role])
        self.db.flush()
        self.admin = self._user("workflow-admin", self.admin_role.role_code)
        self.limited = self._user("workflow-limited", self.limited_role.role_code)
        self.receiver = self._user("workflow-receiver", self.receiver_role.role_code)
        for code in (
            "exception_center.view",
            "exception_center.manage",
            "exception_center.diagnose",
            "exception_center.policy_manage",
            "inventory_snapshot.view",
            "inventory_check.view",
        ):
            self._grant(self.admin_role, code)
        for code in (
            "exception_center.view",
            "exception_center.manage",
            "exception_center.diagnose",
            "inventory_snapshot.view",
        ):
            self._grant(self.limited_role, code)
        for code in ("exception_center.view", "inventory_snapshot.view"):
            self._grant(self.receiver_role, code)
        self.db.add(
            ExceptionPolicy(
                policy_key="default",
                is_enabled=True,
                manual_ai_enabled=True,
                scheduled_ai_enabled=False,
                full_scan_enabled=False,
                digest_enabled=False,
                manual_ai_daily_limit=20,
                scheduled_ai_daily_limit=0,
                scheduled_ai_batch_limit=20,
                ai_concurrency=1,
            )
        )
        self.db.commit()

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.admin_headers = self._headers(self.admin)
        self.limited_headers = self._headers(self.limited)

    def tearDown(self) -> None:
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def _user(self, username: str, role_code: str) -> User:
        user = User(
            username=username,
            password_hash="hash",
            real_name=username,
            role=role_code,
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
                resource_type=code.split(".")[0],
                action_type=code.split(".")[-1],
            )
            self.db.add(permission)
            self.db.flush()
        self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))

    @staticmethod
    def _headers(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.username)}"}

    def _case(
        self,
        suffix: str,
        *,
        source_type: str = "inventory_snapshot_quality",
        occurrence_type: str = "new",
        assignee_user_id: int | None = None,
    ) -> ExceptionCase:
        case = ExceptionCase(
            case_no=f"EXC-WORKFLOW-{suffix}",
            fingerprint=f"workflow-{suffix}",
            domain="inventory",
            rule_code=f"workflow.{suffix.lower()}",
            title=f"Workflow {suffix}",
            severity="high",
            status="open",
            occurrence_type=occurrence_type,
            resource_type="product",
            resource_id=suffix,
            resource_code=suffix,
            resource_name=suffix,
            source_type=source_type,
            source_id=suffix,
            evidence_version="evidence-v1",
            reason="Workflow API regression case",
            assignee_user_id=assignee_user_id,
        )
        self.db.add(case)
        self.db.flush()
        return case

    def _diagnosis(self, case: ExceptionCase) -> ExceptionDiagnosis:
        diagnosis = ExceptionDiagnosis(
            case_id=case.id,
            evidence_version=case.evidence_version,
            root_cause_code="snapshot_mismatch",
            summary="Snapshot and flow differ.",
            confidence=Decimal("0.9700"),
            disposition="actionable",
            evidence_refs_json=["inventory:1"],
            impact_json={"summary": "Inventory is inaccurate."},
            recommended_steps_json=[{"step": 1, "instruction": "Recheck the source."}],
            missing_evidence_json=[],
            model_name="test-model",
            request_id="request-feedback",
        )
        self.db.add(diagnosis)
        self.db.flush()
        return diagnosis

    def test_batch_assign_deduplicates_and_preserves_omitted_assignee(self) -> None:
        first = self._case("ASSIGN-1", assignee_user_id=self.admin.id)
        second = self._case("ASSIGN-2", assignee_user_id=self.admin.id)
        self.db.commit()
        due_at = datetime.now(timezone.utc) + timedelta(days=2)

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.post(
                "/api/v1/exceptions/batch/assign",
                json={"case_nos": [first.case_no, first.case_no, second.case_no], "due_at": due_at.isoformat()},
                headers=self.admin_headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated_count"], 2)
        self.db.refresh(first)
        self.db.refresh(second)
        self.assertEqual(first.assignee_user_id, self.admin.id)
        self.assertEqual(second.assignee_user_id, self.admin.id)
        self.assertEqual(first.due_at, due_at.replace(tzinfo=None))
        events = list(self.db.scalars(select(ExceptionEvent).order_by(ExceptionEvent.id)).all())
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].detail_json["updated_fields"], ["due_at"])
        self.assertTrue(events[0].detail_json["batch"])

    def test_batch_assign_out_of_scope_case_rolls_back_entire_request(self) -> None:
        visible = self._case("VISIBLE")
        hidden = self._case("HIDDEN", source_type="inventory_check_result")
        self.db.commit()
        due_at = datetime.now(timezone.utc) + timedelta(days=1)

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.post(
                "/api/v1/exceptions/batch/assign",
                json={"case_nos": [visible.case_no, hidden.case_no], "due_at": due_at.isoformat()},
                headers=self.limited_headers,
            )

        self.assertEqual(response.status_code, 404, response.text)
        self.db.refresh(visible)
        self.assertIsNone(visible.due_at)
        self.assertEqual(self.db.scalar(select(func.count(ExceptionEvent.id))), 0)

    def test_batch_assign_explicit_null_restores_defaults_and_empty_patch_is_rejected(self) -> None:
        default_owner = self._user("workflow-default-owner", "data_middle_office")
        original_due_at = datetime.now(timezone.utc) + timedelta(days=3)
        case = self._case("ASSIGN-CLEAR", assignee_user_id=self.admin.id)
        case.due_at = original_due_at
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            rejected = self.client.post(
                "/api/v1/exceptions/batch/assign",
                json={"case_nos": [case.case_no]},
                headers=self.admin_headers,
            )
            cleared = self.client.post(
                "/api/v1/exceptions/batch/assign",
                json={"case_nos": [case.case_no], "assignee_user_id": None, "due_at": None},
                headers=self.admin_headers,
            )

        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.db.refresh(case)
        self.assertEqual(case.assignee_user_id, default_owner.id)
        self.assertIsNotNone(case.due_at)
        self.assertNotEqual(case.due_at, original_due_at.replace(tzinfo=None))
        event = self.db.scalar(select(ExceptionEvent).where(ExceptionEvent.case_id == case.id))
        self.assertEqual(event.event_type, "assignment_defaults_restored")
        self.assertEqual(event.detail_json["updated_fields"], ["assignee_user_id", "due_at"])
        self.assertEqual(event.detail_json["previous_assignee_user_id"], self.admin.id)

    def test_batch_assignment_rejects_resolved_or_ignored_atomically(self) -> None:
        active = self._case("ASSIGN-ACTIVE")
        resolved = self._case("ASSIGN-RESOLVED")
        resolved.status = "resolved"
        ignored = self._case("ASSIGN-IGNORED")
        ignored.status = "ignored"
        self.db.commit()
        due_at = datetime.now(timezone.utc) + timedelta(days=1)

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.post(
                "/api/v1/exceptions/batch/assign",
                json={"case_nos": [active.case_no, resolved.case_no, ignored.case_no], "due_at": due_at.isoformat()},
                headers=self.admin_headers,
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.db.refresh(active)
        self.assertIsNone(active.due_at)
        self.assertEqual(self.db.scalar(select(func.count(ExceptionEvent.id))), 0)

    def test_batch_assign_rejects_assignee_without_every_source_permission(self) -> None:
        snapshot_case = self._case("SNAPSHOT")
        check_case = self._case("CHECK", source_type="inventory_check_result")
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.post(
                "/api/v1/exceptions/batch/assign",
                json={
                    "case_nos": [snapshot_case.case_no, check_case.case_no],
                    "assignee_user_id": self.receiver.id,
                },
                headers=self.admin_headers,
            )

        self.assertEqual(response.status_code, 400, response.text)
        self.db.refresh(snapshot_case)
        self.db.refresh(check_case)
        self.assertIsNone(snapshot_case.assignee_user_id)
        self.assertIsNone(check_case.assignee_user_id)
        self.assertEqual(self.db.scalar(select(func.count(ExceptionEvent.id))), 0)

    def test_batch_ignore_is_deduplicated_and_missing_case_is_atomic(self) -> None:
        first = self._case("IGNORE-1")
        second = self._case("IGNORE-2")
        self.db.commit()
        ignored_until = datetime.now(timezone.utc) + timedelta(days=7)

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            failed = self.client.post(
                "/api/v1/exceptions/batch/ignore",
                json={
                    "case_nos": [first.case_no, "EXC-DOES-NOT-EXIST"],
                    "reason": "Known historical discrepancy",
                    "ignored_until": ignored_until.isoformat(),
                },
                headers=self.admin_headers,
            )
            succeeded = self.client.post(
                "/api/v1/exceptions/batch/ignore",
                json={
                    "case_nos": [first.case_no, first.case_no, second.case_no],
                    "reason": "Known historical discrepancy",
                    "ignored_until": ignored_until.isoformat(),
                },
                headers=self.admin_headers,
            )

        self.assertEqual(failed.status_code, 404, failed.text)
        self.assertEqual(succeeded.status_code, 200, succeeded.text)
        self.assertEqual(succeeded.json()["updated_count"], 2)
        self.db.refresh(first)
        self.db.refresh(second)
        self.assertEqual(first.status, "ignored")
        self.assertEqual(second.status, "ignored")
        self.assertEqual(self.db.scalar(select(func.count(ExceptionEvent.id))), 2)

    def test_ignore_rejects_ineligible_states_for_batch_and_single_without_partial_mutation(self) -> None:
        active = self._case("IGNORE-ACTIVE")
        processing = self._case("IGNORE-PROCESSING")
        processing.status = "processing"
        resolved = self._case("IGNORE-RESOLVED")
        resolved.status = "resolved"
        ignored_until = datetime.now(timezone.utc) + timedelta(days=7)
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            batch = self.client.post(
                "/api/v1/exceptions/batch/ignore",
                json={
                    "case_nos": [active.case_no, processing.case_no],
                    "reason": "Cannot ignore running work",
                    "ignored_until": ignored_until.isoformat(),
                },
                headers=self.admin_headers,
            )
            single = self.client.post(
                f"/api/v1/exceptions/{resolved.case_no}/ignore",
                json={"reason": "Cannot ignore resolved work", "ignored_until": ignored_until.isoformat()},
                headers=self.admin_headers,
            )

        self.assertEqual(batch.status_code, 409, batch.text)
        self.assertEqual(single.status_code, 409, single.text)
        self.db.refresh(active)
        self.assertEqual(active.status, "open")
        self.assertEqual(self.db.scalar(select(func.count(ExceptionEvent.id))), 0)

    def test_case_number_limit_is_applied_after_deduplication(self) -> None:
        case = self._case("LIMIT")
        self.db.commit()
        due_at = datetime.now(timezone.utc) + timedelta(days=1)

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            duplicates = self.client.post(
                "/api/v1/exceptions/batch/assign",
                json={"case_nos": [case.case_no] * 150, "due_at": due_at.isoformat()},
                headers=self.admin_headers,
            )
            too_many = self.client.post(
                "/api/v1/exceptions/batch/assign",
                json={"case_nos": [f"EXC-{index}" for index in range(101)], "due_at": due_at.isoformat()},
                headers=self.admin_headers,
            )

        self.assertEqual(duplicates.status_code, 200, duplicates.text)
        self.assertEqual(duplicates.json()["updated_count"], 1)
        self.assertEqual(too_many.status_code, 422, too_many.text)

    def test_occurrence_type_filters_page_and_summary(self) -> None:
        for occurrence_type in ("baseline", "new", "reopened"):
            self._case(occurrence_type.upper(), occurrence_type=occurrence_type)
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            page = self.client.get(
                "/api/v1/exceptions/page?occurrence_type=baseline",
                headers=self.admin_headers,
            )
            filtered_summary = self.client.get(
                "/api/v1/exceptions/summary?occurrence_type=reopened",
                headers=self.admin_headers,
            )
            complete_summary = self.client.get("/api/v1/exceptions/summary", headers=self.admin_headers)

        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 1)
        self.assertEqual(page.json()["items"][0]["occurrence_type"], "baseline")
        self.assertEqual(filtered_summary.status_code, 200, filtered_summary.text)
        self.assertEqual(filtered_summary.json()["total"], 1)
        self.assertEqual(filtered_summary.json()["by_occurrence"], {"reopened": 1})
        self.assertEqual(
            complete_summary.json()["by_occurrence"],
            {"baseline": 1, "new": 1, "reopened": 1},
        )

    def test_immediate_notifications_exclude_baseline_and_warning_cases(self) -> None:
        owner = self._user("workflow-data-owner", "data_middle_office")
        baseline = self._case("NOTIFY-BASELINE", occurrence_type="baseline")
        new_case = self._case("NOTIFY-NEW", occurrence_type="new")
        reopened = self._case("NOTIFY-REOPENED", occurrence_type="reopened")
        warning = self._case("NOTIFY-WARNING", occurrence_type="new")
        warning.severity = "warning"
        now = datetime.now(timezone.utc)

        for case in (baseline, new_case, reopened, warning):
            _assign_and_notify_case(self.db, case, now)
        self.db.commit()

        notifications = list(self.db.scalars(select(ExceptionNotification).order_by(ExceptionNotification.id)).all())
        self.assertEqual({row.case_id for row in notifications}, {new_case.id, reopened.id})
        self.assertTrue(all(row.user_id == owner.id for row in notifications))
        self.assertIsNotNone(baseline.due_at)

    def test_archived_notifications_are_excluded_without_being_marked_read(self) -> None:
        case = self._case("ARCHIVED-NOTIFICATION")
        notification = ExceptionNotification(
            case_id=case.id,
            user_id=self.admin.id,
            notification_type="high_risk",
            evidence_version=case.evidence_version,
            occurrence_cycle=case.occurrence_cycle,
            title="Archived",
            message="Archived baseline notification",
            is_read=False,
            archived_at=datetime.now(timezone.utc),
            archive_reason="baseline_migration",
        )
        self.db.add(notification)
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            listed = self.client.get("/api/v1/exception-notifications", headers=self.admin_headers)
            summary = self.client.get("/api/v1/exceptions/summary", headers=self.admin_headers)
            read = self.client.post(
                f"/api/v1/exception-notifications/{notification.id}/read",
                headers=self.admin_headers,
            )

        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json(), [])
        self.assertEqual(summary.json()["unread_notifications"], 0)
        self.assertEqual(read.status_code, 404, read.text)
        self.db.refresh(notification)
        self.assertFalse(notification.is_read)
        self.assertIsNone(notification.read_at)
        self.assertIsNone(notification.acknowledged_at)

    def test_diagnosis_feedback_writes_fields_and_event(self) -> None:
        case = self._case("FEEDBACK")
        diagnosis = self._diagnosis(case)
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.post(
                f"/api/v1/exception-diagnoses/{diagnosis.id}/feedback",
                json={"rating": "partial", "note": "  The source timing still needs review.  "},
                headers=self.admin_headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["feedback_rating"], "partial")
        self.assertEqual(response.json()["feedback_note"], "The source timing still needs review.")
        self.assertEqual(response.json()["feedback_by_user_id"], self.admin.id)
        self.db.refresh(diagnosis)
        self.assertIsNotNone(diagnosis.feedback_at)
        event = self.db.scalar(select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_feedback"))
        self.assertEqual(event.case_id, case.id)
        self.assertEqual(event.detail_json["diagnosis_id"], diagnosis.id)

    def test_diagnosis_feedback_requires_source_domain_access(self) -> None:
        case = self._case("FEEDBACK-HIDDEN", source_type="inventory_check_result")
        diagnosis = self._diagnosis(case)
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.post(
                f"/api/v1/exception-diagnoses/{diagnosis.id}/feedback",
                json={"rating": "helpful"},
                headers=self.limited_headers,
            )

        self.assertEqual(response.status_code, 404, response.text)
        self.db.refresh(diagnosis)
        self.assertIsNone(diagnosis.feedback_rating)

    def test_exception_detail_recovers_evidence_telemetry_from_diagnosed_event(self) -> None:
        case = self._case("DIAGNOSIS-TELEMETRY")
        job = ExceptionDiagnosisJob(
            job_no="EXJOB-WORKFLOW-TELEMETRY",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="completed",
            available_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        self.db.add(job)
        self.db.flush()
        diagnosis = self._diagnosis(case)
        diagnosis.job_id = job.id
        self.db.add(
            ExceptionEvent(
                case_id=case.id,
                event_type="diagnosed",
                detail_json={
                    "job_no": job.job_no,
                    "model_call": {
                        "request_id": diagnosis.request_id,
                        "evidence_bytes": 1234,
                        "evidence_approx_tokens": 309,
                        "evidence_truncated": True,
                    },
                },
            )
        )
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.get(f"/api/v1/exceptions/{case.case_no}", headers=self.admin_headers)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["diagnosis"]["evidence_bytes"], 1234)
        self.assertEqual(payload["diagnosis"]["evidence_approx_tokens"], 309)
        self.assertTrue(payload["diagnosis"]["evidence_truncated"])
        self.assertEqual(payload["diagnoses"][0]["evidence_bytes"], 1234)
        self.assertEqual(payload["diagnoses"][0]["evidence_approx_tokens"], 309)
        self.assertTrue(payload["diagnoses"][0]["evidence_truncated"])

    def test_job_history_remains_readable_and_retry_cancel_reasons_are_audited(self) -> None:
        case = self._case("JOB-HISTORY")
        case.status = "blocked"
        job = ExceptionDiagnosisJob(
            job_no="EXJOB-WORKFLOW-HISTORY",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="failed",
            attempts=3,
            available_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            error_message="Diagnosis failed",
        )
        self.db.add(job)
        self.db.commit()

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
        ):
            history = self.client.get(f"/api/v1/exception-jobs/{job.id}", headers=self.admin_headers)
            denied_retry = self.client.post(
                f"/api/v1/exception-jobs/{job.id}/retry",
                json={"reason": "Insufficient governance permission", "reset_attempts": True},
                headers=self.limited_headers,
            )
            retried = self.client.post(
                f"/api/v1/exception-jobs/{job.id}/retry",
                json={"reason": "Evidence has been corrected", "reset_attempts": True},
                headers=self.admin_headers,
            )
            cancelled = self.client.post(
                f"/api/v1/exception-jobs/{job.id}/cancel",
                json={"reason": "Operator cancelled the rerun"},
                headers=self.admin_headers,
            )

        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()["status"], "failed")
        self.assertEqual(denied_retry.status_code, 403, denied_retry.text)
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        self.db.refresh(case)
        self.assertEqual(case.status, "blocked")
        events = list(
            self.db.scalars(
                select(ExceptionEvent)
                .where(ExceptionEvent.case_id == case.id)
                .order_by(ExceptionEvent.id)
            ).all()
        )
        self.assertEqual(events[-2].event_type, "diagnosis_retried")
        self.assertEqual(events[-2].detail_json["reason"], "Evidence has been corrected")
        self.assertEqual(events[-1].event_type, "diagnosis_cancelled")
        self.assertEqual(events[-1].detail_json["reason"], "Operator cancelled the rerun")

    def test_retry_rejects_another_active_job_for_the_same_evidence(self) -> None:
        case = self._case("JOB-RETRY-CONFLICT")
        case.status = "processing"
        failed = ExceptionDiagnosisJob(
            job_no="EXJOB-WORKFLOW-RETRY-FAILED",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="failed",
            attempts=2,
            available_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        active = ExceptionDiagnosisJob(
            job_no="EXJOB-WORKFLOW-RETRY-ACTIVE",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="queued",
            attempts=0,
            available_at=datetime.now(timezone.utc),
        )
        self.db.add_all([failed, active])
        self.db.commit()

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
        ):
            response = self.client.post(
                f"/api/v1/exception-jobs/{failed.id}/retry",
                json={"reason": "Retry must not duplicate the active job"},
                headers=self.admin_headers,
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["error_code"], "exception_active_diagnosis_exists")
        self.assertEqual(response.json()["detail"]["active_job_id"], active.id)
        self.db.refresh(failed)
        self.assertEqual(failed.status, "failed")

    def test_database_rejects_two_active_jobs_for_the_same_evidence(self) -> None:
        case = self._case("JOB-UNIQUE-INDEX")
        self.db.add(
            ExceptionDiagnosisJob(
                job_no="EXJOB-WORKFLOW-UNIQUE-1",
                case_id=case.id,
                evidence_version=case.evidence_version,
                trigger_type="manual",
                status="queued",
                attempts=0,
                available_at=datetime.now(timezone.utc),
            )
        )
        self.db.flush()
        self.db.add(
            ExceptionDiagnosisJob(
                job_no="EXJOB-WORKFLOW-UNIQUE-2",
                case_id=case.id,
                evidence_version=case.evidence_version,
                trigger_type="scheduled",
                status="processing",
                attempts=1,
                available_at=datetime.now(timezone.utc),
            )
        )
        with self.assertRaises(IntegrityError):
            self.db.flush()
        self.db.rollback()

    def test_processing_job_cancellation_is_immediate_without_a_running_worker(self) -> None:
        case = self._case("PROCESSING-CANCEL")
        case.status = "processing"
        job = ExceptionDiagnosisJob(
            job_no="EXJOB-WORKFLOW-PROCESSING",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="processing",
            attempts=1,
            available_at=datetime.now(timezone.utc),
            lease_owner="offline-worker",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(job)
        self.db.flush()
        self.db.add(
            ExceptionEvent(
                case_id=case.id,
                event_type="diagnosis_queued",
                from_status="action_required",
                to_status="processing",
                detail_json={"job_no": job.job_no},
            )
        )
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.post(
                f"/api/v1/exception-jobs/{job.id}/cancel",
                json={"reason": "Worker is offline; cancel immediately"},
                headers=self.admin_headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "cancelled")
        self.db.refresh(case)
        self.db.refresh(job)
        self.assertEqual(case.status, "action_required")
        self.assertIsNone(job.lease_owner)
        self.assertIsNone(job.lease_expires_at)
        event = self.db.scalar(
            select(ExceptionEvent).where(
                ExceptionEvent.case_id == case.id,
                ExceptionEvent.event_type == "diagnosis_cancelled",
            )
        )
        self.assertEqual(event.detail_json["reason"], "Worker is offline; cancel immediately")

    def test_all_jobs_queue_has_global_order_total_and_server_pagination(self) -> None:
        case = self._case("ALL-JOBS")
        now = datetime.now(timezone.utc)
        diagnosis = ExceptionDiagnosisJob(
            job_no="EXJOB-WORKFLOW-ALL",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="queued",
            attempts=0,
            available_at=now,
            created_at=now - timedelta(minutes=2),
            updated_at=now - timedelta(minutes=2),
        )
        older_background = ExceptionBackgroundJob(
            job_no="EXBG-WORKFLOW-OLDER",
            job_type="incremental_scan",
            status="completed",
            attempts=1,
            available_at=now - timedelta(minutes=3),
            created_at=now - timedelta(minutes=3),
            updated_at=now - timedelta(minutes=3),
            completed_at=now - timedelta(minutes=3),
        )
        newer_background = ExceptionBackgroundJob(
            job_no="EXBG-WORKFLOW-NEWER",
            job_type="full_scan",
            status="queued",
            attempts=0,
            available_at=now,
            created_at=now - timedelta(minutes=1),
            updated_at=now - timedelta(minutes=1),
        )
        self.db.add_all([diagnosis, older_background, newer_background])
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            first_page = self.client.get(
                "/api/v1/exception-jobs/page?job_kind=all&limit=2&offset=0",
                headers=self.admin_headers,
            )
            second_page = self.client.get(
                "/api/v1/exception-jobs/page?job_kind=all&limit=2&offset=2",
                headers=self.admin_headers,
            )

        self.assertEqual(first_page.status_code, 200, first_page.text)
        self.assertEqual(second_page.status_code, 200, second_page.text)
        self.assertEqual(first_page.json()["total"], 3)
        self.assertEqual(second_page.json()["total"], 3)
        combined = first_page.json()["items"] + second_page.json()["items"]
        self.assertEqual(
            [item["job_no"] for item in combined],
            [newer_background.job_no, diagnosis.job_no, older_background.job_no],
        )
        self.assertEqual([item["job_kind"] for item in combined], ["background", "diagnosis", "background"])
        self.assertEqual(len({(item["job_kind"], item["id"]) for item in combined}), 3)

    def test_unassigned_batch_filter_and_aggregation_include_null_batches(self) -> None:
        unassigned = self._case("BATCH-UNASSIGNED")
        assigned = self._case("BATCH-ASSIGNED")
        assigned.source_batch_kind = "legacy"
        assigned.source_batch_id = 42
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            page = self.client.get(
                "/api/v1/exceptions/page?source_batch_unassigned=true",
                headers=self.admin_headers,
            )
            groups = self.client.get(
                "/api/v1/exceptions/aggregations?group_by=batch",
                headers=self.admin_headers,
            )
            drilldown = self.client.get(
                "/api/v1/exceptions/aggregations?group_by=rule&source_batch_unassigned=true",
                headers=self.admin_headers,
            )
            conflict = self.client.get(
                "/api/v1/exceptions/page?source_batch_id=42&source_batch_unassigned=true",
                headers=self.admin_headers,
            )

        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual([item["case_no"] for item in page.json()["items"]], [unassigned.case_no])
        self.assertIsNone(page.json()["items"][0]["source_batch_kind"])
        self.assertEqual(groups.status_code, 200, groups.text)
        by_key = {item["key"]: item for item in groups.json()["groups"]}
        self.assertEqual(by_key["unassigned"]["label"], "未关联批次")
        self.assertEqual(by_key["unassigned"]["count"], 1)
        self.assertEqual(by_key["legacy:42"]["count"], 1)
        self.assertEqual(by_key["legacy:42"]["source_batch_kind"], "legacy")
        self.assertEqual(by_key["legacy:42"]["source_batch_id"], 42)
        self.assertEqual(drilldown.status_code, 200, drilldown.text)
        self.assertEqual(sum(item["count"] for item in drilldown.json()["groups"]), 1)
        self.assertEqual(conflict.status_code, 422, conflict.text)

    def test_same_numeric_batch_id_is_partitioned_by_kind_for_groups_and_drilldown(self) -> None:
        import_case = self._case("BATCH-COLLISION-IMPORT")
        import_case.source_batch_kind = "import"
        import_case.source_batch_id = 77
        check_case = self._case("BATCH-COLLISION-CHECK", source_type="inventory_check_result")
        check_case.source_batch_kind = "inventory_check"
        check_case.source_batch_id = 77
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            groups = self.client.get(
                "/api/v1/exceptions/aggregations?group_by=batch",
                headers=self.admin_headers,
            )
            import_page = self.client.get(
                "/api/v1/exceptions/page?source_batch_kind=import&source_batch_id=77",
                headers=self.admin_headers,
            )
            check_rules = self.client.get(
                "/api/v1/exceptions/aggregations?group_by=rule&source_batch_kind=inventory_check&source_batch_id=77",
                headers=self.admin_headers,
            )
            ambiguous = self.client.get(
                "/api/v1/exceptions/page?source_batch_id=77",
                headers=self.admin_headers,
            )

        self.assertEqual(groups.status_code, 200, groups.text)
        by_key = {item["key"]: item for item in groups.json()["groups"]}
        self.assertEqual(by_key["import:77"]["label"], "导入批次 77")
        self.assertEqual(by_key["inventory_check:77"]["label"], "库存核验批次 77")
        self.assertEqual(import_page.status_code, 200, import_page.text)
        self.assertEqual([item["case_no"] for item in import_page.json()["items"]], [import_case.case_no])
        self.assertEqual(check_rules.status_code, 200, check_rules.text)
        self.assertEqual(sum(item["count"] for item in check_rules.json()["groups"]), 1)
        self.assertEqual(ambiguous.status_code, 422, ambiguous.text)

    def test_unassigned_batch_group_is_not_truncated_by_the_aggregation_limit(self) -> None:
        unassigned = self._case("BATCH-LIMIT-UNASSIGNED")
        for batch_id in range(1, 202):
            case = self._case(f"BATCH-LIMIT-{batch_id}")
            case.source_batch_kind = "legacy"
            case.source_batch_id = batch_id
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.get(
                "/api/v1/exceptions/aggregations?group_by=batch",
                headers=self.admin_headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["groups"]), 200)
        self.assertEqual(response.json()["total"], 202)
        self.assertTrue(response.json()["truncated"])
        self.assertEqual(response.json()["groups"][0]["key"], "unassigned")
        self.assertEqual(response.json()["groups"][0]["label"], "未关联批次")
        self.assertEqual(response.json()["groups"][0]["count"], 1)
        self.assertEqual(unassigned.source_batch_id, None)

    def test_source_batch_kind_and_id_must_be_persisted_as_a_pair(self) -> None:
        id_only = self._case("BATCH-PAIR-ID-ONLY")
        id_only.source_batch_id = 9
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

        kind_only = self._case("BATCH-PAIR-KIND-ONLY")
        kind_only.source_batch_kind = "import"
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_retry_and_cancel_lock_advisory_then_job_then_case(self) -> None:
        case = self._case("JOB-LOCK-ORDER")
        case.status = "blocked"
        policy = self.db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
        policy.manual_ai_daily_limit = 0
        job = ExceptionDiagnosisJob(
            job_no="EXJOB-WORKFLOW-LOCK-ORDER",
            case_id=case.id,
            evidence_version=case.evidence_version,
            trigger_type="manual",
            status="failed",
            attempts=1,
            available_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        self.db.add(job)
        self.db.commit()
        order: list[str] = []
        real_job_lock = exception_routes._diagnosis_job_for_update
        real_case_lock = exception_routes._exception_case_for_update

        def advisory(db):  # noqa: ANN001, ARG001
            order.append("advisory")

        def lock_job(db, job_id):  # noqa: ANN001
            order.append("job")
            return real_job_lock(db, job_id)

        def lock_case(db, case_id):  # noqa: ANN001
            order.append("case")
            return real_case_lock(db, case_id)

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.settings.exception_ai_enabled", True),
            patch("app.api.routes.exceptions.acquire_exception_case_mutation_lock", side_effect=advisory),
            patch("app.api.routes.exceptions._diagnosis_job_for_update", side_effect=lock_job),
            patch("app.api.routes.exceptions._exception_case_for_update", side_effect=lock_case),
        ):
            retried = self.client.post(
                f"/api/v1/exception-jobs/{job.id}/retry",
                json={"reason": "Retry under ordered locks"},
                headers=self.admin_headers,
            )
            cancelled = self.client.post(
                f"/api/v1/exception-jobs/{job.id}/cancel",
                json={"reason": "Cancel under ordered locks"},
                headers=self.admin_headers,
            )

        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(order, ["advisory", "job", "case", "advisory", "job", "case"])

    def test_policy_patch_preserves_unspecified_fields_and_writes_audit(self) -> None:
        policy = self.db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
        policy.full_scan_cron = "15 2 * * *"
        policy.digest_cron = "45 8 * * *"
        policy.settings_json = {"retained": True}
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.patch(
                "/api/v1/exception-policies",
                json={
                    "expected_updated_at": policy.updated_at.isoformat(),
                    "manual_ai_enabled": False,
                },
                headers=self.admin_headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["manual_ai_enabled"])
        self.assertTrue(payload["is_enabled"])
        self.assertEqual(payload["full_scan_cron"], "15 2 * * *")
        self.assertEqual(payload["digest_cron"], "45 8 * * *")
        self.assertEqual(payload["settings"], {"retained": True})
        audit = self.db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action_type == "update_exception_policy",
                AuditLog.resource_type == "exception_policy",
            )
            .order_by(AuditLog.id.desc())
        )
        self.assertIsNotNone(audit)
        self.assertTrue(audit.before_data["manual_ai_enabled"])
        self.assertFalse(audit.after_data["manual_ai_enabled"])
        self.assertEqual(audit.after_data["settings"], {"retained": True})

    def test_policy_patch_rejects_stale_microsecond_version(self) -> None:
        policy = self.db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
        expected_updated_at = policy.updated_at.isoformat()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            first = self.client.patch(
                "/api/v1/exception-policies",
                json={
                    "expected_updated_at": expected_updated_at,
                    "manual_ai_daily_limit": 19,
                },
                headers=self.admin_headers,
            )
            stale = self.client.patch(
                "/api/v1/exception-policies",
                json={
                    "expected_updated_at": expected_updated_at,
                    "scheduled_ai_enabled": True,
                },
                headers=self.admin_headers,
            )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertNotEqual(first.json()["updated_at"], expected_updated_at)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["error_code"], "exception_policy_version_conflict")
        self.db.refresh(policy)
        self.assertEqual(policy.manual_ai_daily_limit, 19)
        self.assertFalse(policy.scheduled_ai_enabled)

    def test_global_scan_requires_all_source_permissions_and_unrestricted_scope(self) -> None:
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases", return_value={"scanned": 0}) as scan,
        ):
            denied_permission = self.client.post(
                "/api/v1/exceptions/scan?domains=inventory",
                headers=self.limited_headers,
            )

        self.assertEqual(denied_permission.status_code, 403, denied_permission.text)
        scan.assert_not_called()

        self.db.add(
            DataScopeRule(
                subject_type="user",
                subject_id=str(self.admin.id),
                resource_type="inventory_snapshot",
                scope_mode="own",
                scope_value=None,
            )
        )
        self.db.commit()
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases", return_value={"scanned": 0}) as scan,
        ):
            denied_scope = self.client.post(
                "/api/v1/exceptions/scan?domains=inventory",
                headers=self.admin_headers,
            )
        self.assertEqual(denied_scope.status_code, 403, denied_scope.text)
        scan.assert_not_called()

        rule = self.db.scalar(
            select(DataScopeRule).where(
                DataScopeRule.subject_type == "user",
                DataScopeRule.subject_id == str(self.admin.id),
                DataScopeRule.resource_type == "inventory_snapshot",
            )
        )
        rule.scope_mode = "all"
        self.db.commit()
        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.sync_exception_cases", return_value={"scanned": 0}) as scan,
        ):
            allowed = self.client.post(
                "/api/v1/exceptions/scan?domains=inventory",
                headers=self.admin_headers,
            )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        scan.assert_called_once()

    def test_batch_mutation_acquires_scan_lock_before_case_rows(self) -> None:
        case = self._case("BATCH-LOCK-ORDER")
        self.db.commit()
        order: list[str] = []
        real_visible_cases = exception_routes._visible_cases_or_404

        def acquire_lock(db):  # noqa: ANN001, ARG001
            order.append("advisory")

        def lock_rows(db, user, case_nos):  # noqa: ANN001
            order.append("rows")
            return real_visible_cases(db, user, case_nos)

        with (
            patch("app.api.routes.exceptions.settings.exception_center_enabled", True),
            patch("app.api.routes.exceptions.acquire_exception_case_mutation_lock", side_effect=acquire_lock),
            patch("app.api.routes.exceptions._visible_cases_or_404", side_effect=lock_rows),
        ):
            response = self.client.post(
                "/api/v1/exceptions/batch/assign",
                json={"case_nos": [case.case_no], "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
                headers=self.admin_headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(order, ["advisory", "rows"])

    def test_exception_search_limits_are_consistent(self) -> None:
        query = "x" * 201
        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            page = self.client.get(f"/api/v1/exceptions/page?q={query}", headers=self.admin_headers)
            groups = self.client.get(
                f"/api/v1/exceptions/aggregations?group_by=rule&q={query}",
                headers=self.admin_headers,
            )

        self.assertEqual(page.status_code, 422, page.text)
        self.assertEqual(groups.status_code, 422, groups.text)

    def test_quality_endpoint_returns_feedback_metrics_for_each_dimension(self) -> None:
        case = self._case("QUALITY")
        diagnosis = self._diagnosis(case)
        diagnosis.feedback_rating = "partial"
        diagnosis.feedback_by_user_id = self.admin.id
        diagnosis.feedback_at = datetime.now(timezone.utc)
        diagnosis.prompt_version = "prompt-v1"
        diagnosis.contract_version = "contract-v1"
        diagnosis.latency_ms = 125
        diagnosis.prompt_tokens = 10
        diagnosis.completion_tokens = 5
        diagnosis.total_tokens = 15
        zero_usage = self._diagnosis(case)
        zero_usage.prompt_version = "prompt-v1"
        zero_usage.contract_version = "contract-v1"
        zero_usage.latency_ms = 75
        zero_usage.prompt_tokens = 0
        zero_usage.completion_tokens = 0
        zero_usage.total_tokens = 0
        missing_usage = self._diagnosis(case)
        missing_usage.prompt_version = "prompt-v1"
        missing_usage.contract_version = "contract-v1"
        missing_usage.latency_ms = 100
        partial_usage = self._diagnosis(case)
        partial_usage.prompt_version = "prompt-v1"
        partial_usage.contract_version = "contract-v1"
        partial_usage.latency_ms = 90
        partial_usage.prompt_tokens = 4
        partial_usage.completion_tokens = 2
        partial_usage.total_tokens = None
        self.db.commit()

        with patch("app.api.routes.exceptions.settings.exception_center_enabled", True):
            response = self.client.get("/api/v1/exception-diagnoses/quality", headers=self.admin_headers)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["total_diagnoses"], 4)
        self.assertEqual(payload["rated_diagnoses"], 1)
        self.assertEqual(payload["partial"], 1)
        self.assertEqual(payload["total_tokens"], 15)
        self.assertEqual(payload["usage_reported_count"], 2)
        self.assertEqual(payload["usage_missing_count"], 2)
        self.assertEqual(payload["usage_completeness_rate"], 0.5)
        for dimension in (
            "by_domain",
            "by_rule",
            "by_model",
            "by_prompt_version",
            "by_contract_version",
            "by_root_cause_code",
        ):
            self.assertEqual(payload[dimension][0]["diagnoses"], 4)
            self.assertEqual(payload[dimension][0]["rated"], 1)
            self.assertEqual(payload[dimension][0]["partial"], 1)
            self.assertEqual(payload[dimension][0]["usage_reported_count"], 2)
            self.assertEqual(payload[dimension][0]["usage_missing_count"], 2)
            self.assertEqual(payload[dimension][0]["usage_completeness_rate"], 0.5)
        self.assertEqual(self.db.scalar(select(func.count(ExceptionEvent.id))), 0)


if __name__ == "__main__":
    unittest.main()
