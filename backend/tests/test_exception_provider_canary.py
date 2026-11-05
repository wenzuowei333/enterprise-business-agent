import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.services.hermes_ai_service import (
    EXCEPTION_CONTRACT_VERSION,
    EXCEPTION_PROMPT_VERSION,
    ExceptionDiagnosis,
    HermesCallMetadata,
    HermesStructuredDiagnosis,
    reset_hermes_circuit,
)


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_exception_provider_canary.py"


def _load_module():
    module_name = "exception_provider_canary_test_module"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load provider canary")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _AuditSession:
    def __init__(self, rows, scalar_values=()):  # noqa: ANN001
        self.rows = rows
        self.commits = 0
        self.scalar_values = iter(scalar_values)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return False

    def add(self, row):  # noqa: ANN001
        self.rows.append(row)

    def commit(self):
        self.commits += 1

    def scalar(self, statement):  # noqa: ANN001, ARG002
        return next(self.scalar_values)


class _ProviderResponse:
    def __init__(self, payload):  # noqa: ANN001
        self.payload = json.dumps(payload).encode("utf-8")
        self.headers = {"x-request-id": "provider-canary-request-1"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return False

    def read(self, size=-1):  # noqa: ANN001
        return self.payload[:size] if size >= 0 else self.payload


class ExceptionProviderCanaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canary = _load_module()

    def _result(
        self,
        *,
        request_id: str,
        prompt_tokens: int | None = 11,
        completion_tokens: int | None = 7,
        total_tokens: int | None = 18,
    ) -> HermesStructuredDiagnosis:
        now = datetime.now(timezone.utc)
        return HermesStructuredDiagnosis(
            diagnosis=ExceptionDiagnosis(
                root_cause_code="warehouse_missing",
                summary="合成库存记录缺少仓库映射。",
                confidence=0.99,
                evidence_refs=["snapshot:CANARY-SNAPSHOT-001"],
                impact="当前无法安全选择库存修复方案。",
                recommended_steps=["补充仓库映射后重新执行库存核验。"],
                missing_evidence=[],
                disposition="actionable",
            ),
            metadata=HermesCallMetadata(
                provider_host="provider.example",
                model="canary-model",
                request_id=request_id,
                provider_request_id="provider-request-sensitive-header-value",
                started_at=now,
                completed_at=now,
                latency_ms=10,
                attempts=1,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                prompt_version=EXCEPTION_PROMPT_VERSION,
                contract_version=EXCEPTION_CONTRACT_VERSION,
                evidence_bytes=256,
                evidence_approx_tokens=64,
                evidence_truncated=False,
            ),
        )

    def test_success_audits_each_attempt_and_only_safe_contract_evidence(self) -> None:
        rows = []

        def session_factory():
            return _AuditSession(rows)

        def attempt_reserver(factory, *, canary_id, detail):  # noqa: ANN001
            self.canary._write_canary_audit(
                factory,
                action_type=self.canary.CANARY_ACTION_STARTED,
                canary_id=canary_id,
                detail=detail,
            )

        def diagnosis_call(evidence, **kwargs):  # noqa: ANN001
            self.assertEqual(evidence, self.canary.CANARY_EVIDENCE)
            self.assertTrue(kwargs["require_complete_usage"])
            self.assertEqual(kwargs["allowed_root_cause_codes"], ["warehouse_missing"])
            kwargs["before_http_attempt"](1)
            return self._result(request_id=kwargs["request_id"])

        with tempfile.TemporaryDirectory() as temporary_directory:
            revision = Path(temporary_directory) / "SOURCE_REVISION"
            revision.write_text("0123456789abcdef", encoding="utf-8")
            with (
                patch.object(settings, "hermes_api_base_url", "https://provider.example/v1"),
                patch.object(settings, "hermes_model", "canary-model"),
                patch.object(settings, "exception_ai_enabled", True),
            ):
                result = self.canary.execute_provider_canary(
                    session_factory=session_factory,
                    diagnosis_call=diagnosis_call,
                    source_revision_path=revision,
                    attempt_reserver=attempt_reserver,
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider_call_count"], 1)
        self.assertEqual(
            [row.action_type for row in rows],
            [self.canary.CANARY_ACTION_STARTED, self.canary.CANARY_ACTION_COMPLETED],
        )
        self.assertTrue(all(row.resource_type == self.canary.CANARY_RESOURCE_TYPE for row in rows))
        self.assertTrue(all(row.resource_id == result["canary_id"] for row in rows))
        completed = rows[-1].after_data
        self.assertEqual(completed["provider_call_count"], 1)
        self.assertTrue(completed["schema_valid"])
        self.assertTrue(completed["canonical_evidence_refs_valid"])
        self.assertTrue(completed["safety_guard_passed"])
        self.assertTrue(completed["usage_complete"])
        self.assertEqual(len(completed["provider_request_id_sha256"]), 64)
        serialized = json.dumps([row.after_data for row in rows])
        for forbidden in (
            "provider-request-sensitive-header-value",
            "hermes_api_key",
            "canary-snapshot-001",
            "the synthetic record has no warehouse mapping",
        ):
            self.assertNotIn(forbidden, serialized.casefold())

    def test_real_public_diagnosis_contract_is_used_end_to_end(self) -> None:
        rows = []

        def attempt_reserver(factory, *, canary_id, detail):  # noqa: ANN001
            self.canary._write_canary_audit(
                factory,
                action_type=self.canary.CANARY_ACTION_STARTED,
                canary_id=canary_id,
                detail=detail,
            )

        provider_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "root_cause_code": "warehouse_missing",
                                "summary": "合成库存记录缺少仓库映射。",
                                "confidence": 0.99,
                                "evidence_refs": ["snapshot:CANARY-SNAPSHOT-001"],
                                "impact": "当前无法安全选择仓库维度的修复方案。",
                                "recommended_steps": [
                                    "补充仓库映射后重新执行库存核验。"
                                ],
                                "missing_evidence": [],
                                "disposition": "actionable",
                            }
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            revision = Path(temporary_directory) / "SOURCE_REVISION"
            revision.write_text("0123456789abcdef", encoding="utf-8")
            reset_hermes_circuit()
            with (
                patch.object(settings, "hermes_api_base_url", "https://provider.example/v1"),
                patch.object(settings, "hermes_api_key", "synthetic-test-key-not-a-secret"),
                patch.object(settings, "hermes_model", "canary-model"),
                patch.object(settings, "exception_ai_enabled", True),
                patch.object(settings, "exception_ai_max_retries", 0),
                patch(
                    "app.services.hermes_ai_service.urlopen",
                    return_value=_ProviderResponse(provider_payload),
                ) as provider,
            ):
                result = self.canary.execute_provider_canary(
                    session_factory=lambda: _AuditSession(rows),
                    source_revision_path=revision,
                    attempt_reserver=attempt_reserver,
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["root_cause_code"], "warehouse_missing")
        self.assertEqual(result["total_tokens"], 30)
        provider.assert_called_once()
        self.assertEqual(
            [row.action_type for row in rows],
            [self.canary.CANARY_ACTION_STARTED, self.canary.CANARY_ACTION_COMPLETED],
        )

    def test_incomplete_usage_fails_nonzero_contract_and_writes_safe_terminal_audit(self) -> None:
        rows = []

        def attempt_reserver(factory, *, canary_id, detail):  # noqa: ANN001
            self.canary._write_canary_audit(
                factory,
                action_type=self.canary.CANARY_ACTION_STARTED,
                canary_id=canary_id,
                detail=detail,
            )

        def diagnosis_call(evidence, **kwargs):  # noqa: ANN001, ARG001
            kwargs["before_http_attempt"](1)
            return self._result(
                request_id=kwargs["request_id"],
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            revision = Path(temporary_directory) / "SOURCE_REVISION"
            revision.write_text("0123456789abcdef", encoding="utf-8")
            with (
                patch.object(settings, "hermes_api_base_url", "https://provider.example/v1"),
                patch.object(settings, "hermes_model", "canary-model"),
                patch.object(settings, "exception_ai_enabled", True),
                self.assertRaisesRegex(self.canary.ProviderCanaryError, "provider_usage_incomplete"),
            ):
                self.canary.execute_provider_canary(
                    session_factory=lambda: _AuditSession(rows),
                    diagnosis_call=diagnosis_call,
                    source_revision_path=revision,
                    attempt_reserver=attempt_reserver,
                )

        self.assertEqual(
            [row.action_type for row in rows],
            [self.canary.CANARY_ACTION_STARTED, self.canary.CANARY_ACTION_FAILED],
        )
        self.assertEqual(rows[-1].after_data["error_code"], "ProviderCanaryError")
        self.assertNotIn("provider_usage_incomplete", json.dumps(rows[-1].after_data))

    def test_provider_attempt_reservation_blocks_http_before_daily_limit_is_exceeded(self) -> None:
        blocked_rows = []
        blocked_session = _AuditSession(blocked_rows, scalar_values=(20, 19, 1))
        with self.assertRaisesRegex(self.canary.ProviderCanaryError, "provider_daily_limit_reached"):
            self.canary._reserve_canary_provider_attempt(
                lambda: blocked_session,
                canary_id="provider-canary-blocked",
                detail={"status": "started"},
            )
        self.assertEqual(blocked_rows, [])
        self.assertEqual(blocked_session.commits, 0)

        allowed_rows = []
        allowed_session = _AuditSession(allowed_rows, scalar_values=(20, 18, 1))
        self.canary._reserve_canary_provider_attempt(
            lambda: allowed_session,
            canary_id="provider-canary-allowed",
            detail={"status": "started"},
        )
        self.assertEqual(len(allowed_rows), 1)
        self.assertEqual(allowed_rows[0].action_type, self.canary.CANARY_ACTION_STARTED)
        self.assertEqual(allowed_session.commits, 1)

    def test_provider_attempt_reservation_accepts_unlimited_daily_policy(self) -> None:
        rows = []
        session = _AuditSession(rows, scalar_values=(0, 500, 200))

        self.canary._reserve_canary_provider_attempt(
            lambda: session,
            canary_id="provider-canary-unlimited",
            detail={"status": "started"},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].action_type, self.canary.CANARY_ACTION_STARTED)
        self.assertEqual(session.commits, 1)

    def test_cli_failure_output_suppresses_exception_content(self) -> None:
        output = io.StringIO()
        with (
            patch.object(
                self.canary,
                "execute_provider_canary",
                side_effect=RuntimeError("api_key=secret and provider prompt body"),
            ),
            redirect_stdout(output),
        ):
            status = self.canary.main()

        self.assertEqual(status, 1)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload, {"ok": False, "error_code": "RuntimeError"})
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("prompt", output.getvalue())


if __name__ == "__main__":
    unittest.main()
