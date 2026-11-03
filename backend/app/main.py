"""New minimal showcase API. No migrations, seeds or Worker run at import/startup."""
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import secrets
import time
from collections import defaultdict, deque
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app import models as m
from app.core.config import settings
from app.core.database import SessionLocal
from app.services.auth_service import get_db, require_user, require_csrf, login, COOKIE, digest, audit
from app.services.access_control_service import permission_codes, require_permission, scoped_cases, visible_case
from app.services.exception_center_service import create_diagnosis_job, refresh_inventory_case
from app.services.workflow_lock import acquire_exception_case_mutation_lock
from app.services.evidence_contract import prepare_exception_evidence
from app.services.inventory_agent_service import _evidence_version


class LoginInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(min_length=1,max_length=80)
    password:str=Field(min_length=1,max_length=200)


class Scenario(str,Enum):
    success='success'
    missing_evidence='missing_evidence'
    invalid_schema='invalid_schema'
    unknown_reference='unknown_reference'
    timeout='timeout'


class DiagnosisInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_evidence_version:str=Field(min_length=1,max_length=128,strict=True)
    scenario:Scenario=Scenario.success
    force:bool=Field(default=False,strict=True)


def user_payload(db,user):
    return {'id':user.id,'username':user.username,'role':user.role,'permissions':sorted(permission_codes(db,user))}


def job_payload(job):
    return {'id':job.id,'job_no':job.job_no,'case_id':job.case_id,'evidence_version':job.evidence_version,
            'status':job.status,'generation':job.attempts,'worker_id':job.lease_owner,
            'lease_expires_at':job.lease_expires_at,'error_code':job.error_message,
            'scenario':job.demo_scenario,'available_at':job.available_at,'completed_at':job.completed_at}


def case_payload(db,case):
    anomaly=db.get(m.InventoryAnomalyCase,case.inventory_anomaly_case_id)
    snapshot=db.get(m.InventorySnapshot,anomaly.snapshot_id) if anomaly else None
    source_version=_evidence_version(snapshot,anomaly.reason_code) if snapshot else None
    return {'id':case.id,'case_no':case.case_no,'title':case.title,'rule_code':case.rule_code,'status':case.status,
            'warehouse':snapshot.warehouse_name if snapshot else None,'product_code':snapshot.product_code if snapshot else None,
            'evidence_version':case.evidence_version,'source_changed':source_version!=case.evidence_version,
            'reason':case.reason,'synthetic':True}


