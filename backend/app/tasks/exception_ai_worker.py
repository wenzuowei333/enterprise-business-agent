"""Independent local Worker process; claim and writes always use PostgreSQL."""
import argparse
import signal
import threading
import uuid
from app.services.exception_task_service import run_one_diagnosis_job, log


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--worker-id',default='demo-worker-'+uuid.uuid4().hex[:8])
    parser.add_argument('--provider-delay',type=float,default=0,help='Local Mock fault injection, seconds')
    parser.add_argument('--pause-before-write',type=float,default=0,help='Local fault injection after a valid result')
    args=parser.parse_args()
    if min(args.provider_delay,args.pause_before_write)<0 or max(args.provider_delay,args.pause_before_write)>30:
        parser.error('Fault-injection delays must be between 0 and 30 seconds')
    stopped=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopped.set())
    signal.signal(signal.SIGINT,lambda *_:stopped.set())
    while not stopped.is_set():
        try:
            result=run_one_diagnosis_job(worker_id=args.worker_id,provider_delay=args.provider_delay,pause_before_write=args.pause_before_write)
        except Exception as exc:
            log('worker_iteration_failed',error_type=type(exc).__name__)
            if args.once:raise
            result=None
        if args.once:break
        if result is None:stopped.wait(0.25)


if __name__=='__main__':
    main()
