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
    record_service_heartbeat,
    run_one_background_job,
)


logger = logging.getLogger(__name__)


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def run_worker(*, once: bool = False) -> None:
    stop = threading.Event()

    def request_stop(signum, frame) -> None:  # noqa: ANN001, ARG001
        logger.info("Exception worker received shutdown signal")
        stop.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

    worker_id = worker_identity()
    poll_seconds = max(1, settings.exception_worker_poll_seconds)
    heartbeat_seconds = max(5, settings.exception_runtime_heartbeat_seconds)
    next_policy_refresh = 0.0
    next_heartbeat = 0.0
    policy_enabled = True
    logger.info("Exception background worker %s started", worker_id)
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_policy_refresh:
            try:
                policy_enabled = current_exception_runtime_policy().is_enabled
            except Exception as exc:
                logger.error("Failed to reload exception runtime policy: %s", exc.__class__.__name__)
            next_policy_refresh = now + 60
        if now >= next_heartbeat:
            try:
                record_service_heartbeat(
                    service_type="worker",
                    instance_id=worker_id,
                    metadata={"policy_enabled": policy_enabled, "mode": "background"},
                )
            except Exception as exc:
                logger.error("Failed to persist worker heartbeat: %s", exc.__class__.__name__)
            next_heartbeat = now + heartbeat_seconds
        status = None
        if settings.exception_center_enabled and policy_enabled:
            try:
                status = run_one_background_job(worker_id=worker_id)
            except Exception as exc:
                logger.error("Unhandled exception background worker failure: %s", exc.__class__.__name__)
        if status:
            logger.info("Exception background job finished with status=%s", status)
        if once:
            return
        if status is None:
            stop.wait(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the unified exception diagnosis worker")
    parser.add_argument("--once", action="store_true", help="process at most one queued job")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_worker(once=args.once)


if __name__ == "__main__":
    main()
