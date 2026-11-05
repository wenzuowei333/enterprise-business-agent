import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from app.tasks.exception_scheduler import (
        _FULL_SCAN_LOCK_KEY,
        build_scheduler,
        scheduler_advisory_lock,
    )

    APSCHEDULER_AVAILABLE = True
except ModuleNotFoundError:
    APSCHEDULER_AVAILABLE = False


@unittest.skipUnless(APSCHEDULER_AVAILABLE, "APScheduler is not installed in the local test runtime")
class ExceptionSchedulerTest(unittest.TestCase):
    def test_local_advisory_lock_rejects_second_scheduler_instance(self):
        entered = threading.Event()
        release = threading.Event()
        results = []

        def hold_lock():
            with scheduler_advisory_lock(_FULL_SCAN_LOCK_KEY) as acquired:
                results.append(acquired)
                entered.set()
                release.wait(2)

        fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
        with patch("app.tasks.exception_scheduler.engine", fake_engine):
            thread = threading.Thread(target=hold_lock)
            thread.start()
            self.assertTrue(entered.wait(1))
            with scheduler_advisory_lock(_FULL_SCAN_LOCK_KEY) as acquired:
                results.append(acquired)
            release.set()
            thread.join(2)
        self.assertEqual(results, [True, False])

    def test_scheduler_registers_local_time_scan_and_digest(self):
        scheduler = build_scheduler()
        jobs = {job.id: str(job.trigger) for job in scheduler.get_jobs()}
        self.assertIn("exception-full-scan", jobs)
        self.assertIn("hour='2'", jobs["exception-full-scan"])
        self.assertIn("minute='30'", jobs["exception-full-scan"])
        self.assertIn("exception-digest", jobs)
        self.assertIn("hour='8'", jobs["exception-digest"])
        self.assertIn("exception-policy-refresh", jobs)


if __name__ == "__main__":
    unittest.main()
