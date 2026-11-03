"""Actual PostgreSQL concurrency and owned child-process fault tests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import select as io_select
import signal
import subprocess
import sys
import time
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from app import models as m
from app.core.config import settings
from app.core.database import Base, SessionLocal
from app.main import create_app
from app.services.auth_service import COOKIE
from app.services.source_task_functions import claim_diagnosis_job, utcnow
from app.services.exception_task_service import run_one_diagnosis_job, execute_diagnosis_job, heartbeat_diagnosis_job
from conftest import enqueue, ROOT


def test_migrations_match_all_nineteen_models():
    with SessionLocal() as db:
        assert len(Base.metadata.tables)==19
        assert compare_metadata(MigrationContext.configure(db.connection(),opts={'compare_type':True}),Base.metadata)==[]


def test_concurrent_api_enqueue_reuses_one_active_job(admin):
    version=admin.get('/api/cases/1').json()['case']['evidence_version']
    cookie=admin.cookies.get(COOKIE);csrf=admin.headers['X-CSRF-Token']
    def create(_):
        with TestClient(create_app()) as c:
            response=c.post('/api/cases/1/diagnose',headers={'Cookie':f'{COOKIE}={cookie}','X-CSRF-Token':csrf},
                json={'expected_evidence_version':version})
            assert response.status_code==200,response.text
            return response.json()['job']['id']
    with ThreadPoolExecutor(max_workers=8) as pool:ids=list(pool.map(create,range(8)))
    assert len(set(ids))==1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.ExceptionDiagnosisJob))==1
        assert db.scalar(select(func.count()).select_from(m.ExceptionEvent).where(m.ExceptionEvent.event_type=='diagnosis_queued'))==1


def test_concurrent_claim_returns_job_to_only_one_worker(admin):
    enqueue(admin)
    with SessionLocal() as db,db.begin():db.get(m.ExceptionPolicy,1).ai_concurrency=4
    def claim(i):
        with SessionLocal() as db:
            row=claim_diagnosis_job(db,worker_id=f'claim-worker-{i}',trigger_type='manual')
            return row.id if row else None
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(claim,range(8)))
    assert sum(r is not None for r in results)==1
    with SessionLocal() as db:assert db.scalar(select(m.ExceptionDiagnosisJob)).attempts==1


def test_skip_locked_claims_another_ready_row_without_waiting(admin):
    first=enqueue(admin,case_id=1);second=enqueue(admin,case_id=2)
    with SessionLocal() as db,db.begin():db.get(m.ExceptionPolicy,1).ai_concurrency=2
    with SessionLocal() as locked:
        locked.scalar(select(m.ExceptionDiagnosisJob).where(m.ExceptionDiagnosisJob.id==first['id']).with_for_update())
        started=time.monotonic()
        with SessionLocal() as db:claimed=claim_diagnosis_job(db,worker_id='skip-worker',trigger_type='manual')
        assert claimed.id==second['id'] and time.monotonic()-started<2
        locked.rollback()


def test_utc_budget_reservation_is_atomic_across_workers(admin):
    enqueue(admin,case_id=1);enqueue(admin,case_id=2)
    with SessionLocal() as db,db.begin():
        policy=db.get(m.ExceptionPolicy,1);policy.manual_ai_daily_limit=1;policy.ai_concurrency=2
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda i:run_one_diagnosis_job(worker_id=f'budget-worker-{i}'),range(2)))
    assert sorted(results)==['completed','failed']
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.ExceptionEvent).where(m.ExceptionEvent.event_type=='diagnosis_ai_call_started'))==1
        assert db.scalar(select(func.count()).select_from(m.ExceptionDiagnosis))==1


def test_expired_or_old_generation_heartbeat_cannot_revive_lease(admin):
    job=enqueue(admin)
    with SessionLocal() as db:claimed=claim_diagnosis_job(db,worker_id='same-name-worker')
    with SessionLocal() as db,db.begin():db.get(m.ExceptionDiagnosisJob,job['id']).lease_expires_at=utcnow()-timedelta(seconds=1)
    assert not heartbeat_diagnosis_job(job_id=job['id'],worker_id='same-name-worker',lease_generation=1)
    with SessionLocal() as db:replacement=claim_diagnosis_job(db,worker_id='same-name-worker')
    assert replacement.attempts==2
    assert not heartbeat_diagnosis_job(job_id=job['id'],worker_id='same-name-worker',lease_generation=1)
    assert execute_diagnosis_job(job_id=job['id'],worker_id='same-name-worker',lease_generation=1)=='lease_lost'
    assert execute_diagnosis_job(job_id=job['id'],worker_id='same-name-worker',lease_generation=2)=='completed'


def spawn_worker(worker_id,*extra):
    return subprocess.Popen([sys.executable,'-m','app.tasks.exception_ai_worker','--once','--worker-id',worker_id,*extra],
        cwd=ROOT,env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)


def until(predicate,timeout=12):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(0.03)
    raise AssertionError('Timed out waiting for independent PostgreSQL/process state')


def current_job(job_id):
    with SessionLocal() as db:
        job=db.get(m.ExceptionDiagnosisJob,job_id)
        return {'id':job.id,'status':job.status,'generation':job.attempts,'worker_id':job.lease_owner,
                'lease_expires_at':job.lease_expires_at.isoformat() if job.lease_expires_at else None}


def wait_processing(job_id,worker_id):
    return until(lambda:(r if (r:=current_job(job_id))['status']=='processing' and r['worker_id']==worker_id else None))


def wait_expired(job_id):
    def check():
        with SessionLocal() as db:
            row=db.get(m.ExceptionDiagnosisJob,job_id)
            return row.lease_expires_at is not None and row.lease_expires_at<utcnow()
    until(check)


def write_proof(name,details):
    folder=ROOT/'runtime/test-evidence';folder.mkdir(parents=True,exist_ok=True)
    (folder/f'{name}.json').write_text(json.dumps(details,ensure_ascii=False,indent=2)+'\n')


def cleanup(process):
    if process.poll() is None:
        process.send_signal(signal.SIGCONT)
        process.kill();process.wait(timeout=5)


def test_sigkill_worker_is_recovered_by_a_new_process(admin):
    job=enqueue(admin)
    old=spawn_worker('killed-worker','--provider-delay','5')
    try:
        first=wait_processing(job['id'],'killed-worker')
        old.kill();old.wait(timeout=5)
        assert old.returncode==-signal.SIGKILL
        wait_expired(job['id'])
        new=spawn_worker('recovery-worker')
        try:
            out,err=new.communicate(timeout=15)
            assert new.returncode==0,(out,err)
        finally:cleanup(new)
        final=current_job(job['id'])
        assert final['status']=='completed' and final['generation']==2
        write_proof('sigkill-recovery',{'first_claim':first,'killed_signal':'SIGKILL','replacement_logs':out.splitlines(),'final':final})
    finally:cleanup(old)


def test_sigstop_late_result_cannot_overwrite_replacement(admin):
    job=enqueue(admin)
    old=spawn_worker('late-worker','--pause-before-write','2')
    lines=[]
    try:
        deadline=time.monotonic()+15
        ready=False
        while time.monotonic()<deadline:
            readable,_,_=io_select.select([old.stdout],[],[],0.2)
            if readable:
                # Read pipe bytes directly: TextIO buffering can hide a second ready line from select().
                chunk=os.read(old.stdout.fileno(),65536).decode()
                for line in chunk.splitlines():
                    if line:
                        lines.append(line)
                        if json.loads(line).get('event')=='provider_result_ready':ready=True
                if ready:break
            assert old.poll() is None,old.stderr.read()
        assert ready,lines
        old.send_signal(signal.SIGSTOP)
        first=current_job(job['id'])
        wait_expired(job['id'])
        new=spawn_worker('replacement-worker')
        try:
            out,err=new.communicate(timeout=15)
            assert new.returncode==0,(out,err)
        finally:cleanup(new)
        with SessionLocal() as db:
            completed=db.scalar(select(m.ExceptionDiagnosis))
            replacement_request=completed.request_id
        old.send_signal(signal.SIGCONT)
        tail,err=old.communicate(timeout=15)
        assert old.returncode==0,(tail,err)
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(m.ExceptionDiagnosis))==1
            assert db.scalar(select(m.ExceptionDiagnosis)).request_id==replacement_request
            assert db.scalar(select(m.ExceptionDiagnosisJob)).attempts==2
            rejected=db.scalar(select(m.ExceptionEvent).where(m.ExceptionEvent.event_type=='stale_result_rejected'))
            assert rejected.detail_json['rejected_generation']==1 and rejected.detail_json['current_generation']==2
        write_proof('sigstop-stale-result',{'old_after_provider':lines,'first_claim':first,'replacement_logs':out.splitlines(),
            'resumed_old_logs':tail.splitlines(),'final':current_job(job['id']),'replacement_request_id_unchanged':replacement_request})
    finally:cleanup(old)


def test_heartbeats_keep_slow_live_worker_from_being_reclaimed(admin):
    job=enqueue(admin)
    live=spawn_worker('live-heartbeat-worker','--provider-delay','1.5')
    try:
        wait_processing(job['id'],'live-heartbeat-worker')
        time.sleep(settings.exception_job_lease_seconds+0.25)
        with SessionLocal() as db:other=claim_diagnosis_job(db,worker_id='unneeded-replacement')
        assert other is None
        out,err=live.communicate(timeout=15)
        assert live.returncode==0,(out,err)
        assert current_job(job['id'])['generation']==1 and current_job(job['id'])['status']=='completed'
    finally:cleanup(live)
