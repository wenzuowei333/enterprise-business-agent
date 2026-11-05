import unittest
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models import ExceptionDiagnosisJob
from app.schemas.exception_center import (
    ExceptionDiagnosisQualitySummary,
    ExceptionDiagnosisResponse,
    ExceptionOpsSummary,
    PolicyResponse,
    PolicyPatch,
    PolicyUpdate,
    VerifyRequest,
)


class ExceptionPhaseThreeContractTest(unittest.TestCase):
    def _legacy_policy_payload(self) -> dict:
        return {
            "is_enabled": True,
            "full_scan_cron": "30 2 * * *",
            "digest_cron": "30 8 * * *",
            "ai_daily_limit": 100,
            "ai_batch_limit": 50,
            "stale_diagnosis_hours": 24,
        }

    def test_legacy_policy_request_does_not_implicitly_enable_phase_three(self) -> None:
        policy = PolicyUpdate.model_validate(self._legacy_policy_payload())

        self.assertTrue(policy.is_enabled)
        self.assertFalse(policy.manual_ai_enabled)
        self.assertFalse(policy.scheduled_ai_enabled)
        self.assertFalse(policy.full_scan_enabled)
        self.assertFalse(policy.digest_enabled)
        self.assertEqual(policy.manual_ai_daily_limit, 20)
        self.assertEqual(policy.scheduled_ai_daily_limit, 0)
        self.assertEqual(policy.scheduled_ai_batch_limit, 20)
        self.assertEqual(policy.ai_concurrency, 1)

    def test_legacy_policy_response_has_safe_phase_three_defaults(self) -> None:
        now = datetime.now(timezone.utc)
        policy = PolicyResponse.model_validate(
            {
                "policy_key": "default",
                "is_enabled": True,
                "full_scan_cron": "30 2 * * *",
                "digest_cron": "30 8 * * *",
                "ai_daily_limit": 100,
                "ai_batch_limit": 50,
                "stale_diagnosis_hours": 24,
                "settings": {},
                "updated_at": now,
            }
        )

        self.assertFalse(policy.manual_ai_enabled)
        self.assertFalse(policy.scheduled_ai_enabled)
        self.assertFalse(policy.full_scan_enabled)
        self.assertFalse(policy.digest_enabled)
        self.assertEqual(policy.ai_concurrency, 1)

    def test_policy_patch_tracks_only_explicit_non_null_fields(self) -> None:
        now = datetime.now(timezone.utc)
        patch = PolicyPatch.model_validate(
            {"expected_updated_at": now.isoformat(), "manual_ai_enabled": True}
        )
        self.assertEqual(
            patch.model_dump(exclude_unset=True),
            {"expected_updated_at": now, "manual_ai_enabled": True},
        )
        with self.assertRaises(ValidationError):
            PolicyPatch.model_validate({})
        with self.assertRaises(ValidationError):
            PolicyPatch.model_validate({"expected_updated_at": now.isoformat()})
        with self.assertRaises(ValidationError):
            PolicyPatch.model_validate({"expected_updated_at": now.isoformat(), "settings": None})

    def test_active_diagnosis_unique_index_is_partial_on_postgresql(self) -> None:
        index = next(
            index
            for index in ExceptionDiagnosisJob.__table__.indexes
            if index.name == "uq_exception_diagnosis_job_active_case_evidence"
        )
        sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        self.assertIn("UNIQUE INDEX uq_exception_diagnosis_job_active_case_evidence", sql)
        self.assertIn("WHERE status IN ('queued','processing')", sql)

    def test_verify_request_normalizes_optional_observation_fields(self) -> None:
        request = VerifyRequest.model_validate(
            {
                "note": "  reran the source check  ",
                "expected_evidence_version": " evidence-v2 ",
                "expected_outcome": "resolved",
                "observed_result": "  no rows remain  ",
            }
        )

        self.assertEqual(request.note, "reran the source check")
        self.assertEqual(request.expected_evidence_version, "evidence-v2")
        self.assertEqual(request.observed_result, "no rows remain")

    def test_verify_request_requires_an_explicit_evidence_version(self) -> None:
        with self.assertRaises(ValidationError):
            VerifyRequest.model_validate({"note": "rerun"})

    def test_diagnosis_telemetry_rejects_negative_usage(self) -> None:
        for invalid_field in ("latency_ms", "evidence_bytes", "evidence_approx_tokens"):
            with self.subTest(field=invalid_field), self.assertRaises(ValidationError):
                payload = {
                    "id": 1,
                    "evidence_version": "ev-1",
                    "root_cause_code": "insufficient_evidence",
                    "summary": "Blocked",
                    "confidence": "0.5",
                    "disposition": "blocked",
                    "model_name": "test",
                    "diagnosed_at": datetime.now(timezone.utc),
                }
                payload[invalid_field] = -1
                ExceptionDiagnosisResponse.model_validate(payload)

    def test_ops_and_quality_contracts_allow_empty_initial_state(self) -> None:
        now = datetime.now(timezone.utc)
        ops = ExceptionOpsSummary.model_validate(
            {
                "generated_at": now,
                "heartbeats": [
                    {
                        "service_type": "ai_worker",
                        "instance_id": "worker-1",
                        "started_at": now,
                        "last_heartbeat_at": now,
                        "is_stale": False,
                    }
                ],
                "manual_budget": {"limit": 20, "used": 1, "remaining": 19},
                "scheduled_budget": {"limit": 0, "used": 0, "remaining": 0},
            }
        )
        quality = ExceptionDiagnosisQualitySummary.model_validate(
            {
                "generated_at": now,
                "total": 3,
                "by_domain": {"inventory": 3},
                "by_rule": {"inventory.negative_stock": 3},
                "by_root_cause_code": {},
                "by_contract_version": {},
            }
        )

        self.assertEqual(ops.diagnosis_completed_24h, 0)
        self.assertEqual(ops.last_scan_scanned, 0)
        self.assertFalse(ops.heartbeats[0].is_stale)
        self.assertEqual(quality.total_diagnoses, 3)
        self.assertEqual(quality.feedback_coverage_rate, None)
        self.assertEqual(quality.evidence_reference_valid_rate, None)
        self.assertEqual(quality.usage_reported_count, 0)
        self.assertEqual(quality.usage_missing_count, 0)
        self.assertIsNone(quality.usage_completeness_rate)

    def test_ops_circuit_is_nullable_and_rejects_legacy_untyped_fields(self) -> None:
        now = datetime.now(timezone.utc)
        empty = ExceptionOpsSummary.model_validate({"generated_at": now})
        self.assertIsNone(empty.circuit)

        typed = ExceptionOpsSummary.model_validate(
            {
                "generated_at": now,
                "circuit": {
                    "open": True,
                    "consecutive_failures": 5,
                    "retry_after_seconds": 60,
                    "stale": False,
                    "source": "ai_worker",
                },
            }
        )
        self.assertEqual(typed.circuit.source, "ai_worker")
        with self.assertRaises(ValidationError):
            ExceptionOpsSummary.model_validate(
                {
                    "generated_at": now,
                    "circuit": {
                        "open": False,
                        "consecutive_failures": 0,
                        "retry_after_seconds": 0,
                        "stale": False,
                        "source": "ai_worker",
                        "state": "closed",
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
