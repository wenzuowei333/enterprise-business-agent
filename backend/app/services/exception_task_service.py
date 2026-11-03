"""Showcase executor around pinned ERP claim/owned-lock/store implementations."""
import contextlib
import json
import threading
import time
import uuid
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, update, func
from app import models as m
from app.core.config import settings
from app.core.database import SessionLocal
from app.services.access_control_service import requester_may_diagnose
from app.services.exception_center_service import refresh_inventory_case
from app.services import diagnosis_provider
from app.services.source_task_functions import (claim_diagnosis_job, _lock_owned_diagnosis_context,
    _obsolete_diagnosis_detail, _store_diagnosis, utcnow)


def log(event,**fields):
    print(json.dumps({'event':event,**fields},ensure_ascii=False),flush=True)


def heartbeat_diagnosis_job(*,job_id,worker_id,lease_generation):
    now=utcnow()
    with SessionLocal() as db,db.begin():
        changed=db.execute(update(m.ExceptionDiagnosisJob).where(m.ExceptionDiagnosisJob.id==job_id,
            m.ExceptionDiagnosisJob.status=='processing',m.ExceptionDiagnosisJob.lease_owner==worker_id,
            m.ExceptionDiagnosisJob.attempts==lease_generation,m.ExceptionDiagnosisJob.lease_expires_at>now)
            .values(lease_expires_at=now+timedelta(seconds=settings.exception_job_lease_seconds))).rowcount
        return bool(changed)


@contextlib.contextmanager
def diagnosis_job_heartbeat(job_id,worker_id,generation):
    stopped=threading.Event()
    def beat():
        while not stopped.wait(settings.exception_worker_heartbeat_seconds):
            try:
                if not heartbeat_diagnosis_job(job_id=job_id,worker_id=worker_id,lease_generation=generation):
                    return
            except Exception:
                # A failed heartbeat never authorizes a write; final ownership check still applies.
                log('heartbeat_unavailable',job_id=job_id,generation=generation)
    thread=threading.Thread(target=beat,daemon=True,name='diagnosis-heartbeat');thread.start()
    try: yield
    finally: stopped.set();thread.join(timeout=2)


def _event(db,job,name,**details):
    db.add(m.ExceptionEvent(case_id=job.case_id,event_type=name,detail_json={
        'job_id':job.id,'generation':job.attempts,'worker_id':job.lease_owner,
        'evidence_version':job.evidence_version,**details}))


def _cancel_locked(db,job,case,reason):
    _event(db,job,'diagnosis_cancelled',reason=reason)
    job.status='cancelled';job.error_message=reason;job.completed_at=utcnow()
    job.lease_owner=None;job.lease_expires_at=None
    others=db.scalar(select(m.ExceptionDiagnosisJob.id).where(m.ExceptionDiagnosisJob.case_id==case.id,
        m.ExceptionDiagnosisJob.id!=job.id,m.ExceptionDiagnosisJob.evidence_version==case.evidence_version,
        m.ExceptionDiagnosisJob.status.in_(['queued','processing'])).limit(1))
    if not others and case.status=='processing':case.status='open'
    db.commit()


def _validate_context(db,job,case,phase):
    if not case:
        job.status='failed';job.completed_at=utcnow();job.lease_owner=None;job.lease_expires_at=None
        job.error_message='case_missing';db.commit();return False
    if not requester_may_diagnose(db,job):
        _cancel_locked(db,job,case,'requester_access_revoked');return False
    if job.cancel_requested_at:
        _cancel_locked(db,job,case,'cancel_requested');return False
    if case.status in {'resolved','ignored'}:
        _cancel_locked(db,job,case,'case_terminal');return False
    try:
        refresh_inventory_case(db,case)
    except HTTPException:
        _cancel_locked(db,job,case,'source_evidence_unavailable');return False
    obsolete=_obsolete_diagnosis_detail(case,job,phase=phase)
    if obsolete:
        _cancel_locked(db,job,case,obsolete[1]['reason_code']);return False
    return True


def _fail_locked(db,job,case,code,retryable):
    _event(db,job,'diagnosis_retry' if retryable and job.attempts<settings.exception_job_max_attempts else 'diagnosis_failed',error_code=code)
    job.lease_owner=None;job.lease_expires_at=None;job.error_message=code
    if retryable and job.attempts<settings.exception_job_max_attempts:
        job.status='queued';job.available_at=utcnow()+timedelta(seconds=settings.exception_retry_seconds)
    else:
        job.status='failed';job.completed_at=utcnow();case.status='blocked'
    db.commit()


