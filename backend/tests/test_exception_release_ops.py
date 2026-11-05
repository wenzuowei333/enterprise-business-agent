import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
RUNTIME_PATH = ROOT / "scripts" / "verify_exception_stage3_runtime.py"
CANARY_PATH = ROOT / "scripts" / "run_exception_provider_canary.py"
BASELINE_PATH = DEPLOY / "exception-release-baseline.env"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _baseline_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _read(BASELINE_PATH).splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _load_runtime_module():
    module_name = "exception_stage3_runtime_ops_test"
    spec = importlib.util.spec_from_file_location(module_name, RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load exception stage-three runtime verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class ExceptionReleaseOpsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = _load_runtime_module()

    def test_release_baseline_uses_immutable_source_and_current_database_head(self) -> None:
        baseline = _baseline_values()
        self.assertEqual(
            baseline["EXCEPTION_RELEASE_SOURCE_SNAPSHOT"],
            "8bca0f394ad486bd1bbe8b2fcfc751d2e3b88605",
        )
        self.assertEqual(
            baseline["EXCEPTION_RUNTIME_ALEMBIC_REVISION"],
            "20260830_0200",
        )
        self.assertEqual(baseline["EXCEPTION_STAGE3_HISTORY_START"], "20260728_0400")
        self.assertEqual(baseline["EXCEPTION_STAGE3_HISTORY_TARGET"], "20260729_0500")

        source_revision = (ROOT / "SOURCE_REVISION").read_text(encoding="utf-8").strip()
        self.assertRegex(source_revision, r"^[0-9a-f]{40}$")
        self.assertEqual(source_revision, baseline["EXCEPTION_RELEASE_SOURCE_SNAPSHOT"])

        verifier = _read(DEPLOY / "verify-exception-stage3.sh")
        installer = _read(DEPLOY / "install-exception-services.sh")
        for source in (verifier, installer):
            self.assertIn("exception-release-baseline.env", source)
            self.assertIn("EXCEPTION_RELEASE_SOURCE_SNAPSHOT", source)
            self.assertIn("EXCEPTION_RUNTIME_ALEMBIC_REVISION", source)
            self.assertIn("SOURCE_REVISION", source)

    def test_observer_is_non_root_and_has_only_required_supplementary_groups(self) -> None:
        observer = _read(DEPLOY / "enterprise-business-agent-exception-observer.service")
        metrics = _read(DEPLOY / "enterprise-business-agent-exception-observer-metrics.service")

        self.assertIn("User=handmade-exception-observer", observer)
        self.assertIn("Group=handmade-exception-observer", observer)
        self.assertNotIn("User=root", observer)
        self.assertIn("SupplementaryGroups=handmade-exception-code", observer)
        self.assertNotIn("systemd-journal", observer)
        self.assertNotIn("EnvironmentFile=", observer)
        self.assertIn("Requires=enterprise-business-agent-exception-observer-metrics.service", observer)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", observer)
        self.assertIn("StateDirectory=enterprise-business-agent-exception-release", observer)
        self.assertIn("StateDirectoryMode=0750", observer)

        self.assertIn("User=root", metrics)
        self.assertIn("Group=handmade-exception-observer", metrics)
        self.assertIn(
            "SupplementaryGroups=systemd-journal handmade-exception-code",
            metrics,
        )
        self.assertIn("RuntimeDirectory=enterprise-business-agent-exception-observer-metrics", metrics)
        self.assertIn("RuntimeDirectoryMode=0750", metrics)
        self.assertIn("IPAddressDeny=any", metrics)
        self.assertIn("IPAddressAllow=localhost", metrics)
        self.assertIn(
            "EnvironmentFile=/etc/enterprise-business-agent/exception-observer-metrics.env",
            metrics,
        )

    def test_all_exception_services_isolate_sensitive_business_paths(self) -> None:
        units = (
            "enterprise-business-agent-exception-worker.service",
            "enterprise-business-agent-exception-ai-worker.service",
            "enterprise-business-agent-exception-scheduler.service",
            "enterprise-business-agent-exception-observer.service",
        )
        for unit_name in units:
            source = _read(DEPLOY / unit_name)
            with self.subTest(unit=unit_name):
                self.assertIn("InaccessiblePaths=/opt/enterprise-business-agent/.env", source)
                for directory in ("backups", "output", "outputs"):
                    self.assertIn(
                        f"InaccessiblePaths=-/opt/enterprise-business-agent/{directory}",
                        source,
                    )

    def test_backup_archive_has_size_metadata_exclusions_and_data_file_gate(self) -> None:
        backup = _read(DEPLOY / "create-exception-release-backup.sh")
        installer = _read(DEPLOY / "install-exception-services.sh")
        for source in (backup, installer):
            self.assertIn('MAX_CODE_ARCHIVE_BYTES="${MAX_CODE_ARCHIVE_BYTES:-268435456}"', source)
            self.assertNotIn("1073741824", source)
            self.assertIn('forbidden_suffixes = (".dump", ".sql", ".xlsx", ".xls", ".csv")', source)
            self.assertIn("Code archive contains a forbidden database or tabular-data file", source)
        for directory in ("backups", "output", "outputs"):
            self.assertIn(f'--exclude="${{app_name}}/{directory}"', backup)
        self.assertIn("BACKUP_FORMAT_VERSION=2", backup)
        self.assertIn("SOURCE_REVISION=${source_revision}", backup)
        self.assertIn("DATABASE_ALEMBIC_REVISION=${database_alembic_revision}", backup)
        self.assertIn("SOURCE_REVISION is required before a release backup can be trusted", backup)
        self.assertNotIn('source_revision="unknown"', backup)
        self.assertIn("CODE_ARCHIVE_BYTES=${code_archive_bytes}", backup)
        self.assertIn("CODE_ARCHIVE_LIMIT_BYTES=${MAX_CODE_ARCHIVE_BYTES}", backup)
        self.assertIn("DATABASE_DUMP_BYTES=${database_dump_bytes}", backup)
        self.assertIn("validate_code_archive_contents", installer)

    def test_backup_archive_validator_rejects_every_forbidden_data_type(self) -> None:
        backup = _read(DEPLOY / "create-exception-release-backup.sh")
        invocation = backup.index('"${PYTHON}" - "${partial_dir}/code.tar.gz"')
        block_start = backup.index("<<'PY'\n", invocation) + len("<<'PY'\n")
        validator = backup[block_start : backup.index("\nPY\n", block_start)]

        def write_archive(path: Path, member_name: str) -> None:
            content = b"release-test"
            with tarfile.open(path, mode="w:gz") as archive:
                member = tarfile.TarInfo(member_name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            allowed_archive = temporary_root / "allowed.tar.gz"
            write_archive(allowed_archive, "enterprise-business-agent/backend/app/main.py")
            allowed = subprocess.run(
                [sys.executable, "-c", validator, str(allowed_archive), "enterprise-business-agent"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

            for suffix in (".dump", ".sql", ".xlsx", ".xls", ".csv", ".csv.gz"):
                with self.subTest(suffix=suffix):
                    forbidden_archive = temporary_root / f"forbidden-{suffix.removeprefix('.').replace('.', '-')}.tar.gz"
                    write_archive(
                        forbidden_archive,
                        f"enterprise-business-agent/backend/fixtures/business-data{suffix}",
                    )
                    rejected = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            validator,
                            str(forbidden_archive),
                            "enterprise-business-agent",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn("forbidden database or tabular-data file", rejected.stderr)

    def test_observation_limits_cannot_be_weakened(self) -> None:
        self.runtime._validate_observation_limits(8.0, 900)
        for minimum_hours, maximum_gap in ((7.99, 900), (8.0, 901), (8.0, 59)):
            with self.subTest(minimum_hours=minimum_hours, maximum_gap=maximum_gap):
                with self.assertRaises(ValueError):
                    self.runtime._validate_observation_limits(minimum_hours, maximum_gap)

    def test_observation_requires_a_continuous_hong_kong_workday(self) -> None:
        hong_kong = ZoneInfo("Asia/Hong_Kong")
        workday = datetime(2026, 7, 27, 9, 0, tzinfo=hong_kong)
        samples = [workday + timedelta(minutes=5 * index) for index in range(97)]
        covered = self.runtime._covered_workday_window(
            samples,
            deployed_at=(workday - timedelta(minutes=5)).astimezone(timezone.utc),
            now=(workday + timedelta(hours=8, minutes=5)).astimezone(timezone.utc),
            maximum_gap_seconds=900,
        )
        self.assertEqual(covered, "2026-07-27")

        night_start = datetime(2026, 7, 27, 18, 0, tzinfo=hong_kong)
        night_samples = [night_start + timedelta(minutes=5 * index) for index in range(97)]
        self.assertIsNone(
            self.runtime._covered_workday_window(
                night_samples,
                deployed_at=(night_start - timedelta(minutes=5)).astimezone(timezone.utc),
                now=(night_start + timedelta(hours=8, minutes=5)).astimezone(timezone.utc),
                maximum_gap_seconds=900,
            )
        )

    def test_record_environment_check_does_not_require_web_jwt(self) -> None:
        settings = SimpleNamespace(
            environment="production",
            exception_center_enabled=True,
            exception_ai_enabled=False,
            exception_schedule_enabled=False,
            exception_actions_enabled=False,
            exception_ai_concurrency=1,
            exception_manual_ai_daily_limit=20,
            exception_manual_ai_require_provider_usage=True,
            exception_scheduled_ai_daily_limit=0,
            exception_evidence_max_bytes=32768,
            exception_evidence_max_tokens=8000,
            exception_ai_shutdown_timeout_seconds=150,
            jwt_secret="",
            hermes_api_base_url="",
            hermes_api_key="",
        )
        least_privilege_audit = self.runtime.ReleaseAudit()
        self.runtime._runtime_environment_checks(
            least_privilege_audit,
            settings,
            mode="dark",
            require_web_secret=False,
        )
        self.assertFalse(least_privilege_audit.failures)

        web_audit = self.runtime.ReleaseAudit()
        self.runtime._runtime_environment_checks(
            web_audit,
            settings,
            mode="dark",
            require_web_secret=True,
        )
        self.assertIn("secret.jwt", {failure.name for failure in web_audit.failures})

    def test_record_settings_import_avoids_unreadable_application_env(self) -> None:
        runtime_source = _read(RUNTIME_PATH)
        self.assertLess(
            runtime_source.index("runtime_cwd ="),
            runtime_source.index("from app.core.config import settings"),
        )
        self.assertIn("args.observation_file.parent", runtime_source)
        self.assertIn(
            "require_web_secret=not (args.record_observation or args.write_observation_metrics)",
            runtime_source,
        )
        consume_branch = runtime_source[
            runtime_source.index("if args.consume_observation_metrics:") :
            runtime_source.index("else:\n            from app.core.config import settings")
        ]
        self.assertNotIn("app.core.config", consume_branch)
        self.assertNotIn("app.core.database", consume_branch)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            application_root = temporary_root / "application"
            state_root = temporary_root / "state" / "observer"
            application_root.mkdir()
            state_root.mkdir(parents=True)
            environment_file = application_root / ".env"
            environment_file.write_bytes(b"\xff\xfe\x00not-utf8")
            environment_file.chmod(0)
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONPATH": str(ROOT / "backend"),
                    "ENVIRONMENT": "production",
                    "DATABASE_URL": "sqlite://",
                    "EXCEPTION_CENTER_ENABLED": "true",
                    "EXCEPTION_AI_ENABLED": "false",
                    "EXCEPTION_SCHEDULE_ENABLED": "false",
                    "EXCEPTION_ACTIONS_ENABLED": "false",
                    "EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS": "150",
                }
            )
            blocked = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from app.core.config import settings; print(settings.environment)",
                ],
                cwd=application_root,
                env=environment,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertNotEqual(
                blocked.returncode,
                0,
                "poisoned/unreadable application .env fixture must fail if probed",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from app.core.config import settings; assert settings.environment == 'production'",
                ],
                cwd=state_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_release_identity_changes_only_with_deployed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable = root / "backend" / "app" / "worker.py"
            executable.parent.mkdir(parents=True)
            executable.write_text("VALUE = 1\n", encoding="utf-8")
            docs = root / "docs" / "notes.md"
            docs.parent.mkdir(parents=True)
            docs.write_text("first\n", encoding="utf-8")

            first = self.runtime._compute_release_identity(root)
            docs.write_text("second\n", encoding="utf-8")
            self.assertEqual(first, self.runtime._compute_release_identity(root))
            executable.write_text("VALUE = 2\n", encoding="utf-8")
            self.assertNotEqual(first, self.runtime._compute_release_identity(root))

    def test_observation_baseline_binds_release_identity_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "observation.json"
            audit = self.runtime.ReleaseAudit()
            self.runtime._initialize_observation(
                audit,
                path,
                deployed_at=datetime.now(timezone.utc) - timedelta(hours=9),
                snapshot={"ai_calls_total": 0, "diagnosis_jobs_total": 0},
                release_identity="a" * 64,
                expected_revision="20260729_0500",
            )
            payload = __import__("json").loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["release_identity"], "a" * 64)
            self.assertEqual(payload["expected_revision"], "20260729_0500")

            verification = self.runtime.ReleaseAudit()
            self.runtime._verify_observation(
                verification,
                path,
                minimum_hours=8,
                maximum_gap_seconds=900,
                latest_sample_max_age_seconds=60,
                release_identity="b" * 64,
                expected_revision="wrong-revision",
            )
            failed_names = {failure.name for failure in verification.failures}
            self.assertIn("observation.release_identity", failed_names)
            self.assertIn("observation.expected_revision", failed_names)

    def test_manual_ready_rejects_a_final_sample_older_than_sixty_seconds(self) -> None:
        hong_kong = ZoneInfo("Asia/Hong_Kong")
        fixed_now = datetime(2026, 7, 29, 18, 0, tzinfo=hong_kong).astimezone(timezone.utc)
        deployed_at = datetime(2026, 7, 29, 8, 55, tzinfo=hong_kong).astimezone(timezone.utc)
        latest_sample = fixed_now - timedelta(seconds=61)
        sample_times: list[datetime] = []
        current = deployed_at + timedelta(minutes=5)
        while current <= latest_sample:
            sample_times.append(current)
            current += timedelta(minutes=5)
        sample_times.append(latest_sample)
        clean_sample = {
            "web_healthy": True,
            "database_healthy": True,
            "http_5xx_count": 0,
            "ai_calls_since_deploy": 0,
            "diagnosis_jobs_since_deploy": 0,
            "active_diagnosis_jobs": 0,
            "expired_diagnosis_leases": 0,
            "expired_background_leases": 0,
            "duplicate_active_diagnoses": 0,
            "heartbeat_ages": {},
            "audit_ok": True,
        }

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[no-untyped-def]
                return fixed_now if tz is None else fixed_now.astimezone(tz)

        with tempfile.TemporaryDirectory() as temporary_directory:
            observation_path = Path(temporary_directory) / "observation.json"
            observation_path.write_text(
                json.dumps(
                    {
                        "schema_version": self.runtime.OBSERVATION_SCHEMA_VERSION,
                        "deployed_at": deployed_at.isoformat(),
                        "release_identity": "a" * 64,
                        "expected_revision": "20260729_0500",
                        "baseline": {"ai_calls_total": 0, "diagnosis_jobs_total": 0},
                        "samples": [
                            {**clean_sample, "sampled_at": sampled_at.isoformat()}
                            for sampled_at in sample_times
                        ],
                    }
                ),
                encoding="utf-8",
            )
            audit = self.runtime.ReleaseAudit()
            with patch.object(self.runtime, "datetime", FrozenDateTime):
                self.runtime._verify_observation(
                    audit,
                    observation_path,
                    minimum_hours=8,
                    maximum_gap_seconds=900,
                    latest_sample_max_age_seconds=60,
                    release_identity="a" * 64,
                    expected_revision="20260729_0500",
                )

        failure_names = {failure.name for failure in audit.failures}
        self.assertEqual(failure_names, {"observation.continuous_samples"})

    def test_manual_ready_rechecks_cumulative_database_activity(self) -> None:
        engine = create_engine("sqlite://")
        dark_since = datetime.now(timezone.utc) - timedelta(hours=9)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('20260729_0500')")
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE exception_policy (
                        policy_key TEXT NOT NULL,
                        is_enabled INTEGER NOT NULL,
                        manual_ai_enabled INTEGER NOT NULL,
                        scheduled_ai_enabled INTEGER NOT NULL,
                        full_scan_enabled INTEGER NOT NULL,
                        digest_enabled INTEGER NOT NULL,
                        manual_ai_daily_limit INTEGER NOT NULL,
                        scheduled_ai_daily_limit INTEGER NOT NULL,
                        scheduled_ai_batch_limit INTEGER NOT NULL,
                        ai_concurrency INTEGER NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action_type TEXT NOT NULL,
                        resource_type TEXT NOT NULL,
                        resource_id TEXT,
                        before_data JSON,
                        after_data JSON,
                        created_at TIMESTAMP NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO exception_policy VALUES
                    ('default', 1, 0, 0, 0, 0, 20, 0, 20, 1)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE exception_event (
                        event_type TEXT NOT NULL, created_at TIMESTAMP NOT NULL, detail_json JSON
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE exception_diagnosis_job (
                        status TEXT NOT NULL, lease_expires_at TIMESTAMP,
                        case_id INTEGER, evidence_version INTEGER,
                        trigger_type TEXT NOT NULL, created_at TIMESTAMP NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE exception_background_job (
                        status TEXT NOT NULL, lease_expires_at TIMESTAMP,
                        job_type TEXT NOT NULL, created_at TIMESTAMP NOT NULL
                    )
                    """
                )
            )
            activity_time = datetime.now(timezone.utc) - timedelta(minutes=5)
            connection.execute(
                text(
                    """
                    INSERT INTO exception_event (event_type, created_at, detail_json)
                    VALUES ('diagnosis_ai_call_started', :created_at, NULL)
                    """
                ),
                {"created_at": activity_time},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO audit_log
                        (action_type, resource_type, resource_id, after_data, created_at)
                    VALUES
                        ('exception_provider_call_started', 'exception_provider_canary',
                         'provider-canary-after-dark', '{}', :created_at)
                    """
                ),
                {"created_at": activity_time},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO exception_diagnosis_job
                        (status, lease_expires_at, case_id, evidence_version, trigger_type, created_at)
                    VALUES ('completed', NULL, 1, 1, 'manual', :created_at)
                    """
                ),
                {"created_at": activity_time},
            )

        audit = self.runtime.ReleaseAudit()
        snapshot = self.runtime._database_checks(
            audit,
            engine,
            mode="manual-ready",
            expected_revision="20260729_0500",
            heartbeat_max_age=120,
            skip_heartbeats=True,
            preflight=True,
            dark_since=dark_since,
            transition_since=None,
        )
        failure_names = {failure.name for failure in audit.failures}
        self.assertIn("dark.ai_calls_since_start", failure_names)
        self.assertIn("dark.diagnosis_jobs_since_start", failure_names)
        self.assertEqual(snapshot["ai_calls_since_deploy"], 2)
        self.assertEqual(snapshot["diagnosis_jobs_since_deploy"], 1)
        self.assertEqual(snapshot["provider_calls_today"], 2)
        self.assertEqual(snapshot["provider_canary_calls_today"], 1)
        self.assertEqual(snapshot["provider_budget_remaining"], 18)

        with engine.begin() as connection:
            for _ in range(19):
                connection.execute(
                    text(
                        """
                        INSERT INTO exception_event (event_type, created_at, detail_json)
                        VALUES ('diagnosis_ai_call_started', :created_at, :detail_json)
                        """
                    ),
                    {
                        "created_at": activity_time,
                        "detail_json": json.dumps({"trigger_type": "manual"}),
                    },
                )
        over_limit = self.runtime.ReleaseAudit()
        over_limit_snapshot = self.runtime._database_checks(
            over_limit,
            engine,
            mode="manual-ready",
            expected_revision="20260729_0500",
            heartbeat_max_age=120,
            skip_heartbeats=True,
            preflight=True,
            dark_since=dark_since,
            transition_since=None,
        )
        over_limit_failures = {item.name for item in over_limit.failures}
        self.assertIn("budget.provider_daily_limit", over_limit_failures)
        self.assertIn("budget.manual_remaining", over_limit_failures)
        self.assertEqual(over_limit_snapshot["provider_calls_today"], 21)
        self.assertEqual(over_limit_snapshot["provider_budget_remaining"], 0)

    def test_future_or_late_operator_transition_marker_fails(self) -> None:
        now = datetime.now(timezone.utc)
        activation = now - timedelta(minutes=2)
        audit = self.runtime.ReleaseAudit()
        baseline = self.runtime._validate_manual_transition(
            audit,
            activation_at=activation,
            operator_marker=now + timedelta(minutes=1),
            now=now,
        )
        self.assertEqual(baseline, activation)
        self.assertIn("manual.operator_marker_not_future", {item.name for item in audit.failures})
        self.assertIn("manual.operator_marker_precedes_activation", {item.name for item in audit.failures})

        valid_audit = self.runtime.ReleaseAudit()
        valid_baseline = self.runtime._validate_manual_transition(
            valid_audit,
            activation_at=activation,
            operator_marker=activation - timedelta(seconds=5),
            now=now,
        )
        self.assertEqual(valid_baseline, activation)
        self.assertFalse(valid_audit.failures)

    def test_migration_rehearsal_restores_real_dump_and_cycles_exact_revisions(self) -> None:
        script = _read(DEPLOY / "rehearse-exception-stage3-migration.sh")
        self.assertIn('POSTGRES_HOST="127.0.0.1"', script)
        self.assertIn('START_REVISION="20260728_0400"', script)
        self.assertIn('TARGET_REVISION="20260729_0500"', script)
        self.assertIn("pg_restore", script)
        self.assertIn("--no-owner", script)
        self.assertIn("--no-acl", script)
        self.assertIn('run_alembic upgrade "${TARGET_REVISION}"', script)
        self.assertIn('run_alembic downgrade "${START_REVISION}"', script)
        self.assertEqual(script.count('run_alembic upgrade "${TARGET_REVISION}"'), 2)
        self.assertIn("trap cleanup EXIT", script)
        self.assertIn('DROP DATABASE IF EXISTS "${database_name}"', script)
        self.assertIn('DROP ROLE IF EXISTS "${role_name}"', script)
        self.assertIn("case_fingerprint", script)
        self.assertIn("notification_fingerprint", script)
        self.assertIn("diagnosis_fingerprint", script)
        self.assertIn("diagnosis_job_legacy_fingerprint", script)
        self.assertIn("background_job_fingerprint", script)
        self.assertIn("event_fingerprint", script)
        self.assertIn('EXPECTED_TARGET_SOURCE_REVISION="${EXPECTED_TARGET_SOURCE_REVISION:-}"', script)
        self.assertIn('EXPECTED_BACKUP_APP_ROOT="${EXPECTED_BACKUP_APP_ROOT:-}"', script)
        self.assertIn('REHEARSAL_PYTHON="${REHEARSAL_PYTHON:-}"', script)
        self.assertIn('SOURCE_REVISION_FILE="${APP_ROOT}/SOURCE_REVISION"', script)
        self.assertIn('validate_candidate_root "${APP_ROOT}"', script)
        self.assertIn('[[ -e "${candidate_root}/.venv" || -L "${candidate_root}/.venv" ]]', script)
        self.assertIn('"${PYTHON}" != "${EXPECTED_BACKUP_APP_ROOT}/.venv/bin/python"', script)
        self.assertIn('"${backup_app_root}" != "${EXPECTED_BACKUP_APP_ROOT}"', script)
        self.assertNotIn('"${backup_app_root}" != "${APP_ROOT}"', script)
        self.assertIn("policy_legacy_fingerprint", script)
        self.assertIn("0400 occurrence, feedback, and archive columns retained", script)
        self.assertIn("migration_20260729_0500_policy", script)
        self.assertIn("typed source-batch backfill", script)
        self.assertIn("uq_exception_diagnosis_job_active_case_evidence", script)
        self.assertIn("policy migration snapshots cleaned", script)
        self.assertIn("Evidence case=${baseline_case}", script)
        self.assertNotIn("echo ${role_password}", script)
        self.assertNotIn("echo ${database_url}", script)

    def test_migration_rehearsal_rejects_candidate_virtualenv_entries(self) -> None:
        script = _read(DEPLOY / "rehearse-exception-stage3-migration.sh")
        function_start = script.index("validate_candidate_root()")
        function_end = script.index("\n}\n", function_start) + len("\n}\n")
        validator = script[function_start:function_end]
        harness = f"""set -euo pipefail
{validator}
temporary_root="$(mktemp -d)"
cleanup() {{
  if [[ "${{temporary_root}}" == /tmp/* ]]; then
    rm -rf -- "${{temporary_root}}"
  fi
}}
trap cleanup EXIT
candidate_root="${{temporary_root}}/candidate"
mkdir "${{candidate_root}}"
case "${{1}}" in
  clean) ;;
  directory) mkdir "${{candidate_root}}/.venv" ;;
  symlink) ln -s /opt/enterprise-business-agent/.venv "${{candidate_root}}/.venv" ;;
  *) exit 99 ;;
esac
validate_candidate_root "${{candidate_root}}"
"""

        command_prefix = ["wsl.exe", "--exec", "bash"] if os.name == "nt" else ["bash"]
        for fixture, expected_returncode in (("clean", 0), ("directory", 1), ("symlink", 1)):
            with self.subTest(fixture=fixture):
                result = subprocess.run(
                    [*command_prefix, "-c", harness, "candidate-venv-test", fixture],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, expected_returncode, result.stderr)
                if expected_returncode:
                    self.assertIn("must not contain a .venv entry or symbolic link", result.stderr)

    def test_release_sync_preserves_runtime_artifacts_and_deletes_only_stale_code(self) -> None:
        sync_script = DEPLOY / "sync-exception-stage3-release.sh"
        source = _read(sync_script)
        required_exclusions = (
            "--exclude=/.env",
            "--exclude=/.venv/",
            "--exclude=/runtime/",
            "--exclude=/uploads/",
            "--exclude=/attachments/",
            "--exclude=/reports/",
            "--exclude=/backups/",
            "--exclude=/output/",
            "--exclude=/outputs/",
            "--exclude=/android/signing.properties",
            "--exclude=/android/local.properties",
            "--exclude=/android/*.jks",
            "--exclude=/android/*.keystore",
            "--exclude=/backend/app/static/downloads/",
        )
        for exclusion in required_exclusions:
            with self.subTest(exclusion=exclusion):
                self.assertIn(f'"{exclusion}"', source)
        self.assertNotIn("--delete-excluded", source)
        self.assertIn("--checksum", source)
        self.assertIn("--no-times", source)
        self.assertIn('EXPECTED_SYNC_PLAN_SHA256="${EXPECTED_SYNC_PLAN_SHA256:-}"', source)
        self.assertIn("Candidate root must not contain Python bytecode or __pycache__ entries.", source)

        rehearsal = _read(DEPLOY / "rehearse-exception-stage3-migration.sh")
        self.assertIn("export PYTHONDONTWRITEBYTECODE=1", rehearsal)

        rollout = _read(ROOT / "docs" / "exception-center-stage3-rollout.md")
        self.assertIn("sync-exception-stage3-release.sh", rollout)
        self.assertIn(
            'SYNC_PLAN_PATH="$(sudo mktemp /tmp/enterprise-business-agent-sync-plan.XXXXXX)"',
            rollout,
        )
        self.assertNotIn("sudo rsync -a --delete", rollout)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            candidate = temporary_root / "candidate"
            target = temporary_root / "target"
            candidate.mkdir()
            target.mkdir()
            target.chmod(0o710)

            (candidate / "SOURCE_REVISION").write_text("release-sha\n", encoding="utf-8")
            (candidate / "fresh-code.txt").write_text("candidate\n", encoding="utf-8")
            (candidate / "backend" / "app" / "static" / "downloads").mkdir(parents=True)
            (candidate / "backend" / "app" / "static" / "downloads" / ".gitkeep").write_text(
                "", encoding="utf-8"
            )

            signing = target / "android" / "signing.properties"
            signing.parent.mkdir(parents=True)
            signing.write_text("storePassword=production-secret\n", encoding="utf-8")
            apk = target / "backend" / "app" / "static" / "downloads" / "demo-management.apk"
            apk.parent.mkdir(parents=True)
            apk.write_bytes(b"production-apk")
            versioned_apk = apk.with_name("demo-management-1.6.3.apk")
            versioned_apk.write_bytes(b"versioned-production-apk")
            stale = target / "ordinary-stale.txt"
            stale.write_text("remove me\n", encoding="utf-8")

            if os.name == "nt":
                def wsl_path(path: Path) -> str:
                    result = subprocess.run(
                        ["wsl.exe", "--exec", "wslpath", "-a", str(path)],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    return result.stdout.strip()

                command_prefix = ["wsl.exe", "--exec", "env"]
                script_arg = wsl_path(sync_script)
                candidate_arg = wsl_path(candidate)
                target_arg = wsl_path(target)
            else:
                command_prefix = ["env"]
                script_arg = str(sync_script)
                candidate_arg = str(candidate)
                target_arg = str(target)

            def run_sync(mode: str, plan_sha256: str | None = None) -> subprocess.CompletedProcess[bytes]:
                environment_args = ["EXPECTED_TARGET_SOURCE_REVISION=release-sha"]
                if plan_sha256 is not None:
                    environment_args.append(f"EXPECTED_SYNC_PLAN_SHA256={plan_sha256}")
                return subprocess.run(
                    [
                        *command_prefix,
                        *environment_args,
                        "bash",
                        script_arg,
                        mode,
                        candidate_arg,
                        target_arg,
                    ],
                    capture_output=True,
                    timeout=30,
                    check=False,
                )

            dry_run = run_sync("dry-run")
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr.decode(errors="replace"))
            dry_plan = dry_run.stdout.decode("utf-8", errors="replace")
            self.assertIn("ordinary-stale.txt", dry_plan)
            self.assertIn("*deleting", dry_plan)
            self.assertNotIn("signing.properties", dry_plan)
            self.assertNotIn("demo-management.apk", dry_plan)
            self.assertNotIn("demo-management-1.6.3.apk", dry_plan)
            self.assertTrue(stale.exists())

            plan_sha256 = hashlib.sha256(dry_run.stdout).hexdigest()
            rejected = run_sync("apply", "0" * 64)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(
                "does not match the reviewed dry-run plan",
                rejected.stderr.decode("utf-8", errors="replace"),
            )
            self.assertTrue(stale.exists())
            self.assertEqual(signing.read_text(encoding="utf-8"), "storePassword=production-secret\n")
            self.assertEqual(apk.read_bytes(), b"production-apk")

            applied = run_sync("apply", plan_sha256)
            self.assertEqual(applied.returncode, 0, applied.stderr.decode(errors="replace"))
            self.assertFalse(stale.exists())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o710)
            self.assertEqual(signing.read_text(encoding="utf-8"), "storePassword=production-secret\n")
            self.assertEqual(apk.read_bytes(), b"production-apk")
            self.assertEqual(versioned_apk.read_bytes(), b"versioned-production-apk")
            self.assertEqual((target / "fresh-code.txt").read_text(encoding="utf-8"), "candidate\n")
            self.assertEqual((target / "SOURCE_REVISION").read_text(encoding="utf-8"), "release-sha\n")

            dirty_candidate = temporary_root / "dirty-candidate"
            dirty_candidate.mkdir()
            (dirty_candidate / "SOURCE_REVISION").write_text("release-sha\n", encoding="utf-8")
            cache_entry = dirty_candidate / "backend" / "__pycache__" / "module.cpython-312.pyc"
            cache_entry.parent.mkdir(parents=True)
            cache_entry.write_bytes(b"compiled-bytecode")
            dirty_candidate_arg = wsl_path(dirty_candidate) if os.name == "nt" else str(dirty_candidate)
            dirty = subprocess.run(
                [
                    *command_prefix,
                    "EXPECTED_TARGET_SOURCE_REVISION=release-sha",
                    "bash",
                    script_arg,
                    "dry-run",
                    dirty_candidate_arg,
                    target_arg,
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertNotEqual(dirty.returncode, 0)
            self.assertIn(
                "must not contain Python bytecode or __pycache__ entries",
                dirty.stderr.decode("utf-8", errors="replace"),
            )

            nested_target = candidate / "nested-target"
            nested_target.mkdir()
            nested_target_arg = wsl_path(nested_target) if os.name == "nt" else str(nested_target)
            nested = subprocess.run(
                [
                    *command_prefix,
                    "EXPECTED_TARGET_SOURCE_REVISION=release-sha",
                    "bash",
                    script_arg,
                    "dry-run",
                    candidate_arg,
                    nested_target_arg,
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertNotEqual(nested.returncode, 0)
            self.assertIn(
                "must not contain one another",
                nested.stderr.decode("utf-8", errors="replace"),
            )

    def test_release_backup_identity_is_checked_by_every_consumer(self) -> None:
        consumers = (
            DEPLOY / "install-exception-services.sh",
            DEPLOY / "rehearse-exception-stage3-migration.sh",
            DEPLOY / "apply-exception-stage3-migration.sh",
        )
        for path in consumers:
            source = _read(path)
            with self.subTest(script=path.name):
                self.assertIn("EXPECTED_PREVIOUS_SOURCE_REVISION", source)
                self.assertIn("EXPECTED_PREVIOUS_ALEMBIC_REVISION", source)
                self.assertIn("EXPECTED_RELEASE_BACKUP_MANIFEST_SHA256", source)
                self.assertIn("DATABASE_ALEMBIC_REVISION", source)
                self.assertIn('sha256sum --check --quiet SHA256SUMS', source)
                self.assertIn('sha256sum "${', source)
                self.assertIn("database/alembic-revision.txt", source)

    def test_production_migration_stops_loaded_workers_and_requires_quiescence(self) -> None:
        script = _read(DEPLOY / "apply-exception-stage3-migration.sh")
        self.assertIn(
            'EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION:-}"',
            script,
        )
        self.assertIn(
            '[[ "${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" != "${START_REVISION}" ]]',
            script,
        )
        self.assertIn(
            '[[ "${backup_database_revision}" != "${EXPECTED_PREVIOUS_ALEMBIC_REVISION}" ]]',
            script,
        )
        self.assertIn(
            '[[ "${backup_revision_file_value}" != "${backup_database_revision}" ]]',
            script,
        )
        for service in (
            "enterprise-business-agent-exception-worker.service",
            "enterprise-business-agent-exception-ai-worker.service",
            "enterprise-business-agent-exception-scheduler.service",
        ):
            self.assertIn(service, script)
        self.assertIn('if systemctl cat "${service}" >/dev/null 2>&1; then', script)
        self.assertIn('loaded_services+=("${service}")', script)
        self.assertIn('systemctl stop "${loaded_services[@]}"', script)
        self.assertIn('if [[ "${previous_loaded[${service}]}" != "true" ]]; then', script)
        self.assertIn('if [[ "${previous_active[${service}]}" == "true" ]]; then', script)
        self.assertIn("trap restore_services EXIT", script)
        self.assertIn(
            'SELECT count(*) FROM exception_diagnosis_job WHERE status = \'processing\'',
            script,
        )
        self.assertIn(
            'SELECT count(*) FROM exception_background_job WHERE status = \'processing\'',
            script,
        )
        quiescence = script.index("if diagnosis_processing or background_processing:")
        migration = script.index('upgrade "${TARGET_REVISION}"')
        self.assertLess(quiescence, migration)

    def test_observer_scalar_contract_binds_identity_and_hides_privileged_inputs(self) -> None:
        observer_unit = _read(DEPLOY / "enterprise-business-agent-exception-observer.service")
        observer_script = _read(DEPLOY / "record-exception-stage3-observation.sh")
        metrics_unit = _read(DEPLOY / "enterprise-business-agent-exception-observer-metrics.service")
        metrics_script = _read(DEPLOY / "collect-exception-stage3-observation-metrics.sh")
        runtime = _read(RUNTIME_PATH)

        self.assertNotIn("DATABASE_URL", observer_unit + observer_script)
        self.assertIn(
            "SupplementaryGroups=systemd-journal handmade-exception-code",
            metrics_unit,
        )
        self.assertIn(
            'SupplementaryGroups=systemd-journal ${CODE_GROUP}',
            _read(DEPLOY / "install-exception-services.sh"),
        )
        self.assertNotIn("journalctl", observer_unit + observer_script)
        self.assertNotIn("EnvironmentFile=", observer_unit)
        self.assertIn("--consume-observation-metrics", observer_script)
        self.assertIn("journalctl --unit enterprise-business-agent.service", metrics_script)
        self.assertIn("--write-observation-metrics", metrics_script)
        self.assertIn('chown root:"${OBSERVER_GROUP}" "${METRICS_FILE}"', metrics_script)
        self.assertIn('chmod 0640 "${METRICS_FILE}"', metrics_script)
        self.assertIn("RuntimeDirectoryMode=0750", metrics_unit)
        self.assertIn("metrics_stat.st_uid == 0", runtime)
        self.assertIn("metrics_stat.st_gid == os.getgid()", runtime)
        self.assertIn("stat.S_IMODE(metrics_stat.st_mode) == 0o640", runtime)
        self.assertIn(
            'metrics.get("release_identity") == observation.get("release_identity") == release_identity',
            runtime,
        )
        self.assertIn(
            'metrics.get("expected_revision") == observation.get("expected_revision") == expected_revision',
            runtime,
        )
        self.assertIn(
            'metrics.get("deployed_at") == observation.get("deployed_at")',
            runtime,
        )

    def test_observer_runtime_revision_is_bound_to_the_current_baseline(self) -> None:
        runtime = _read(RUNTIME_PATH)
        self.assertIn('parser.add_argument("--expected-revision", required=True)', runtime)

        with patch.object(sys, "argv", [str(RUNTIME_PATH)]):
            with self.assertRaises(SystemExit):
                self.runtime.parse_args()
        with patch.object(
            sys,
            "argv",
            [str(RUNTIME_PATH), "--expected-revision", "20260801_0100"],
        ):
            self.assertEqual(
                self.runtime.parse_args().expected_revision,
                "20260801_0100",
            )

        scripts = (
            DEPLOY / "collect-exception-stage3-observation-metrics.sh",
            DEPLOY / "record-exception-stage3-observation.sh",
        )
        for path in scripts:
            source = _read(path)
            with self.subTest(script=path.name):
                self.assertIn('get("expected_revision")', source)
                self.assertIn('--expected-revision "${expected_revision}"', source)
                self.assertNotIn("20260729_0500", source)

    def test_observer_timer_has_a_recurring_calendar_trigger_and_a_release_gate(self) -> None:
        timer = _read(DEPLOY / "enterprise-business-agent-exception-observer.timer")
        verifier = _read(DEPLOY / "verify-exception-stage3.sh")

        self.assertIn("OnCalendar=*-*-* *:00/5:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertNotIn("OnUnitActiveSec", timer)
        self.assertIn("--property=SubState", verifier)
        self.assertIn("--property=NextElapseUSecRealtime", verifier)
        self.assertIn("--property=NextElapseUSecMonotonic", verifier)
        self.assertIn('"${observer_timer_substate}" == "waiting"', verifier)
        self.assertIn("has a finite next trigger", verifier)

    def test_manual_ready_forces_a_fresh_dark_sample_before_live_preflight(self) -> None:
        installer = _read(DEPLOY / "install-exception-services.sh")
        manual_block_start = installer.index('if [[ "${MODE}" == "manual-ready" ]]; then')
        final_sample = installer.index('systemctl start "${OBSERVER_SERVICE}"', manual_block_start)
        result_check = installer.index("The mandatory final dark-observation sample failed", final_sample)
        preflight = installer.index('"${PYTHON}" "${AUDIT}" "${preflight_args[@]}"', result_check)
        mutation = installer.index("mutation_started=true", preflight)
        self.assertLess(final_sample, result_check)
        self.assertLess(result_check, preflight)
        self.assertLess(preflight, mutation)
        preflight_block = installer[result_check:preflight]
        self.assertIn("--observation-latest-max-age-seconds 60", preflight_block)
        self.assertIn('--dark-since "${observation_deployed_at}"', preflight_block)

    def test_installer_rollback_restores_observation_and_only_created_identities(self) -> None:
        installer = _read(DEPLOY / "install-exception-services.sh")
        identity_function = installer[
            installer.index("ensure_system_identity()") : installer.index("read_backup_metadata_value()")
        ]
        rollback = installer[
            installer.index("rollback_release()") : installer.index("release_exit_handler()")
        ]
        snapshot = installer[
            installer.index("previous_observation_root_exists=false") :
            installer.index("mutation_started=true")
        ]

        self.assertIn('if ! getent passwd "${user_name}"', identity_function)
        self.assertIn('created_service_users+=("${user_name}")', identity_function)
        self.assertIn('cp --archive "${OBSERVATION_FILE}"', snapshot)
        self.assertIn('previous_observation_uid="$(stat -c \'%u\'', snapshot)
        self.assertIn('previous_observation_gid="$(stat -c \'%g\'', snapshot)
        self.assertIn('previous_observation_mode="$(stat -c \'%a\'', snapshot)
        self.assertIn('cp --archive --force', rollback)
        self.assertIn('"${backup_dir}/observation/dark-observation.json" "${OBSERVATION_FILE}"', rollback)
        self.assertIn('chown "${previous_observation_uid}:${previous_observation_gid}"', rollback)
        self.assertIn('chmod "${previous_observation_mode}" "${OBSERVATION_ROOT}"', rollback)
        self.assertIn('for (( index=${#created_service_users[@]}-1; index>=0; index-- )); do', rollback)
        self.assertIn('userdel "${service_user}"', rollback)
        self.assertNotIn('for service_user in "${unit_users[@]}"', rollback)

    def test_rehearsal_fingerprints_diagnosis_and_background_queue_state(self) -> None:
        script = _read(DEPLOY / "rehearse-exception-stage3-migration.sh")
        diagnosis_job = script[
            script.index("diagnosis_job_legacy_fingerprint()") :
            script.index("background_job_fingerprint()")
        ]
        background_job = script[
            script.index("background_job_fingerprint()") : script.index("event_fingerprint()")
        ]
        self.assertIn("to_jsonb(j)", diagnosis_job)
        self.assertIn("exception_diagnosis_job", diagnosis_job)
        self.assertNotIn("'status'", diagnosis_job)
        self.assertNotIn("'lease_owner'", diagnosis_job)
        self.assertNotIn("'lease_expires_at'", diagnosis_job)
        self.assertIn("to_jsonb(j)", background_job)
        self.assertIn("exception_background_job", background_job)
        self.assertGreaterEqual(script.count('"$(diagnosis_job_legacy_fingerprint)"'), 3)
        self.assertGreaterEqual(script.count('"$(background_job_fingerprint)"'), 2)

    def test_manual_policy_transition_uses_compare_and_swap_without_echoing_policy(self) -> None:
        rollout = _read(ROOT / "docs" / "exception-center-stage3-rollout.md")
        manual_start = rollout.index("## 切换人工灰度")
        compose_start = rollout.index("## Docker Compose 等价隔离", manual_start)
        manual = rollout[manual_start:compose_start]

        policy_version_read = manual.index('POLICY_UPDATED_AT="$(')
        policy_get = manual.index("curl -fsS", policy_version_read)
        policy_patch = manual.index("curl -fsS -X PATCH", policy_get)
        self.assertLess(policy_get, policy_patch)
        self.assertIn('json.load(sys.stdin).get("updated_at")', manual)
        self.assertIn('"expected_updated_at": os.environ["POLICY_UPDATED_AT"]', manual)
        self.assertIn('"manual_ai_enabled": True', manual)
        self.assertIn("--data-binary @-", manual)
        self.assertIn("set +x", manual)
        self.assertIn("set -euo pipefail", manual)
        self.assertIn(">/dev/null", manual)
        self.assertIn("重新 `GET` 最新 `updated_at`", manual)
        self.assertNotIn("--data '{\"manual_ai_enabled\":true}'", manual)
        self.assertNotIn("echo ${ACCESS_TOKEN}", manual)

    def test_shutdown_timeout_is_wired_through_every_release_surface(self) -> None:
        self.assertIn("EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS=150", _read(ROOT / ".env.example"))
        self.assertIn("EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS", _read(ROOT / "docker-compose.yml"))
        self.assertIn("EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS", _read(DEPLOY / "install-exception-services.sh"))
        self.assertIn("limit.ai_shutdown_timeout", _read(RUNTIME_PATH))
        self.assertIn("TimeoutStopSec=180", _read(DEPLOY / "enterprise-business-agent-exception-ai-worker.service"))

    def test_provider_canary_is_audited_without_business_case_mutation(self) -> None:
        canary = _read(CANARY_PATH)
        self.assertIn("call_hermes_exception_diagnosis", canary)
        self.assertIn("require_complete_usage=True", canary)
        self.assertIn('CANARY_ACTION_STARTED = "exception_provider_call_started"', canary)
        self.assertIn('CANARY_ACTION_COMPLETED = "exception_provider_canary_completed"', canary)
        self.assertIn("canonical_evidence_refs_valid", canary)
        self.assertIn("safety_guard_passed", canary)
        self.assertIn("usage_complete", canary)
        self.assertNotIn("ExceptionCase", canary)
        self.assertNotIn("ExceptionDiagnosisJob", canary)
        self.assertNotIn("print(exc", canary)
        self.assertNotIn("api_key", canary.casefold())

    def test_manual_ready_requires_matching_pre_dark_provider_canary(self) -> None:
        now = datetime.now(timezone.utc)
        dark_since = now - timedelta(hours=9)
        completed_at = dark_since - timedelta(minutes=1)
        engine = create_engine("sqlite://")
        detail = {
            "status": "passed",
            "source_revision": "release-sha",
            "model": "provider-model",
            "prompt_version": "prompt.v1",
            "contract_version": "contract.v1",
            "provider_call_count": 1,
            "root_cause_code": "warehouse_missing",
            "schema_valid": True,
            "canonical_evidence_refs_valid": True,
            "safety_guard_passed": True,
            "usage_complete": True,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "evidence_truncated": False,
        }
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action_type TEXT NOT NULL,
                        resource_type TEXT NOT NULL,
                        resource_id TEXT,
                        after_data JSON,
                        created_at TIMESTAMP NOT NULL
                    )
                    """
                )
            )
            for action_type in (
                "exception_provider_call_started",
                "exception_provider_canary_completed",
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO audit_log
                            (action_type, resource_type, resource_id, after_data, created_at)
                        VALUES (:action_type, 'exception_provider_canary', 'provider-canary-1',
                                :after_data, :created_at)
                        """
                    ),
                    {
                        "action_type": action_type,
                        "after_data": json.dumps(detail),
                        "created_at": completed_at,
                    },
                )

        audit = self.runtime.ReleaseAudit()
        with engine.connect() as connection:
            self.runtime._provider_canary_checks(
                audit,
                connection,
                text,
                now=now,
                dark_since=dark_since,
                maximum_age_seconds=172800,
                source_revision="release-sha",
                provider_model="provider-model",
                prompt_version="prompt.v1",
                contract_version="contract.v1",
            )
        self.assertFalse(audit.failures)

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO audit_log
                        (action_type, resource_type, resource_id, after_data, created_at)
                    VALUES ('exception_provider_call_started', 'exception_provider_canary',
                            'provider-canary-late', '{}', :created_at)
                    """
                ),
                {"created_at": now},
            )
        failed = self.runtime.ReleaseAudit()
        with engine.connect() as connection:
            self.runtime._provider_canary_checks(
                failed,
                connection,
                text,
                now=now,
                dark_since=dark_since,
                maximum_age_seconds=172800,
                source_revision="release-sha",
                provider_model="provider-model",
                prompt_version="prompt.v1",
                contract_version="contract.v1",
            )
        self.assertIn("provider_canary.latest_completed", {item.name for item in failed.failures})

    def test_provider_usage_gate_is_ai_only_and_release_wide(self) -> None:
        installer = _read(DEPLOY / "install-exception-services.sh")
        verifier = _read(DEPLOY / "verify-exception-stage3.sh")
        compose = _read(ROOT / "docker-compose.yml")
        runtime = _read(RUNTIME_PATH)

        ai_keys = installer[installer.index("ai_environment_keys=(") : installer.index("required_environment_keys=(")]
        common_keys = installer[installer.index("common_environment_keys=(") : installer.index("ai_environment_keys=(")]
        self.assertIn("EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE", ai_keys)
        self.assertNotIn("EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE", common_keys)
        self.assertIn("EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE=true", verifier)
        self.assertIn("limit.manual_provider_usage", runtime)
        ai_compose = compose[compose.index("  exception-ai-worker:") : compose.index("  exception-scheduler:")]
        self.assertIn("EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE", ai_compose)
        non_ai_blocks = (
            compose[compose.index("  exception-worker:") : compose.index("  exception-ai-worker:")],
            compose[compose.index("  exception-scheduler:") : compose.index("  frontend:")],
        )
        for block in non_ai_blocks:
            self.assertNotIn("EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE", block)
            self.assertIn('HERMES_API_BASE_URL: ""', block)
            self.assertIn('HERMES_API_KEY: ""', block)

    def test_rollout_runs_canary_before_dark_baseline_and_passes_migration_revision(self) -> None:
        rollout = _read(ROOT / "docs" / "exception-center-stage3-rollout.md")
        rehearsal = rollout.index("rehearse-exception-stage3-migration.sh")
        rehearsal_block = rollout[rollout.rfind("sudo env", 0, rehearsal) : rehearsal]
        self.assertIn('EXPECTED_TARGET_SOURCE_REVISION="${EXPECTED_TARGET_SOURCE_REVISION}"', rehearsal_block)
        self.assertIn("EXPECTED_BACKUP_APP_ROOT=/opt/enterprise-business-agent", rehearsal_block)
        self.assertIn("REHEARSAL_PYTHON=/opt/enterprise-business-agent/.venv/bin/python", rehearsal_block)
        self.assertIn('"${RELEASE_BACKUP_DIR}" "${CANDIDATE_ROOT}"', rollout[rehearsal : rehearsal + 300])

        migration = rollout.index("bash deploy/apply-exception-stage3-migration.sh")
        migration_block = rollout[rollout.rfind("sudo env", 0, migration) : migration]
        self.assertIn(
            'EXPECTED_PREVIOUS_ALEMBIC_REVISION="${EXPECTED_PREVIOUS_ALEMBIC_REVISION}"',
            migration_block,
        )

        canary = rollout.index("scripts/run_exception_provider_canary.py", migration)
        dark_installer = rollout.index("bash deploy/install-exception-services.sh", canary)
        self.assertLess(migration, canary)
        self.assertLess(canary, dark_installer)
        canary_block = rollout[rollout.rfind("(", 0, canary) : rollout.index(")", canary) + 1]
        self.assertIn("set +x", canary_block)
        self.assertIn("EXCEPTION_AI_ENABLED=true", canary_block)
        self.assertIn("只有 canary 返回 0 后才能建立新的 DARK_SINCE", rollout)
        self.assertIn("观察期间再次运行 canary", rollout)

    def test_linux_release_artifacts_have_explicit_lf_export_contract(self) -> None:
        attributes = {
            line.strip()
            for line in _read(ROOT / ".gitattributes").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertTrue(
            {
                "*.sh text eol=lf",
                "deploy/*.service text eol=lf",
                "deploy/*.timer text eol=lf",
                "deploy/*.env text eol=lf",
            }.issubset(attributes)
        )


if __name__ == "__main__":
    unittest.main()
