import unittest
from unittest.mock import call, patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.crm_projects import (
    create_crm_followup,
    create_crm_project_task,
    update_crm_followup,
    update_crm_task,
)
from app.core.database import Base
from app.models import (
    ApprovalEvent,
    ApprovalInstance,
    CrmFollowup,
    CrmProject,
    CrmProjectCustomerTask,
    CustomerMaster,
    ExceptionBackgroundJob,
    ExceptionPolicy,
    User,
)
from app.schemas.crm import CrmFollowupCreate, CrmFollowupUpdate, CrmTaskCreate, CrmTaskUpdate
from app.services.approval_service import (
    create_approval_instance,
    execute_crm_followup_submit,
    transition_approval,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ExceptionBusinessWriteHookTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(
            username="exception-hook-user",
            password_hash="hash",
            real_name="Exception Hook User",
            role="admin",
            status="active",
            is_active=True,
        )
        self.customer = CustomerMaster(
            customer_code="C-EXCEPTION-HOOK",
            customer_name="Exception Hook Customer",
            status="active",
        )
        self.db.add_all([self.user, self.customer])
        self.db.flush()
        self.project = CrmProject(
            project_code="P-EXCEPTION-HOOK",
            project_name="Exception Hook Project",
            owner_user_id=self.user.id,
            project_manager_user_id=self.user.id,
            status="active",
            approval_status="approved",
            created_by_user_id=self.user.id,
            updated_by_user_id=self.user.id,
        )
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _task(self, task_code: str = "TASK-EXCEPTION-HOOK") -> CrmProjectCustomerTask:
        task = CrmProjectCustomerTask(
            project_id=self.project.id,
            task_code=task_code,
            customer_code=self.customer.customer_code,
            customer_name_snapshot=self.customer.customer_name,
            executor_user_id=self.user.id,
            executor_name_snapshot=self.user.real_name,
            status="in_progress",
        )
        self.db.add(task)
        self.db.commit()
        return task

    def _set_domain_modes(self, *, crm: str, approval: str, baseline_completed: bool = True) -> None:
        policy = self.db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
        if policy is None:
            policy = ExceptionPolicy(policy_key="default")
            self.db.add(policy)
        rollout = {}
        for domain, mode in (("crm", crm), ("approval", approval)):
            if mode == "shadow" and baseline_completed:
                rollout[domain] = {
                    "shadow_cycle": 1,
                    "shadow_started_at": "2026-07-29T00:00:00+00:00",
                    "baseline_completed_at": "2026-07-29T00:01:00+00:00",
                }
        policy.settings_json = {
            "domain_modes": {"crm": crm, "approval": approval},
            "domain_rollout": rollout,
        }
        self.db.commit()

    def test_shadow_business_hook_waits_for_baseline_completion(self):
        self._set_domain_modes(crm="shadow", approval="off", baseline_completed=False)
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            task = create_crm_project_task(
                self.project.id,
                CrmTaskCreate(
                    task_code="TASK-BEFORE-BASELINE",
                    customer_code=self.customer.customer_code,
                    executor_user_id=self.user.id,
                ),
                request=None,
                db=self.db,
                current_user=self.user,
            )
        self.assertEqual(int(self.db.scalar(select(func.count()).select_from(ExceptionBackgroundJob)) or 0), 0)

        self._set_domain_modes(crm="shadow", approval="off", baseline_completed=True)
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            update_crm_task(
                task.id,
                CrmTaskUpdate(status="in_progress"),
                request=None,
                db=self.db,
                current_user=self.user,
            )
        self.assertEqual(int(self.db.scalar(select(func.count()).select_from(ExceptionBackgroundJob)) or 0), 1)

    def test_off_domains_do_not_enqueue_crm_or_approval_jobs(self):
        self._set_domain_modes(crm="off", approval="off")
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            task = create_crm_project_task(
                self.project.id,
                CrmTaskCreate(
                    task_code="TASK-OFF-HOOK",
                    customer_code=self.customer.customer_code,
                    executor_user_id=self.user.id,
                ),
                request=None,
                db=self.db,
                current_user=self.user,
            )
            approval = create_approval_instance(
                self.db,
                approval_type="crm_project_extension",
                resource_type="crm_project",
                resource_id=str(self.project.id),
                title="Off approval hook",
                description=None,
                applicant=self.user,
                current_handler_user_id=self.user.id,
                priority="normal",
                payload_json={"project_id": self.project.id},
                submit=True,
            )
            self.db.commit()

        self.assertIsNotNone(self.db.get(CrmProjectCustomerTask, task.id))
        self.assertIsNotNone(self.db.get(ApprovalInstance, approval.id))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ExceptionBackgroundJob)), 0)

    def test_failed_task_commit_rolls_back_task_and_real_shadow_scan_job(self):
        self._set_domain_modes(crm="shadow", approval="off")

        def fail_commit() -> None:
            self.db.rollback()
            raise RuntimeError("simulated final commit failure")

        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            with patch.object(self.db, "commit", side_effect=fail_commit):
                with self.assertRaisesRegex(RuntimeError, "simulated final commit failure"):
                    create_crm_project_task(
                        self.project.id,
                        CrmTaskCreate(
                            task_code="TASK-ROLLBACK-HOOK",
                            customer_code=self.customer.customer_code,
                            executor_user_id=self.user.id,
                        ),
                        request=None,
                        db=self.db,
                        current_user=self.user,
                    )

        self.db.expire_all()
        self.assertIsNone(
            self.db.scalar(
                select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.task_code == "TASK-ROLLBACK-HOOK")
            )
        )
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ExceptionBackgroundJob)), 0)

    def test_task_and_followup_writes_enqueue_target_scans_before_commit(self):
        with patch("app.api.routes.crm_projects.enqueue_incremental_exception_scan_safely") as enqueue:
            task = create_crm_project_task(
                self.project.id,
                CrmTaskCreate(
                    task_code="TASK-WRITE-HOOK",
                    customer_code=self.customer.customer_code,
                    executor_user_id=self.user.id,
                ),
                request=None,
                db=self.db,
                current_user=self.user,
            )
            enqueue.assert_called_once_with(
                self.db,
                domains=["crm"],
                target_resource_type="crm_project_task",
                target_resource_id=task.id,
            )

            enqueue.reset_mock()
            update_crm_task(
                task.id,
                CrmTaskUpdate(round_target="updated target"),
                request=None,
                db=self.db,
                current_user=self.user,
            )
            enqueue.assert_called_once_with(
                self.db,
                domains=["crm"],
                target_resource_type="crm_project_task",
                target_resource_id=task.id,
            )

            enqueue.reset_mock()
            followup = create_crm_followup(
                CrmFollowupCreate(
                    project_id=self.project.id,
                    task_id=task.id,
                    customer_feedback="customer feedback",
                ),
                request=None,
                db=self.db,
                current_user=self.user,
            )
            self.assertEqual(
                enqueue.call_args_list,
                [
                    call(
                        self.db,
                        domains=["crm"],
                        target_resource_type="crm_followup",
                        target_resource_id=followup.id,
                    ),
                    call(
                        self.db,
                        domains=["crm"],
                        target_resource_type="crm_project_task",
                        target_resource_id=task.id,
                    ),
                ],
            )

            enqueue.reset_mock()
            with patch("app.api.routes.crm_projects.has_permission", return_value=True):
                update_crm_followup(
                    followup.id,
                    CrmFollowupUpdate(customer_feedback="updated feedback"),
                    request=None,
                    db=self.db,
                    current_user=self.user,
                )
            self.assertEqual(
                enqueue.call_args_list,
                [
                    call(
                        self.db,
                        domains=["crm"],
                        target_resource_type="crm_followup",
                        target_resource_id=followup.id,
                    ),
                    call(
                        self.db,
                        domains=["crm"],
                        target_resource_type="crm_project_task",
                        target_resource_id=task.id,
                    ),
                ],
            )

    def test_approved_followup_enqueues_followup_and_refreshed_task(self):
        task = self._task("TASK-APPROVED-FOLLOWUP")
        approval = ApprovalInstance(
            approval_no="APPR-APPROVED-FOLLOWUP",
            approval_type="crm_followup_submit",
            resource_type="crm_followup",
            resource_id="pending",
            title="Approve followup",
            applicant_user_id=self.user.id,
            current_handler_user_id=self.user.id,
            status="submitted",
            priority="normal",
            payload_json={
                "followup": CrmFollowupCreate(
                    project_id=self.project.id,
                    task_id=task.id,
                    customer_feedback="approved feedback",
                ).model_dump(mode="json")
            },
        )
        self.db.add(approval)
        self.db.flush()

        with patch("app.services.approval_service.enqueue_incremental_exception_scan_safely") as enqueue:
            result = execute_crm_followup_submit(
                self.db,
                approval,
                self.user,
                {"review_status": "approved"},
            )

        followup = self.db.get(CrmFollowup, result["followup_id"])
        self.assertIsNotNone(followup)
        self.assertEqual(result["task_id"], task.id)
        self.assertEqual(
            enqueue.call_args_list,
            [
                call(
                    self.db,
                    domains=["crm"],
                    target_resource_type="crm_followup",
                    target_resource_id=followup.id,
                ),
                call(
                    self.db,
                    domains=["crm"],
                    target_resource_type="crm_project_task",
                    target_resource_id=task.id,
                ),
            ],
        )

    def test_approval_create_and_scan_job_rollback_together(self):
        self._set_domain_modes(crm="off", approval="shadow")
        transaction = self.db.begin()
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            approval = create_approval_instance(
                self.db,
                approval_type="crm_project_extension",
                resource_type="crm_project",
                resource_id=str(self.project.id),
                title="Rollback approval creation",
                description=None,
                applicant=self.user,
                current_handler_user_id=self.user.id,
                priority="normal",
                payload_json={"project_id": self.project.id},
                submit=True,
            )
            approval_id = approval.id
            job = self.db.scalar(select(ExceptionBackgroundJob))
            self.assertIsNotNone(job)
            self.assertEqual(job.payload_json["target_resource_type"], "approval_instance")
            self.assertEqual(job.payload_json["target_resource_id"], str(approval.id))
        transaction.rollback()

        self.assertIsNone(self.db.get(ApprovalInstance, approval_id))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ExceptionBackgroundJob)), 0)

    def test_approval_transition_and_scan_job_rollback_together(self):
        self._set_domain_modes(crm="off", approval="off")
        with patch("app.services.exception_center_service.settings.exception_center_enabled", False):
            approval = create_approval_instance(
                self.db,
                approval_type="crm_project_extension",
                resource_type="crm_project",
                resource_id=str(self.project.id),
                title="Rollback approval transition",
                description=None,
                applicant=self.user,
                current_handler_user_id=self.user.id,
                priority="normal",
                payload_json={"project_id": self.project.id},
                submit=True,
            )
        self.db.commit()
        approval_id = approval.id
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ExceptionBackgroundJob)), 0)
        initial_event_count = self.db.scalar(
            select(func.count()).select_from(ApprovalEvent).where(ApprovalEvent.approval_id == approval_id)
        )
        self.db.commit()
        self._set_domain_modes(crm="off", approval="shadow")

        transaction = self.db.begin()
        approval = self.db.get(ApprovalInstance, approval_id)
        with patch("app.services.exception_center_service.settings.exception_center_enabled", True):
            transition_approval(
                self.db,
                approval=approval,
                operator=self.user,
                event_type="reject",
                to_status="rejected",
                comment="rollback transition",
            )
            self.db.flush()
            self.assertEqual(approval.status, "rejected")
            self.assertIsNotNone(self.db.scalar(select(ExceptionBackgroundJob)))
        transaction.rollback()

        self.db.expire_all()
        self.assertEqual(self.db.get(ApprovalInstance, approval_id).status, "submitted")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ExceptionBackgroundJob)), 0)
        self.assertEqual(
            self.db.scalar(
                select(func.count()).select_from(ApprovalEvent).where(ApprovalEvent.approval_id == approval_id)
            ),
            initial_event_count,
        )


if __name__ == "__main__":
    unittest.main()