def create_app(session_factory=None):
    app=FastAPI(title=settings.app_name,version='0.3.0')
    app.state.session_factory=session_factory or SessionLocal
    attempts=defaultdict(deque)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])

    @app.middleware('http')
    async def safety_headers(request,call_next):
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin=request.headers.get('origin')
            if origin and origin!=str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':{'code':'origin_rejected','message':'请求来源无效'}},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        return JSONResponse({'detail':{'code':'invalid_request','message':'请求字段不符合约定',
            'fields':[{'location':list(e['loc']),'type':e['type']} for e in exc.errors()]}},status_code=422)

    @app.get('/health')
    def health():return {'status':'ok','mode':'mock','synthetic_data':True}

    @app.post('/api/auth/login')
    def login_route(body:LoginInput,request:Request,response:Response,db=Depends(get_db)):
        key=request.client.host if request.client else 'local';now=time.monotonic()
        while attempts[key] and attempts[key][0]<now-60:attempts[key].popleft()
        if len(attempts[key])>=10:raise HTTPException(429,detail={'code':'login_throttled','message':'尝试过于频繁，请稍后再试'})
        attempts[key].append(now)
        user,session,token=login(db,body.username,body.password)
        attempts[key].clear()
        old=request.cookies.get(COOKIE)
        if old:
            previous=db.scalar(select(m.DemoSession).where(m.DemoSession.token_hash==digest(old)))
            if previous:db.delete(previous);db.commit()
        response.set_cookie(COOKIE,token,httponly=True,samesite='strict',secure=False,
                            max_age=settings.session_ttl_seconds,path='/')
        return {'user':user_payload(db,user),'csrf_token':session.csrf_token}

    @app.get('/api/auth/session')
    def session_route(request:Request,user=Depends(require_user),db=Depends(get_db)):
        return {'user':user_payload(db,user),'csrf_token':request.state.demo_session.csrf_token}

    @app.post('/api/auth/logout')
    def logout_route(request:Request,response:Response,user=Depends(require_csrf),db=Depends(get_db)):
        db.delete(request.state.demo_session);audit(db,user,'logout');db.commit()
        response.delete_cookie(COOKIE,path='/')
        return {'logged_out':True}

    @app.get('/api/cases')
    def list_cases(user=Depends(require_user),db=Depends(get_db)):
        require_permission(db,user,'exception.view')
        cases=db.scalars(scoped_cases(db,user).order_by(m.ExceptionCase.id)).all()
        return {'cases':[case_payload(db,c) for c in cases],'total':len(cases)}

    @app.get('/api/cases/{case_id}')
    def case_detail(case_id:int,user=Depends(require_user),db=Depends(get_db)):
        case=visible_case(db,user,case_id)
        evidence=db.scalar(select(m.ExceptionEvidence).where(m.ExceptionEvidence.case_id==case.id,m.ExceptionEvidence.evidence_version==case.evidence_version))
        projected,budget=prepare_exception_evidence(evidence.data_json,domain='inventory') if evidence else ({},{})
        jobs=db.scalars(select(m.ExceptionDiagnosisJob).where(m.ExceptionDiagnosisJob.case_id==case.id).order_by(m.ExceptionDiagnosisJob.id.desc()).limit(20)).all()
        diagnosis=db.scalar(select(m.ExceptionDiagnosis).where(m.ExceptionDiagnosis.case_id==case.id).order_by(m.ExceptionDiagnosis.id.desc()).limit(1))
        info=case_payload(db,case)
        result=None if not diagnosis else {'id':diagnosis.id,'job_id':diagnosis.job_id,'summary':diagnosis.summary,
            'root_cause_code':diagnosis.root_cause_code,'confidence':diagnosis.confidence,'disposition':diagnosis.disposition,
            'evidence_refs':diagnosis.evidence_refs_json,'impact':diagnosis.impact_json,'recommended_steps':diagnosis.recommended_steps_json,
            'missing_evidence':diagnosis.missing_evidence_json,'model':diagnosis.model_name,'evidence_version':diagnosis.evidence_version,
            'current':diagnosis.evidence_version==case.evidence_version and not info['source_changed']}
        events=db.scalars(select(m.ExceptionEvent).where(m.ExceptionEvent.case_id==case.id).order_by(m.ExceptionEvent.id.desc()).limit(40)).all()
        return {'case':info,'evidence':projected,'input_budget':budget,'diagnosis':result,'jobs':[job_payload(j) for j in jobs],
                'events':[{'id':e.id,'type':e.event_type,'created_at':e.created_at,'detail':e.detail_json} for e in events]}

    @app.post('/api/cases/{case_id}/diagnose')
    def diagnose_route(case_id:int,body:DiagnosisInput,user=Depends(require_csrf),db=Depends(get_db)):
        job,reused=create_diagnosis_job(db,user,case_id,body.expected_evidence_version,body.scenario.value,body.force)
        return {'job':job_payload(job),'reused':reused}

    @app.post('/api/cases/{case_id}/recheck')
    def recheck_route(case_id:int,user=Depends(require_csrf),db=Depends(get_db)):
        require_permission(db,user,'exception.diagnose')
        acquire_exception_case_mutation_lock(db)
        visible_case(db,user,case_id)
        case=db.scalar(select(m.ExceptionCase).where(m.ExceptionCase.id==case_id).with_for_update())
        active=refresh_inventory_case(db,case)
        visible_case(db,user,case_id)
        audit(db,user,'rule_rechecked',case.id,{'still_anomalous':active});db.commit()
        return {'case':case_payload(db,case),'still_anomalous':active}

    @app.get('/api/jobs/{job_id}')
    def job_detail(job_id:int,user=Depends(require_user),db=Depends(get_db)):
        require_permission(db,user,'exception.view')
        visible_ids=scoped_cases(db,user).with_only_columns(m.ExceptionCase.id)
        job=db.scalar(select(m.ExceptionDiagnosisJob).where(m.ExceptionDiagnosisJob.id==job_id,m.ExceptionDiagnosisJob.case_id.in_(visible_ids)))
        if not job:raise HTTPException(404,detail={'code':'job_not_found','message':'任务不存在或不可见'})
        return {'job':job_payload(job)}

    @app.get('/api/audit')
    def audit_route(user=Depends(require_user),db=Depends(get_db)):
        require_permission(db,user,'exception.manage')
        rows=db.scalars(select(m.AuditLog).order_by(m.AuditLog.id.desc()).limit(50)).all()
        return {'items':[{'id':r.id,'action':r.action_type,'actor_id':r.user_id,'case_id':r.resource_id,'details':r.after_data} for r in rows]}

    web=Path(__file__).resolve().parents[1]/'web'
    app.mount('/',StaticFiles(directory=web,html=True),name='demo-ui')
    return app


app=create_app()
