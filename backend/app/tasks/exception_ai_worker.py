from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
import time

from app.core.config import settings
from app.services.exception_task_service import (
    current_exception_runtime_policy,
    handoff_diagnosis_jobs_for_worker,
    latest_persisted_ai_circuit_state,
    record_service_heartbeat,
    run_one_diagnosis_job,
)
from app.services.hermes_ai_service import (
    configure_hermes_concurrency,
    hermes_circuit_status,
    restore_hermes_circuit,
)


logger = logging.getLogger(__name__)


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class _DaemonJobSlot:
    def __init__(self, *, worker_id: str, stop_event: threading.Event, index: int):
        self.done = threading.Event()
        self.status: str | None = None
        self.error_name: str | None = None
        self.thread = threading.Thread(
            target=self._run,
            kwargs={"worker_id": worker_id, "stop_event": stop_event},
            name=f"exception-ai-{index}",
            daemon=True,
        )

    def _run(self, *, worker_id: str, stop_event: threading.Event) -> None:
        try:
            self.status = run_one_diagnosis_job(worker_id=worker_id, stop_event=stop_event)
        except Exception as exc:
            self.error_name = exc.__class__.__name__
        finally:
            self.done.set()

    def start(self) -> None:
        self.thread.start()


def _attempt_lease_handoff(*, worker_id: str, deadline: float) -> int | None:
    """Attempt DB lease handoff without allowing DB waits to break shutdown bounds."""
    completed = threading.Event()
    result: list[int | Exception] = []

    def handoff() -> None:
        try:
            result.append(handoff_diagnosis_jobs_for_worker(worker_id=worker_id))
        except Exception as exc:
            result.append(exc)
        finally:
            completed.set()

    threading.Thread(
        target=handoff,
        name="exception-ai-lease-handoff",
        daemon=True,
    ).start()
    while not completed.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        completed.wait(min(0.05, remaining))
    if not result:
        return None
    if isinstance(result[0], Exception):
        logger.error("Failed to hand off AI worker leases: %s", result[0].__class__.__name__)
        return None
    return int(result[0])


def run_worker(*, once: bool = False, stop_event: threading.Event | None = None) -> None:
    stop = stop_event or threading.Event()

    def request_stop(signum, frame) -> None:  # noqa: ANN001, ARG001
        logger.info("Exception AI worker received shutdown signal")
        stop.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

    worker_id = worker_identity()
    policy = current_exception_runtime_policy()
    concurrency = max(1, policy.ai_concurrency)
    configure_hermes_concurrency(concurrency)
    persisted_circuit = latest_persisted_ai_circuit_state()
    restored_circuit = restore_hermes_circuit(persisted_circuit)
    if persisted_circuit is not None:
        logger.info(
            "Restored Hermes circuit with failures=%s retry_after_seconds=%s",
            restored_circuit["consecutive_failures"],
            restored_circuit["retry_after_seconds"],
        )
    poll_seconds = max(1, settings.exception_worker_poll_seconds)
    heartbeat_seconds = max(5, settings.exception_runtime_heartbeat_seconds)
    next_policy_refresh = 0.0
    next_heartbeat = 0.0
    policy_enabled = policy.is_enabled
    running: list[_DaemonJobSlot] = []
    slot_index = 0
    submitted_once = False
    logger.info("Exception AI worker %s started with concurrency=%s", worker_id, concurrency)

    def collect_finished() -> bool:
        finished = [slot for slot in running if slot.done.is_set()]
        for slot in finished:
            running.remove(slot)
            slot.thread.join(timeout=0)
            if slot.error_name:
                logger.error("Unhandled exception AI worker failure: %s", slot.error_name)
            elif slot.status:
                logger.info("Exception diagnosis job finished with status=%s", slot.status)
        return bool(finished)

    try:
        while not stop.is_set():
            if collect_finished():
                # Persist the provider circuit immediately after each completed
                # call instead of waiting for the next periodic heartbeat.
                next_heartbeat = 0.0
            if once and submitted_once and not running:
                return

            now = time.monotonic()
            if now >= next_policy_refresh:
                try:
                    policy = current_exception_runtime_policy()
                    policy_enabled = policy.is_enabled
                    desired_concurrency = max(1, policy.ai_concurrency)
                    if desired_concurrency != concurrency:
                        concurrency = desired_concurrency
                        configure_hermes_concurrency(concurrency)
                except Exception as exc:
                    logger.error("Failed to reload exception runtime policy: %s", exc.__class__.__name__)
                next_policy_refresh = now + 60

            if now >= next_heartbeat:
                try:
                    record_service_heartbeat(
                        service_type="ai_worker",
                        instance_id=worker_id,
                        metadata={
                            "policy_enabled": policy_enabled,
                            "global_ai_enabled": settings.exception_ai_enabled,
                            "concurrency": concurrency,
                            "running_jobs": len(running),
                            "circuit": hermes_circuit_status(),
                        },
                    )
                except Exception as exc:
                    logger.error("Failed to persist AI worker heartbeat: %s", exc.__class__.__name__)
                next_heartbeat = now + heartbeat_seconds

            if settings.exception_center_enabled and settings.exception_ai_enabled and policy_enabled:
                if len(running) < concurrency and (not once or not submitted_once):
                    slot_index += 1
                    slot = _DaemonJobSlot(
                        worker_id=worker_id,
                        stop_event=stop,
                        index=slot_index,
                    )
                    running.append(slot)
                    submitted_once = submitted_once or once
                    slot.start()
            elif once:
                return

            if not running:
                stop.wait(poll_seconds)
            else:
                stop.wait(0.25)
    finally:
        stop.set()
        shutdown_timeout = max(0.1, float(settings.exception_ai_shutdown_timeout_seconds))
        shutdown_deadline = time.monotonic() + shutdown_timeout
        first_handoff_deadline = min(
            shutdown_deadline,
            time.monotonic() + min(1.0, shutdown_timeout * 0.2),
        )
        _attempt_lease_handoff(worker_id=worker_id, deadline=first_handoff_deadline)

        final_handoff_reserve = min(1.0, shutdown_timeout * 0.2)
        job_wait_deadline = max(time.monotonic(), shutdown_deadline - final_handoff_reserve)
        while running and time.monotonic() < job_wait_deadline:
            collect_finished()
            if not running:
                break
            remaining = job_wait_deadline - time.monotonic()
            running[0].thread.join(timeout=min(0.05, max(0.0, remaining)))

        _attempt_lease_handoff(worker_id=worker_id, deadline=shutdown_deadline)
        collect_finished()
        if running:
            logger.warning(
                "Exception AI worker exiting with %s abandoned daemon task(s) after %.1fs",
                len(running),
                shutdown_timeout,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the unified exception AI diagnosis worker")
    parser.add_argument("--once", action="store_true", help="process at most one queued diagnosis job")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_worker(once=args.once)


if __name__ == "__main__":
    main()
