import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import app.models  # noqa: F401 - register all foreign-key targets
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.exception_center import (
    ExceptionCase,
    ExceptionDiagnosis,
    ExceptionDiagnosisJob,
    ExceptionEvidence,
    ExceptionEvent,
    ExceptionNotification,
    ExceptionPolicy,
    ExceptionServiceHeartbeat,
)
from app.models.identity import AuditLog
from app.services.exception_task_service import (
    JobLeaseLostError,
    _fail_or_retry_job,
    _reserve_ai_call_budget,
    _today_ai_call_count,
    claim_diagnosis_job,
    complete_cancelled_diagnosis_job,
    enqueue_incremental_scan,
    exception_ops_summary,
    execute_diagnosis_job,
    handoff_diagnosis_jobs_for_worker,
    heartbeat_diagnosis_job,
    latest_persisted_ai_circuit_state,
    record_service_heartbeat,
)
from app.services.exception_center_service import enqueue_due_ai_diagnoses
from app.services.hermes_ai_service import (
    ExceptionDiagnosis as AiDiagnosis,
    HermesCallMetadata,
    HermesStructuredDiagnosis,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ARG001
    return "JSON"


class ExceptionTaskServiceTest(unittest.TestCase):
    def setUp(self):
        self.ai_enabled_patch = patch(
            "app.services.exception_task_service.settings.exception_ai_enabled",
            True,
        )
        self.ai_enabled_patch.start()
        self.addCleanup(self.ai_enabled_patch.stop)
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.SessionLocal()
        self.case = ExceptionCase(
            case_no="EXC-TEST-1",
            fingerprint="fingerprint-1",
            domain="inventory",
            rule_code="inventory.negative_stock",
            title="Negative inventory",
            severity="high",
            status="open",
            source_type="inventory_snapshot",
            evidence_version="ev-1",
            reason="Stock quantity is negative",
        )
        self.db.add(self.case)
        self.db.flush()
        self.db.add(
            ExceptionEvidence(
                case_id=self.case.id,
                evidence_version="ev-1",
                data_json={
                    "allowed_root_cause_codes": ["warehouse_missing"],
                    "evidence": [{"ref": "snapshot:1", "stock_qty": -2}],
                },
            )
        )
        self.job = ExceptionDiagnosisJob(
            job_no="EXJOB-TEST-1",
            case_id=self.case.id,
            evidence_version="ev-1",
            trigger_type="manual",
            status="queued",
            available_at=datetime.now(timezone.utc),
        )
        self.policy = ExceptionPolicy(
            policy_key="default",
            is_enabled=True,
            manual_ai_enabled=True,
            scheduled_ai_enabled=True,
            full_scan_enabled=False,
            digest_enabled=False,
            full_scan_cron="30 2 * * *",
            digest_cron="30 8 * * *",
            ai_daily_limit=100,
            ai_batch_limit=50,
            manual_ai_daily_limit=100,
            scheduled_ai_daily_limit=100,
            scheduled_ai_batch_limit=50,
            ai_concurrency=1,
            stale_diagnosis_hours=24,
        )
        self.db.add_all([self.job, self.policy])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _structured_result(self, *, summary: str = "当前记录缺少仓库映射。") -> HermesStructuredDiagnosis:
        now = datetime.now(timezone.utc)
        return HermesStructuredDiagnosis(
            diagnosis=AiDiagnosis(
                root_cause_code="warehouse_missing",
                summary=summary,
                confidence=0.98,
                evidence_refs=["snapshot:1"],
                impact="当前余额无法安全归属到仓库。",
                recommended_steps=["补充仓库映射"],
                missing_evidence=[],
                disposition="actionable",
            ),
            metadata=HermesCallMetadata(
                provider_host="ai.example",
                model="test-model",
                request_id="exception-ai-test-result",
                provider_request_id="provider-test-result",
                started_at=now,
                completed_at=now,
                latency_ms=10,
                attempts=1,
                total_tokens=20,
                evidence_bytes=321,
                evidence_approx_tokens=81,
                evidence_truncated=True,
            ),
        )

    def test_claim_uses_lease_and_prevents_duplicate_claim(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, "processing")
        self.assertEqual(claimed.lease_owner, "worker-1")
        self.assertEqual(claimed.attempts, 1)
        with self.SessionLocal() as second_db:
            self.assertIsNone(claim_diagnosis_job(second_db, worker_id="worker-2"))

    def test_expired_lease_is_recovered(self):
        self.job.status = "processing"
        self.job.lease_owner = "dead-worker"
        self.job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.db.commit()
        recovered = claim_diagnosis_job(self.db, worker_id="worker-2")
        self.assertEqual(recovered.id, self.job.id)
        self.assertEqual(recovered.lease_owner, "worker-2")

    def test_processing_job_without_lease_is_recovered(self):
        self.job.status = "processing"
        self.job.lease_owner = "dead-worker"
        self.job.lease_expires_at = None
        self.db.commit()
        recovered = claim_diagnosis_job(self.db, worker_id="worker-2")
        self.assertEqual(recovered.id, self.job.id)
        self.assertEqual(recovered.lease_owner, "worker-2")

    def test_policy_concurrency_blocks_additional_active_lease(self):
        self.policy.ai_concurrency = 1
        second_case = ExceptionCase(
            case_no="EXC-TEST-CONCURRENCY",
            fingerprint="fingerprint-concurrency",
            domain="inventory",
            rule_code="inventory.negative_stock",
            title="Second negative inventory case",
            severity="high",
            status="open",
            source_type="inventory_snapshot",
            evidence_version="ev-concurrency",
            reason="A separate case is waiting for the same worker pool.",
        )
        self.db.add(second_case)
        self.db.flush()
        second_job = ExceptionDiagnosisJob(
            job_no="EXJOB-TEST-CONCURRENCY",
            case_id=second_case.id,
            evidence_version="ev-concurrency",
            trigger_type="manual",
            status="queued",
            available_at=datetime.now(timezone.utc),
        )
        self.db.add(second_job)
        self.db.commit()
        first = claim_diagnosis_job(self.db, worker_id="worker-1")
        self.assertIsNotNone(first)
        with self.SessionLocal() as second_db:
            blocked = claim_diagnosis_job(second_db, worker_id="worker-2")
        self.assertIsNone(blocked)

    def test_execute_persists_structured_result_and_counts_call_event(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        now = datetime.now(timezone.utc)
        result = HermesStructuredDiagnosis(
            diagnosis=AiDiagnosis(
                root_cause_code="warehouse_missing",
                summary="当前记录缺少仓库映射。",
                confidence=0.98,
                evidence_refs=["snapshot:1"],
                impact="当前余额无法安全归属到仓库。",
                recommended_steps=["补充仓库映射", "重新执行核验"],
                missing_evidence=[],
                disposition="actionable",
            ),
            metadata=HermesCallMetadata(
                provider_host="ai.example",
                model="test-model",
                request_id="exception-ai-test",
                provider_request_id="provider-test",
                started_at=now,
                completed_at=now,
                latency_ms=10,
                attempts=1,
                total_tokens=20,
                evidence_bytes=321,
                evidence_approx_tokens=81,
                evidence_truncated=True,
            ),
        )

        usage_requirements = []

        def successful_provider_call(*args, before_http_attempt=None, **kwargs):  # noqa: ANN002, ANN003, ARG001
            self.assertIsNotNone(before_http_attempt)
            usage_requirements.append(kwargs.get("require_complete_usage"))
            before_http_attempt(1)
            return result

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=successful_provider_call,
            ),
            patch("app.services.exception_task_service.settings.exception_ai_daily_limit", 100),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")
        self.assertEqual(status, "completed")
        refresh_job = ExceptionDiagnosisJob(
            job_no="EXJOB-TEST-REFRESH",
            case_id=self.case.id,
            evidence_version="ev-1",
            trigger_type="scheduled",
            status="queued",
            available_at=datetime.now(timezone.utc),
        )
        self.db.add(refresh_job)
        self.db.commit()
        claimed_refresh = claim_diagnosis_job(self.db, worker_id="worker-2")
        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=successful_provider_call,
            ),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            refresh_status = execute_diagnosis_job(job_id=claimed_refresh.id, worker_id="worker-2")
        self.assertEqual(refresh_status, "completed")
        self.db.expire_all()
        diagnoses = list(
            self.db.scalars(
                select(ExceptionDiagnosis)
                .where(ExceptionDiagnosis.case_id == self.case.id)
                .order_by(ExceptionDiagnosis.id)
            ).all()
        )
        self.assertEqual(len(diagnoses), 2)
        diagnosis = diagnoses[-1]
        self.assertEqual(diagnosis.root_cause_code, "warehouse_missing")
        self.assertEqual(diagnosis.impact_json, {"summary": "当前余额无法安全归属到仓库。"})
        self.assertEqual(diagnosis.model_name, "test-model")
        self.assertEqual(diagnosis.provider_request_id, "provider-test")
        self.assertEqual(diagnosis.prompt_version, "exception-diagnosis-2026-08-30.v4")
        self.assertEqual(diagnosis.contract_version, "exception-diagnosis-json.zh-cn.v2")
        self.assertEqual(diagnosis.latency_ms, 10)
        self.assertEqual(diagnosis.total_tokens, 20)
        self.assertEqual(self.db.get(ExceptionCase, self.case.id).status, "action_required")
        events = list(self.db.scalars(select(ExceptionEvent).where(ExceptionEvent.case_id == self.case.id)).all())
        self.assertIn("diagnosis_ai_call_started", {event.event_type for event in events})
        self.assertIn("diagnosed", {event.event_type for event in events})
        self.assertEqual(usage_requirements, [True, False])
        diagnosed_event = [event for event in events if event.event_type == "diagnosed"][-1]
        self.assertEqual(diagnosed_event.detail_json["diagnosis_id"], diagnosis.id)
        self.assertEqual(diagnosed_event.detail_json["job_id"], refresh_job.id)
        self.assertEqual(diagnosed_event.detail_json["evidence_version"], diagnosis.evidence_version)
        self.assertEqual(diagnosed_event.detail_json["model_call"]["evidence_bytes"], 321)
        self.assertEqual(diagnosed_event.detail_json["model_call"]["evidence_approx_tokens"], 81)
        self.assertTrue(diagnosed_event.detail_json["model_call"]["evidence_truncated"])

    def test_incremental_scan_dedupes_only_active_job_and_merges_domains(self):
        first, reused = enqueue_incremental_scan(
            self.db,
            domains=["import"],
            source_batch_kind="import",
            source_batch_id=91,
        )
        self.assertFalse(reused)
        second, reused = enqueue_incremental_scan(
            self.db,
            domains=["inventory"],
            source_batch_kind="import",
            source_batch_id=91,
        )
        self.assertTrue(reused)
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.payload_json["domains"], ["import", "inventory"])
        self.assertEqual(second.payload_json["source_batch_kind"], "import")

        check_job, reused = enqueue_incremental_scan(
            self.db,
            domains=["inventory"],
            source_batch_kind="inventory_check",
            source_batch_id=91,
        )
        self.assertFalse(reused)
        self.assertNotEqual(check_job.id, first.id)
        self.assertEqual(check_job.dedupe_key, "incremental:inventory_check:91")
        self.assertEqual(check_job.payload_json["source_batch_kind"], "inventory_check")

        first.status = "processing"
        self.db.flush()
        replacement, reused = enqueue_incremental_scan(
            self.db,
            domains=["master_data"],
            source_batch_kind="import",
            source_batch_id=91,
        )
        self.assertFalse(reused)
        self.assertNotEqual(replacement.id, first.id)
        self.assertIsNone(first.dedupe_key)
        self.assertEqual(replacement.dedupe_key, "incremental:import:91")
        self.assertEqual(replacement.payload_json["domains"], ["master_data"])

        merged_followup, reused = enqueue_incremental_scan(
            self.db,
            domains=["receivable"],
            source_batch_kind="import",
            source_batch_id=91,
        )
        self.assertTrue(reused)
        self.assertEqual(merged_followup.id, replacement.id)
        self.assertEqual(merged_followup.payload_json["domains"], ["master_data", "receivable"])

    def test_incremental_scan_requires_a_complete_typed_batch_reference(self):
        with self.assertRaisesRegex(ValueError, "must be provided together"):
            enqueue_incremental_scan(self.db, domains=["import"], source_batch_id=91)
        with self.assertRaisesRegex(ValueError, "must be provided together"):
            enqueue_incremental_scan(self.db, domains=["import"], source_batch_kind="import")
        with self.assertRaisesRegex(ValueError, "Unsupported source batch kind"):
            enqueue_incremental_scan(
                self.db,
                domains=["import"],
                source_batch_kind="unknown",
                source_batch_id=91,
            )

    def test_global_incremental_scan_merges_queued_and_preserves_processing_followup(self):
        queued, reused = enqueue_incremental_scan(self.db, domains=["master_data"])
        self.assertFalse(reused)
        self.assertEqual(queued.dedupe_key, "incremental:global")

        merged, reused = enqueue_incremental_scan(self.db, domains=["inventory"])
        self.assertTrue(reused)
        self.assertEqual(merged.id, queued.id)
        self.assertEqual(merged.payload_json["domains"], ["inventory", "master_data"])

        queued.status = "processing"
        self.db.flush()
        followup, reused = enqueue_incremental_scan(self.db, domains=["receivable"])
        self.assertFalse(reused)
        self.assertNotEqual(followup.id, queued.id)
        self.assertIsNone(queued.dedupe_key)
        self.assertEqual(followup.dedupe_key, "incremental:global")
        self.assertEqual(followup.payload_json["domains"], ["receivable"])

    def test_ai_daily_budget_reservation_is_atomic_at_limit(self):
        self.policy.manual_ai_daily_limit = 1
        self.policy.ai_concurrency = 2
        self.db.commit()
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        first, _ = _reserve_ai_call_budget(
            self.db,
            case=self.case,
            job=claimed,
            request_id="budget-call-1",
        )
        second, reason = _reserve_ai_call_budget(
            self.db,
            case=self.case,
            job=claimed,
            request_id="budget-call-2",
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(reason, "Manual AI diagnosis daily limit reached")
        reservations = list(
            self.db.scalars(
                select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_ai_call_started")
            ).all()
        )
        self.assertEqual(len(reservations), 1)

    def test_zero_daily_limit_allows_unlimited_provider_reservations(self):
        self.policy.manual_ai_daily_limit = 0
        self.policy.ai_concurrency = 1
        self.db.commit()
        claimed = claim_diagnosis_job(self.db, worker_id="worker-unlimited")

        first, first_reason = _reserve_ai_call_budget(
            self.db,
            case=self.case,
            job=claimed,
            request_id="unlimited-call-1",
        )
        second, second_reason = _reserve_ai_call_budget(
            self.db,
            case=self.case,
            job=claimed,
            request_id="unlimited-call-2",
        )

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertIsNone(first_reason)
        self.assertIsNone(second_reason)
        self.assertEqual(_today_ai_call_count(self.db, trigger_type="manual"), 2)

    def test_provider_canary_attempt_consumes_manual_but_not_scheduled_budget(self):
        self.policy.manual_ai_daily_limit = 1
        self.db.add_all(
            [
                AuditLog(
                    action_type="exception_provider_call_started",
                    resource_type="exception_provider_canary",
                    resource_id="provider-canary-current",
                    created_at=datetime.now(timezone.utc),
                ),
                AuditLog(
                    action_type="exception_provider_canary_completed",
                    resource_type="exception_provider_canary",
                    resource_id="provider-canary-current",
                    created_at=datetime.now(timezone.utc),
                ),
                AuditLog(
                    action_type="exception_provider_call_started",
                    resource_type="unrelated_resource",
                    resource_id="not-a-provider-canary",
                    created_at=datetime.now(timezone.utc),
                ),
            ]
        )
        self.db.commit()

        self.assertEqual(_today_ai_call_count(self.db, trigger_type="manual"), 1)
        self.assertEqual(_today_ai_call_count(self.db, trigger_type="scheduled"), 0)
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        reserved, reason = _reserve_ai_call_budget(
            self.db,
            case=self.case,
            job=claimed,
            request_id="budget-after-canary",
        )

        self.assertFalse(reserved)
        self.assertEqual(reason, "Manual AI diagnosis daily limit reached")
        self.assertIsNone(
            self.db.scalar(
                select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_ai_call_started")
            )
        )

    def test_expired_lease_cannot_reserve_ai_call_budget(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        generation = claimed.attempts
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.commit()

        with self.assertRaisesRegex(JobLeaseLostError, "lease was lost"):
            _reserve_ai_call_budget(
                self.db,
                case=self.case,
                job=claimed,
                request_id="expired-lease-budget-call",
                worker_id="worker-1",
                lease_generation=generation,
            )

        self.assertIsNone(
            self.db.scalar(
                select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_ai_call_started")
            )
        )

    def test_global_ai_fuse_blocks_budget_reservation_without_event(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        with patch("app.services.exception_task_service.settings.exception_ai_enabled", False):
            reserved, reason = _reserve_ai_call_budget(
                self.db,
                case=self.case,
                job=claimed,
                request_id="global-fuse-test",
            )

        self.assertFalse(reserved)
        self.assertEqual(reason, "Exception AI diagnosis is disabled")
        self.assertEqual(
            self.db.scalar(
                select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_ai_call_started")
            ),
            None,
        )

    def test_cancellation_restores_pre_diagnosis_status_and_records_reason_once(self):
        self.case.status = "processing"
        self.job.cancel_requested_at = datetime.now(timezone.utc)
        self.job.cancel_requested_by_user_id = 99
        self.db.add(
            ExceptionEvent(
                case_id=self.case.id,
                event_type="diagnosis_queued",
                from_status="action_required",
                to_status="processing",
                detail_json={"job_no": self.job.job_no},
            )
        )
        self.db.commit()

        complete_cancelled_diagnosis_job(self.db, self.job, message="Operator cancelled stale request")
        self.db.commit()
        complete_cancelled_diagnosis_job(self.db, self.job, message="Operator cancelled stale request")
        self.db.commit()

        self.db.refresh(self.case)
        self.db.refresh(self.job)
        self.assertEqual(self.job.status, "cancelled")
        self.assertEqual(self.case.status, "action_required")
        events = list(
            self.db.scalars(
                select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_cancelled")
            ).all()
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].detail_json["reason"], "Operator cancelled stale request")
        self.assertEqual(events[0].actor_user_id, 99)

    def test_cancel_retry_cancel_records_two_distinct_audit_events(self):
        first_cancel_at = datetime.now(timezone.utc)
        self.case.status = "processing"
        self.job.status = "processing"
        self.job.attempts = 1
        self.job.cancel_requested_at = first_cancel_at
        self.job.cancel_requested_by_user_id = 99
        self.db.commit()

        complete_cancelled_diagnosis_job(self.db, self.job, message="First cancellation")
        self.db.commit()

        self.job.status = "queued"
        self.job.completed_at = None
        self.job.error_message = None
        self.job.cancel_requested_at = None
        self.job.cancel_requested_by_user_id = None
        self.case.status = "processing"
        self.db.commit()

        self.job.status = "processing"
        self.job.cancel_requested_at = first_cancel_at + timedelta(seconds=5)
        self.job.cancel_requested_by_user_id = 99
        complete_cancelled_diagnosis_job(self.db, self.job, message="Second cancellation")
        self.db.commit()

        events = list(
            self.db.scalars(
                select(ExceptionEvent)
                .where(ExceptionEvent.event_type == "diagnosis_cancelled")
                .order_by(ExceptionEvent.id)
            ).all()
        )
        self.assertEqual(len(events), 2)
        self.assertEqual([event.detail_json["job_id"] for event in events], [self.job.id, self.job.id])
        self.assertNotEqual(
            events[0].detail_json["cancel_requested_at"],
            events[1].detail_json["cancel_requested_at"],
        )

    def test_worker_handoff_requeues_lease_and_stale_thread_cannot_persist(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-old")
        old_generation = claimed.attempts

        with patch("app.services.exception_task_service.SessionLocal", self.SessionLocal):
            handed_off = handoff_diagnosis_jobs_for_worker(worker_id="worker-old")

        self.assertEqual(handed_off, 1)
        self.db.expire_all()
        released = self.db.get(ExceptionDiagnosisJob, claimed.id)
        self.assertEqual(released.status, "queued")
        self.assertIsNone(released.lease_owner)
        self.assertIsNone(released.lease_expires_at)

        reclaimed = claim_diagnosis_job(self.db, worker_id="worker-new")
        self.assertEqual(reclaimed.id, claimed.id)
        self.assertGreater(reclaimed.attempts, old_generation)
        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch("app.services.exception_task_service.call_hermes_exception_diagnosis") as provider_call,
        ):
            stale_status = execute_diagnosis_job(
                job_id=claimed.id,
                worker_id="worker-old",
                lease_generation=old_generation,
            )

        self.assertEqual(stale_status, "lease_lost")
        provider_call.assert_not_called()
        self.db.expire_all()
        self.assertEqual(self.db.get(ExceptionDiagnosisJob, claimed.id).lease_owner, "worker-new")
        self.assertEqual(
            list(self.db.scalars(select(ExceptionDiagnosis).where(ExceptionDiagnosis.job_id == claimed.id)).all()),
            [],
        )

    def test_ai_worker_circuit_heartbeat_is_persisted_and_old_rows_are_pruned(self):
        old = ExceptionServiceHeartbeat(
            service_type="ai_worker",
            instance_id="old-worker",
            started_at=datetime.now(timezone.utc) - timedelta(days=45),
            last_heartbeat_at=datetime.now(timezone.utc) - timedelta(days=45),
            metadata_json={"circuit": {"open": False}},
        )
        self.db.add(old)
        self.db.commit()

        with patch("app.services.exception_task_service.SessionLocal", self.SessionLocal):
            record_service_heartbeat(
                service_type="ai_worker",
                instance_id="active-worker",
                metadata={"circuit": {"open": True, "consecutive_failures": 5, "retry_after_seconds": 60}},
            )

        self.db.expire_all()
        summary = exception_ops_summary(self.db)
        self.assertTrue(summary["circuit"]["open"])
        self.assertEqual(summary["circuit"]["consecutive_failures"], 5)
        self.assertEqual(
            set(summary["circuit"]),
            {"open", "consecutive_failures", "retry_after_seconds", "stale", "source"},
        )
        self.assertFalse(summary["circuit"]["stale"])
        self.assertEqual(summary["circuit"]["source"], "ai_worker")
        instances = {
            row.instance_id
            for row in self.db.scalars(select(ExceptionServiceHeartbeat)).all()
        }
        self.assertEqual(instances, {"active-worker"})

    def test_latest_circuit_state_deducts_worker_downtime_from_cooldown(self):
        heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        self.db.add(
            ExceptionServiceHeartbeat(
                service_type="ai_worker",
                instance_id="previous-worker",
                started_at=heartbeat_at,
                last_heartbeat_at=heartbeat_at,
                metadata_json={
                    "circuit": {
                        "open": True,
                        "consecutive_failures": 5,
                        "retry_after_seconds": 60,
                    }
                },
            )
        )
        self.db.commit()

        with patch("app.services.exception_task_service.SessionLocal", self.SessionLocal):
            state = latest_persisted_ai_circuit_state()

        self.assertIsNotNone(state)
        self.assertTrue(state["open"])
        self.assertEqual(state["consecutive_failures"], 5)
        self.assertGreaterEqual(state["retry_after_seconds"], 29)
        self.assertLessEqual(state["retry_after_seconds"], 30)

    def test_ops_circuit_is_nullable_and_stale_state_only_comes_from_ai_worker(self):
        self.assertIsNone(exception_ops_summary(self.db)["circuit"])
        stale_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        self.db.add(
            ExceptionServiceHeartbeat(
                service_type="ai_worker",
                instance_id="stale-worker",
                started_at=stale_at,
                last_heartbeat_at=stale_at,
                metadata_json={
                    "circuit": {
                        "open": False,
                        "consecutive_failures": 1,
                        "retry_after_seconds": 0,
                    }
                },
            )
        )
        self.db.commit()

        circuit = exception_ops_summary(self.db)["circuit"]

        self.assertIsNotNone(circuit)
        self.assertTrue(circuit["stale"])
        self.assertEqual(circuit["source"], "ai_worker")

    def test_stale_lease_generation_cannot_renew_or_start_provider_call(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        stale_generation = claimed.attempts
        claimed.attempts += 1
        self.db.commit()

        with patch("app.services.exception_task_service.SessionLocal", self.SessionLocal):
            renewed = heartbeat_diagnosis_job(
                job_id=claimed.id,
                worker_id="worker-1",
                lease_generation=stale_generation,
            )
            with patch("app.services.exception_task_service.call_hermes_exception_diagnosis") as provider_call:
                status = execute_diagnosis_job(
                    job_id=claimed.id,
                    worker_id="worker-1",
                    lease_generation=stale_generation,
                )

        self.assertFalse(renewed)
        self.assertEqual(status, "lease_lost")
        provider_call.assert_not_called()

    def test_lease_lost_before_http_reservation_neither_counts_budget_nor_calls_provider(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        generation = claimed.attempts
        provider_http_started = False

        def lose_lease_before_http(*args, before_http_attempt=None, **kwargs):  # noqa: ANN002, ANN003, ARG001
            nonlocal provider_http_started
            with self.SessionLocal() as concurrent_db:
                concurrent_job = concurrent_db.get(ExceptionDiagnosisJob, claimed.id)
                concurrent_job.attempts = generation + 1
                concurrent_db.commit()
            before_http_attempt(1)
            provider_http_started = True
            raise AssertionError("provider HTTP must not start after lease loss")

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=lose_lease_before_http,
            ),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(
                job_id=claimed.id,
                worker_id="worker-1",
                lease_generation=generation,
            )

        self.assertEqual(status, "lease_lost")
        self.assertFalse(provider_http_started)
        self.assertEqual(
            self.db.scalar(
                select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_ai_call_started")
            ),
            None,
        )

    def test_expired_lease_before_http_reservation_neither_counts_budget_nor_calls_provider(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        generation = claimed.attempts
        provider_http_started = False

        def expire_lease_before_http(*args, before_http_attempt=None, **kwargs):  # noqa: ANN002, ANN003, ARG001
            nonlocal provider_http_started
            with self.SessionLocal() as concurrent_db:
                concurrent_job = concurrent_db.get(ExceptionDiagnosisJob, claimed.id)
                concurrent_job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                concurrent_db.commit()
            before_http_attempt(1)
            provider_http_started = True
            raise AssertionError("provider HTTP must not start after lease expiry")

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=expire_lease_before_http,
            ),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(
                job_id=claimed.id,
                worker_id="worker-1",
                lease_generation=generation,
            )

        self.assertEqual(status, "lease_lost")
        self.assertFalse(provider_http_started)
        self.assertIsNone(
            self.db.scalar(
                select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_ai_call_started")
            )
        )

    def test_terminal_ai_failure_blocks_case_instead_of_leaving_processing(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        with patch("app.services.exception_task_service.settings.exception_job_max_attempts", 1):
            _fail_or_retry_job(self.db, claimed, RuntimeError("unsafe provider detail"))
        self.db.expire_all()
        failed_job = self.db.get(ExceptionDiagnosisJob, claimed.id)
        failed_case = self.db.get(ExceptionCase, self.case.id)
        self.assertEqual(failed_job.status, "failed")
        self.assertEqual(failed_case.status, "blocked")
        self.assertNotIn("unsafe provider detail", failed_job.error_message)
        event = self.db.scalar(
            select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_failed")
        )
        self.assertEqual(event.to_status, "blocked")

    def test_unexpected_provider_error_is_safely_failed_without_waiting_for_lease_expiry(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=RuntimeError("api_key=do-not-store; customer private text"),
            ),
            patch("app.services.exception_task_service.settings.exception_job_max_attempts", 1),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")

        self.assertEqual(status, "failed")
        self.db.expire_all()
        failed_job = self.db.get(ExceptionDiagnosisJob, claimed.id)
        failed_case = self.db.get(ExceptionCase, self.case.id)
        self.assertEqual(failed_job.status, "failed")
        self.assertEqual(failed_case.status, "blocked")
        self.assertEqual(failed_job.error_message, "Diagnosis failed (RuntimeError)")
        self.assertNotIn("do-not-store", failed_job.error_message)

    def test_lost_lease_never_persists_diagnosis_or_mutates_new_owner(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.diagnosis_job_heartbeat",
                side_effect=JobLeaseLostError("lost"),
            ),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")
        self.assertEqual(status, "lease_lost")
        self.db.expire_all()
        self.assertEqual(self.db.get(ExceptionDiagnosisJob, claimed.id).status, "processing")
        diagnoses = list(
            self.db.scalars(select(ExceptionDiagnosis).where(ExceptionDiagnosis.case_id == self.case.id)).all()
        )
        self.assertEqual(diagnoses, [])

    def test_evidence_change_during_model_call_cancels_without_persisting_result(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        now = datetime.now(timezone.utc)
        result = HermesStructuredDiagnosis(
            diagnosis=AiDiagnosis(
                root_cause_code="warehouse_missing",
                summary="该结果在模型调用期间已过期。",
                confidence=0.98,
                evidence_refs=["snapshot:1"],
                impact="过期结果不得影响当前案件。",
                recommended_steps=["不要保存该结果"],
                missing_evidence=[],
                disposition="actionable",
            ),
            metadata=HermesCallMetadata(
                provider_host="ai.example",
                model="test-model",
                request_id="exception-ai-stale",
                provider_request_id="provider-stale",
                started_at=now,
                completed_at=now,
                latency_ms=10,
                attempts=1,
                total_tokens=20,
            ),
        )

        def update_evidence_during_call(*args, **kwargs):  # noqa: ANN002, ANN003
            with self.SessionLocal() as concurrent_db:
                concurrent_case = concurrent_db.get(ExceptionCase, self.case.id)
                concurrent_case.evidence_version = "ev-2"
                concurrent_case.status = "open"
                concurrent_db.commit()
            return result

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=update_evidence_during_call,
            ),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")

        self.assertEqual(status, "cancelled")
        self.db.expire_all()
        cancelled_job = self.db.get(ExceptionDiagnosisJob, claimed.id)
        current_case = self.db.get(ExceptionCase, self.case.id)
        self.assertEqual(cancelled_job.status, "cancelled")
        self.assertEqual(cancelled_job.evidence_version, "ev-1")
        self.assertEqual(current_case.evidence_version, "ev-2")
        self.assertEqual(current_case.status, "open")
        self.assertEqual(
            list(self.db.scalars(select(ExceptionDiagnosis).where(ExceptionDiagnosis.job_id == claimed.id)).all()),
            [],
        )
        self.assertEqual(
            list(
                self.db.scalars(
                    select(ExceptionNotification).where(ExceptionNotification.case_id == self.case.id)
                ).all()
            ),
            [],
        )
        self.assertNotIn(
            "diagnosed",
            {
                event.event_type
                for event in self.db.scalars(select(ExceptionEvent).where(ExceptionEvent.case_id == self.case.id)).all()
            },
        )
        cancelled_event = self.db.scalar(
            select(ExceptionEvent).where(ExceptionEvent.event_type == "diagnosis_cancelled")
        )
        self.assertIsNotNone(cancelled_event)
        self.assertEqual(cancelled_event.detail_json["reason_code"], "evidence_superseded")
        self.assertEqual(cancelled_event.detail_json["phase"], "after_generation")
        self.assertEqual(cancelled_event.detail_json["lease_generation"], claimed.attempts)

    def test_resolved_case_before_provider_attempt_is_cancelled_without_http_call(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        with self.SessionLocal() as concurrent_db:
            concurrent_case = concurrent_db.get(ExceptionCase, self.case.id)
            concurrent_case.status = "resolved"
            concurrent_db.commit()

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch("app.services.exception_task_service.call_hermes_exception_diagnosis") as provider_call,
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")

        self.assertEqual(status, "cancelled")
        provider_call.assert_not_called()
        self.db.expire_all()
        self.assertEqual(self.db.get(ExceptionCase, self.case.id).status, "resolved")
        self.assertEqual(self.db.get(ExceptionDiagnosisJob, claimed.id).status, "cancelled")
        self.assertEqual(
            list(self.db.scalars(select(ExceptionDiagnosis).where(ExceptionDiagnosis.job_id == claimed.id)).all()),
            [],
        )

    def test_case_resolved_after_initial_read_is_rechecked_before_http_attempt(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        provider_http_started = False

        def resolve_before_http(*args, before_http_attempt=None, **kwargs):  # noqa: ANN002, ANN003, ARG001
            nonlocal provider_http_started
            with self.SessionLocal() as concurrent_db:
                concurrent_case = concurrent_db.get(ExceptionCase, self.case.id)
                concurrent_case.status = "resolved"
                concurrent_db.commit()
            before_http_attempt(1)
            provider_http_started = True
            raise AssertionError("provider HTTP must not start for a resolved case")

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=resolve_before_http,
            ),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")

        self.assertEqual(status, "cancelled")
        self.assertFalse(provider_http_started)
        self.db.expire_all()
        self.assertEqual(self.db.get(ExceptionCase, self.case.id).status, "resolved")
        self.assertEqual(self.db.get(ExceptionDiagnosisJob, claimed.id).status, "cancelled")

    def test_case_ignored_during_model_call_is_not_reopened_by_successful_result(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        result = self._structured_result(summary="该结果必须被丢弃。")

        def ignore_during_call(*args, before_http_attempt=None, **kwargs):  # noqa: ANN002, ANN003, ARG001
            before_http_attempt(1)
            with self.SessionLocal() as concurrent_db:
                concurrent_case = concurrent_db.get(ExceptionCase, self.case.id)
                concurrent_case.status = "ignored"
                concurrent_db.commit()
            return result

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=ignore_during_call,
            ),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")

        self.assertEqual(status, "cancelled")
        self.db.expire_all()
        self.assertEqual(self.db.get(ExceptionCase, self.case.id).status, "ignored")
        self.assertEqual(
            list(self.db.scalars(select(ExceptionDiagnosis).where(ExceptionDiagnosis.job_id == claimed.id)).all()),
            [],
        )

    def test_provider_failure_after_scan_resolution_cancels_instead_of_retrying_or_blocking(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")

        def fail_after_resolution(*args, before_http_attempt=None, **kwargs):  # noqa: ANN002, ANN003, ARG001
            before_http_attempt(1)
            with self.SessionLocal() as concurrent_db:
                concurrent_case = concurrent_db.get(ExceptionCase, self.case.id)
                concurrent_case.status = "resolved"
                concurrent_db.commit()
            raise RuntimeError("provider failed after the case was resolved")

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=fail_after_resolution,
            ),
            patch("app.services.exception_task_service.settings.exception_job_max_attempts", 1),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")

        self.assertEqual(status, "cancelled")
        self.db.expire_all()
        self.assertEqual(self.db.get(ExceptionCase, self.case.id).status, "resolved")
        self.assertEqual(self.db.get(ExceptionDiagnosisJob, claimed.id).status, "cancelled")
        self.assertNotIn(
            "diagnosis_failed",
            {
                event.event_type
                for event in self.db.scalars(select(ExceptionEvent).where(ExceptionEvent.case_id == self.case.id)).all()
            },
        )

    def test_provider_failure_after_evidence_change_is_superseded_without_retry(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")

        def fail_after_evidence_change(*args, before_http_attempt=None, **kwargs):  # noqa: ANN002, ANN003, ARG001
            before_http_attempt(1)
            with self.SessionLocal() as concurrent_db:
                concurrent_case = concurrent_db.get(ExceptionCase, self.case.id)
                concurrent_case.evidence_version = "ev-2"
                concurrent_case.status = "open"
                concurrent_db.commit()
            raise RuntimeError("provider failed after evidence changed")

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=fail_after_evidence_change,
            ),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")

        self.assertEqual(status, "cancelled")
        self.db.expire_all()
        self.assertEqual(self.db.get(ExceptionCase, self.case.id).evidence_version, "ev-2")
        self.assertEqual(self.db.get(ExceptionDiagnosisJob, claimed.id).status, "cancelled")

    def test_stop_event_before_generation_hands_job_back_without_provider_call(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        stop_event = threading.Event()
        stop_event.set()

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch("app.services.exception_task_service.call_hermes_exception_diagnosis") as provider_call,
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(
                job_id=claimed.id,
                worker_id="worker-1",
                stop_event=stop_event,
            )

        self.assertEqual(status, "queued")
        provider_call.assert_not_called()
        self.db.expire_all()
        handed_off = self.db.get(ExceptionDiagnosisJob, claimed.id)
        self.assertEqual(handed_off.status, "queued")
        self.assertIsNone(handed_off.lease_owner)
        self.assertIsNone(handed_off.lease_expires_at)

    def test_stop_event_during_model_call_discards_result_and_releases_lease(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        stop_event = threading.Event()
        result = self._structured_result(summary="停止服务后的结果不得保存。")

        def stop_during_call(*args, before_http_attempt=None, cancel_event=None, **kwargs):  # noqa: ANN002, ANN003, ARG001
            self.assertIs(cancel_event, stop_event)
            before_http_attempt(1)
            cancel_event.set()
            return result

        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch(
                "app.services.exception_task_service.call_hermes_exception_diagnosis",
                side_effect=stop_during_call,
            ),
            patch("app.services.exception_task_service.settings.exception_center_enabled", True),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
        ):
            status = execute_diagnosis_job(
                job_id=claimed.id,
                worker_id="worker-1",
                stop_event=stop_event,
            )

        self.assertEqual(status, "queued")
        self.db.expire_all()
        handed_off = self.db.get(ExceptionDiagnosisJob, claimed.id)
        self.assertIsNone(handed_off.lease_owner)
        self.assertIsNone(handed_off.lease_expires_at)
        self.assertEqual(
            list(self.db.scalars(select(ExceptionDiagnosis).where(ExceptionDiagnosis.job_id == claimed.id)).all()),
            [],
        )

    def test_disabled_feature_gate_never_calls_model(self):
        claimed = claim_diagnosis_job(self.db, worker_id="worker-1")
        with (
            patch("app.services.exception_task_service.SessionLocal", self.SessionLocal),
            patch("app.services.exception_task_service.settings.exception_center_enabled", False),
            patch("app.services.exception_task_service.settings.exception_ai_enabled", True),
            patch("app.services.exception_task_service.call_hermes_exception_diagnosis") as model_call,
        ):
            status = execute_diagnosis_job(job_id=claimed.id, worker_id="worker-1")
        self.assertEqual(status, "queued")
        model_call.assert_not_called()
        self.db.expire_all()
        self.assertEqual(self.db.get(ExceptionCase, self.case.id).status, "blocked")

    def test_old_diagnosis_for_unchanged_evidence_is_not_scheduled_again(self):
        self.db.add(
            ExceptionDiagnosis(
                case_id=self.case.id,
                job_id=None,
                evidence_version="ev-1",
                root_cause_code="warehouse_missing",
                summary="Already diagnosed.",
                confidence=0.9,
                disposition="manual_review",
                evidence_refs_json=["snapshot:1"],
                impact_json={"summary": "Known impact"},
                recommended_steps_json=[],
                missing_evidence_json=[],
                model_name="old-model",
                request_id="old-request",
                diagnosed_at=datetime.now(timezone.utc) - timedelta(days=30),
            )
        )
        self.db.commit()
        jobs = enqueue_due_ai_diagnoses(self.db, limit=50)
        self.assertEqual(jobs, [])

    def test_master_completeness_cases_are_never_scheduled_for_per_case_ai(self):
        case = ExceptionCase(
            case_no="EXC-MASTER-COMPLETENESS",
            fingerprint="master-completeness",
            domain="master_data",
            rule_code="master_completeness.customer",
            title="Incomplete customer",
            severity="high",
            status="open",
            source_type="customer_master",
            evidence_version="master-ev-1",
            reason="Missing customer fields",
        )
        self.db.add(case)
        self.db.commit()

        jobs = enqueue_due_ai_diagnoses(self.db, limit=50)

        self.assertNotIn(case.id, {job.case_id for job in jobs})

    def test_disabled_scheduled_policy_leaves_scheduled_queue_unclaimed(self):
        self.job.trigger_type = "scheduled"
        self.policy.scheduled_ai_enabled = False
        self.db.commit()

        claimed = claim_diagnosis_job(self.db, worker_id="worker-disabled-scheduled")

        self.assertIsNone(claimed)
        self.db.refresh(self.job)
        self.assertEqual(self.job.status, "queued")

    def test_scheduled_diagnoses_use_explicit_severity_priority_before_limit(self):
        now = datetime.now(timezone.utc)
        candidates = []
        for index, severity in enumerate(("warning", "critical", "high"), start=1):
            case = ExceptionCase(
                case_no=f"EXC-PRIORITY-{index}",
                fingerprint=f"priority-fingerprint-{index}",
                domain="inventory",
                rule_code="inventory.negative_stock",
                title=f"{severity} candidate",
                severity=severity,
                status="open",
                source_type="inventory_snapshot",
                evidence_version=f"priority-ev-{index}",
                reason="Needs diagnosis",
                last_seen_at=now + timedelta(minutes=index),
            )
            self.db.add(case)
            candidates.append(case)
        self.db.commit()

        jobs = enqueue_due_ai_diagnoses(self.db, limit=2)

        scheduled_case_ids = [job.case_id for job in jobs]
        self.assertEqual(scheduled_case_ids, [candidates[1].id, candidates[2].id])

    def test_diagnosed_and_active_candidates_are_excluded_before_limit(self):
        now = datetime.now(timezone.utc)
        for index in range(20):
            diagnosed_case = ExceptionCase(
                case_no=f"EXC-DIAGNOSED-{index}",
                fingerprint=f"diagnosed-fingerprint-{index}",
                domain="inventory",
                rule_code="inventory.negative_stock",
                title="Already diagnosed critical candidate",
                severity="critical",
                status="open",
                source_type="inventory_snapshot",
                evidence_version=f"diagnosed-ev-{index}",
                reason="Already diagnosed",
                last_seen_at=now - timedelta(days=30, minutes=index),
            )
            self.db.add(diagnosed_case)
            self.db.flush()
            self.db.add(
                ExceptionDiagnosis(
                    case_id=diagnosed_case.id,
                    job_id=None,
                    evidence_version=diagnosed_case.evidence_version,
                    root_cause_code="warehouse_missing",
                    summary="Existing diagnosis.",
                    confidence=0.9,
                    disposition="manual_review",
                    evidence_refs_json=[],
                    impact_json={},
                    recommended_steps_json=[],
                    missing_evidence_json=[],
                    diagnosed_at=now - timedelta(days=1),
                )
            )
        active_case = ExceptionCase(
            case_no="EXC-ACTIVE-JOB",
            fingerprint="active-job-fingerprint",
            domain="inventory",
            rule_code="inventory.negative_stock",
            title="Active job candidate",
            severity="critical",
            status="open",
            source_type="inventory_snapshot",
            evidence_version="active-job-ev",
            reason="Already queued",
            last_seen_at=now - timedelta(days=60),
        )
        target_case = ExceptionCase(
            case_no="EXC-UNDIGNOSED-TARGET",
            fingerprint="undiagnosed-target-fingerprint",
            domain="inventory",
            rule_code="inventory.negative_stock",
            title="Undiagnosed target",
            severity="critical",
            status="open",
            source_type="inventory_snapshot",
            evidence_version="undiagnosed-target-ev",
            reason="Needs diagnosis",
            last_seen_at=now,
        )
        self.db.add_all([active_case, target_case])
        self.db.flush()
        self.db.add(
            ExceptionDiagnosisJob(
                job_no="EXJOB-ACTIVE-CANDIDATE",
                case_id=active_case.id,
                evidence_version=active_case.evidence_version,
                trigger_type="scheduled",
                status="queued",
                available_at=now,
            )
        )
        self.db.commit()

        jobs = enqueue_due_ai_diagnoses(self.db, limit=1)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].case_id, target_case.id)


if __name__ == "__main__":
    unittest.main()