def _reserve_budget(db,job,case,request_id):
    policy=db.scalar(select(m.ExceptionPolicy).where(m.ExceptionPolicy.policy_key=='default').with_for_update())
    if not settings.exception_ai_enabled or not settings.exception_center_enabled or not policy or not policy.is_enabled or not policy.manual_ai_enabled:
        return 'diagnosis_disabled'
    # PostgreSQL UTC day boundaries, atomically counted under the policy row lock.
    count=db.scalar(select(func.count(m.ExceptionEvent.id)).where(m.ExceptionEvent.event_type=='diagnosis_ai_call_started',
        m.ExceptionEvent.created_at>=func.date_trunc('day',func.timezone('UTC',func.now())).op('AT TIME ZONE')('UTC'))) or 0
    if count>=policy.manual_ai_daily_limit:return 'daily_budget_exhausted'
    _event(db,job,'diagnosis_ai_call_started',request_id=request_id,model='mock-fixed-v1')
    db.commit()
    return None


def _record_stale(job_id,worker_id,generation):
    with SessionLocal() as db:
        job=db.get(m.ExceptionDiagnosisJob,job_id)
        if job:
            db.add(m.ExceptionEvent(case_id=job.case_id,event_type='stale_result_rejected',detail_json={
                'job_id':job_id,'rejected_worker':worker_id,'rejected_generation':generation,'current_generation':job.attempts}))
            db.commit()
    log('lease_lost',job_id=job_id,worker_id=worker_id,generation=generation)


def execute_diagnosis_job(*,job_id,worker_id,lease_generation,provider_delay=0,pause_before_write=0):
    request_id=str(uuid.uuid4())
    with diagnosis_job_heartbeat(job_id,worker_id,lease_generation):
        with SessionLocal() as db:
            job,case=_lock_owned_diagnosis_context(db,job_id=job_id,worker_id=worker_id,lease_generation=lease_generation)
            if not job: db.rollback();return 'lease_lost'
            if not _validate_context(db,job,case,'before_provider'):return 'cancelled'
            if job.attempts>settings.exception_job_max_attempts:
                _fail_locked(db,job,case,'attempts_exhausted',False);return 'failed'
            evidence=db.scalar(select(m.ExceptionEvidence).where(m.ExceptionEvidence.case_id==case.id,
                m.ExceptionEvidence.evidence_version==job.evidence_version))
            if not evidence:
                _cancel_locked(db,job,case,'evidence_missing');return 'cancelled'
            payload=evidence.data_json.copy();scenario=job.demo_scenario
            budget_error=_reserve_budget(db,job,case,request_id)
            if budget_error:
                _fail_locked(db,job,case,budget_error,False);return 'failed'
        # No locks/transactions held across the provider call.
        error=None;result=None
        try:
            result=diagnosis_provider.invoke(payload,scenario,request_id=request_id,delay=provider_delay)
            log('provider_result_ready',job_id=job_id,worker_id=worker_id,generation=lease_generation)
            if pause_before_write:time.sleep(pause_before_write)  # explicit local fault injection only
        except Exception as exc:error=exc
        with SessionLocal() as db:
            job,case=_lock_owned_diagnosis_context(db,job_id=job_id,worker_id=worker_id,lease_generation=lease_generation)
            if not job:
                db.rollback();_record_stale(job_id,worker_id,lease_generation);return 'lease_lost'
            if not _validate_context(db,job,case,'after_provider'):return 'cancelled'
            if error is not None:
                code='provider_timeout' if isinstance(error,TimeoutError) else 'invalid_provider_output'
                _fail_locked(db,job,case,code,isinstance(error,TimeoutError));return job.status
            _store_diagnosis(db,job=job,case=case,result=result)
            return 'completed'


def run_one_diagnosis_job(*,worker_id,provider_delay=0,pause_before_write=0):
    with SessionLocal() as db:
        job=claim_diagnosis_job(db,worker_id=worker_id,trigger_type='manual')
        if not job:return None
        job_id=job.id;generation=job.attempts
    log('claimed',job_id=job_id,worker_id=worker_id,generation=generation)
    status=execute_diagnosis_job(job_id=job_id,worker_id=worker_id,lease_generation=generation,
        provider_delay=provider_delay,pause_before_write=pause_before_write)
    log('finished',job_id=job_id,worker_id=worker_id,generation=generation,status=status)
    return status
