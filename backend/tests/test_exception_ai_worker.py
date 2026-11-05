import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.tasks.exception_ai_worker import run_worker


class ExceptionAiWorkerShutdownTest(unittest.TestCase):
    def test_worker_restores_latest_persisted_circuit_before_claiming_work(self):
        policy = SimpleNamespace(is_enabled=False, ai_concurrency=1)
        persisted = {"open": True, "consecutive_failures": 5, "retry_after_seconds": 300}
        restored = {"open": True, "consecutive_failures": 5, "retry_after_seconds": 299}

        with (
            patch("app.tasks.exception_ai_worker.current_exception_runtime_policy", return_value=policy),
            patch("app.tasks.exception_ai_worker.configure_hermes_concurrency"),
            patch(
                "app.tasks.exception_ai_worker.latest_persisted_ai_circuit_state",
                return_value=persisted,
            ) as load_circuit,
            patch(
                "app.tasks.exception_ai_worker.restore_hermes_circuit",
                return_value=restored,
            ) as restore_circuit,
            patch("app.tasks.exception_ai_worker.record_service_heartbeat"),
            patch("app.tasks.exception_ai_worker.handoff_diagnosis_jobs_for_worker", return_value=0),
            patch("app.tasks.exception_ai_worker.run_one_diagnosis_job") as run_one,
            patch("app.tasks.exception_ai_worker.settings.exception_center_enabled", True),
            patch("app.tasks.exception_ai_worker.settings.exception_ai_enabled", True),
            patch("app.tasks.exception_ai_worker.settings.exception_ai_shutdown_timeout_seconds", 0.2),
        ):
            run_worker(once=True)

        load_circuit.assert_called_once_with()
        restore_circuit.assert_called_once_with(persisted)
        run_one.assert_not_called()

    def test_sigterm_sets_shared_stop_token_before_worker_returns(self):
        callbacks = {}
        observed_stop_event = None

        def register_signal(signum, callback):  # noqa: ANN001
            callbacks[signum] = callback

        def run_one(*, worker_id, stop_event, trigger_type=None):  # noqa: ARG001
            nonlocal observed_stop_event
            observed_stop_event = stop_event
            self.assertFalse(stop_event.is_set())
            callbacks[signal.SIGTERM](signal.SIGTERM, None)
            self.assertTrue(stop_event.is_set())
            return "queued"

        policy = SimpleNamespace(is_enabled=True, ai_concurrency=1)
        with (
            patch("app.tasks.exception_ai_worker.signal.signal", side_effect=register_signal),
            patch("app.tasks.exception_ai_worker.current_exception_runtime_policy", return_value=policy),
            patch("app.tasks.exception_ai_worker.configure_hermes_concurrency"),
            patch("app.tasks.exception_ai_worker.latest_persisted_ai_circuit_state", return_value=None),
            patch("app.tasks.exception_ai_worker.restore_hermes_circuit", return_value={"consecutive_failures": 0, "retry_after_seconds": 0}),
            patch("app.tasks.exception_ai_worker.record_service_heartbeat"),
            patch("app.tasks.exception_ai_worker.hermes_circuit_status", return_value={"open": False}),
            patch("app.tasks.exception_ai_worker.handoff_diagnosis_jobs_for_worker", return_value=0),
            patch("app.tasks.exception_ai_worker.run_one_diagnosis_job", side_effect=run_one),
            patch("app.tasks.exception_ai_worker.settings.exception_center_enabled", True),
            patch("app.tasks.exception_ai_worker.settings.exception_ai_enabled", True),
            patch("app.tasks.exception_ai_worker.settings.exception_ai_shutdown_timeout_seconds", 0.2),
        ):
            run_worker(once=True)

        self.assertIsInstance(observed_stop_event, threading.Event)
        self.assertTrue(observed_stop_event.is_set())
        self.assertIn(signal.SIGTERM, callbacks)

    def test_pre_stopped_worker_does_not_claim_work(self):
        stop_event = threading.Event()
        stop_event.set()
        policy = SimpleNamespace(is_enabled=True, ai_concurrency=1)

        with (
            patch("app.tasks.exception_ai_worker.current_exception_runtime_policy", return_value=policy),
            patch("app.tasks.exception_ai_worker.configure_hermes_concurrency"),
            patch("app.tasks.exception_ai_worker.latest_persisted_ai_circuit_state", return_value=None),
            patch("app.tasks.exception_ai_worker.restore_hermes_circuit", return_value={"consecutive_failures": 0, "retry_after_seconds": 0}),
            patch("app.tasks.exception_ai_worker.handoff_diagnosis_jobs_for_worker", return_value=0),
            patch("app.tasks.exception_ai_worker.run_one_diagnosis_job") as run_one,
            patch("app.tasks.exception_ai_worker.settings.exception_center_enabled", True),
            patch("app.tasks.exception_ai_worker.settings.exception_ai_enabled", True),
            patch("app.tasks.exception_ai_worker.settings.exception_ai_shutdown_timeout_seconds", 0.2),
        ):
            run_worker(once=True, stop_event=stop_event)

        run_one.assert_not_called()

    def test_hung_daemon_task_cannot_extend_shutdown_deadline(self):
        stop_event = threading.Event()
        task_started = threading.Event()
        release_task = threading.Event()
        policy = SimpleNamespace(is_enabled=True, ai_concurrency=1)

        def hanging_job(*, worker_id, stop_event):  # noqa: ARG001
            task_started.set()
            release_task.wait(30)
            return "queued"

        with (
            patch("app.tasks.exception_ai_worker.current_exception_runtime_policy", return_value=policy),
            patch("app.tasks.exception_ai_worker.configure_hermes_concurrency"),
            patch("app.tasks.exception_ai_worker.latest_persisted_ai_circuit_state", return_value=None),
            patch("app.tasks.exception_ai_worker.restore_hermes_circuit", return_value={"consecutive_failures": 0, "retry_after_seconds": 0}),
            patch("app.tasks.exception_ai_worker.record_service_heartbeat"),
            patch("app.tasks.exception_ai_worker.hermes_circuit_status", return_value={"open": False}),
            patch("app.tasks.exception_ai_worker.handoff_diagnosis_jobs_for_worker", return_value=1) as handoff,
            patch("app.tasks.exception_ai_worker.run_one_diagnosis_job", side_effect=hanging_job),
            patch("app.tasks.exception_ai_worker.settings.exception_center_enabled", True),
            patch("app.tasks.exception_ai_worker.settings.exception_ai_enabled", True),
            patch("app.tasks.exception_ai_worker.settings.exception_ai_shutdown_timeout_seconds", 0.3),
        ):
            worker = threading.Thread(target=run_worker, kwargs={"once": True, "stop_event": stop_event})
            worker.start()
            self.assertTrue(task_started.wait(2))
            started = time.monotonic()
            stop_event.set()
            worker.join(timeout=1)
            elapsed = time.monotonic() - started
            release_task.set()

        self.assertFalse(worker.is_alive())
        self.assertLess(elapsed, 0.8)
        self.assertGreaterEqual(handoff.call_count, 2)

    @unittest.skipIf(os.name == "nt", "POSIX SIGTERM semantics are required")
    def test_real_subprocess_sigterm_exits_despite_hung_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            started_path = Path(temp_dir) / "started"
            stopped_path = Path(temp_dir) / "stopped"
            script = f"""
import time
from pathlib import Path
from types import SimpleNamespace
from app.tasks import exception_ai_worker as worker

worker.current_exception_runtime_policy = lambda: SimpleNamespace(is_enabled=True, ai_concurrency=1)
worker.configure_hermes_concurrency = lambda value: value
worker.latest_persisted_ai_circuit_state = lambda: None
worker.restore_hermes_circuit = lambda value: {{"consecutive_failures": 0, "retry_after_seconds": 0}}
worker.record_service_heartbeat = lambda **kwargs: None
worker.hermes_circuit_status = lambda: {{"open": False}}
worker.handoff_diagnosis_jobs_for_worker = lambda **kwargs: 1
worker.settings.exception_center_enabled = True
worker.settings.exception_ai_enabled = True
worker.settings.exception_ai_shutdown_timeout_seconds = 0.3

def hang_forever(**kwargs):
    Path({str(started_path)!r}).write_text("started", encoding="utf-8")
    while True:
        time.sleep(60)

worker.run_one_diagnosis_job = hang_forever
worker.run_worker(once=True)
Path({str(stopped_path)!r}).write_text("stopped", encoding="utf-8")
"""
            env = os.environ.copy()
            backend_root = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = os.pathsep.join(
                item for item in (backend_root, env.get("PYTHONPATH", "")) if item
            )
            process = subprocess.Popen(
                [sys.executable, "-c", script],
                cwd=backend_root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 10
                while not started_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(started_path.exists())
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=3)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=3)

            self.assertEqual(process.returncode, 0, msg=f"stdout={stdout}\nstderr={stderr}")
            self.assertTrue(stopped_path.exists())


if __name__ == "__main__":
    unittest.main()
