from sqlalchemy import select, func
from app import models as m
from app.core.database import SessionLocal
from app.services.auth_service import COOKIE
from app.services.exception_task_service import run_one_diagnosis_job
from conftest import enqueue


def sign_in(client,name):
    result=client.post('/api/auth/login',json={'username':name,'password':'LocalDemo-2026!'})
    assert result.status_code==200
    client.headers['X-CSRF-Token']=result.json()['csrf_token']
    return result


def test_login_cookie_hash_and_anonymous_rejection(client):
    assert client.get('/api/cases').status_code==401
    result=sign_in(client,'demo_admin')
    assert 'HttpOnly' in result.headers['set-cookie'] and 'SameSite=strict' in result.headers['set-cookie']
    token=client.cookies.get(COOKIE)
    with SessionLocal() as db:
        record=db.scalar(select(m.DemoSession))
        assert record.token_hash!=token and len(record.token_hash)==64
    assert client.get('/api/cases').json()['total']==6


def test_case_and_job_scope_are_enforced_in_api(admin):
    west=enqueue(admin,case_id=5)
    sign_in(admin,'demo_east')
    payload=admin.get('/api/cases').json()
    assert payload['total']==4
    assert {r['warehouse'] for r in payload['cases']}=={'演示东仓'}
    assert admin.get('/api/cases/5').status_code==404
    assert admin.get(f"/api/jobs/{west['id']}").status_code==404
    assert admin.post('/api/cases/5/diagnose',json={'expected_evidence_version':'unseen','scenario':'success'}).status_code==404
    assert admin.get('/api/audit').status_code==403


def test_read_only_user_cannot_diagnose_or_recheck(client):
    sign_in(client,'demo_viewer')
    version=client.get('/api/cases/1').json()['case']['evidence_version']
    assert client.post('/api/cases/1/diagnose',json={'expected_evidence_version':version}).status_code==403
    assert client.post('/api/cases/1/recheck',json={}).status_code==403
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(m.ExceptionDiagnosisJob))==0


def test_csrf_and_foreign_origin_rejected(admin):
    assert admin.post('/api/auth/logout',headers={'X-CSRF-Token':''}).status_code==403
    assert admin.post('/api/cases/1/recheck',headers={'Origin':'https://foreign.example'}).status_code==403


def test_unknown_fields_and_invalid_mode_do_not_create_jobs(admin):
    version=admin.get('/api/cases/1').json()['case']['evidence_version']
    for extras in ({'user_id':1},{'warehouse':'演示西仓'},{'scenario':'not_a_scenario'},{'force':'true'}):
        response=admin.post('/api/cases/1/diagnose',json={'expected_evidence_version':version,**extras})
        assert response.status_code==422,response.text
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(m.ExceptionDiagnosisJob))==0


def test_invalid_credentials_and_validation_never_echo_password(client):
    secret='wrong-demo-password'
    response=client.post('/api/auth/login',json={'username':'demo_admin','password':secret})
    assert response.status_code==401 and secret not in response.text
    response=client.post('/api/auth/login',json={'username':'demo_admin','password':'x'*201})
    assert response.status_code==422 and 'x'*201 not in response.text


def test_permission_override_revokes_existing_session(client):
    sign_in(client,'demo_east')
    with SessionLocal() as db,db.begin():
        permission=db.scalar(select(m.Permission).where(m.Permission.permission_code=='exception.view'))
        db.add(m.UserPermissionOverride(user_id=2,permission_id=permission.id,effect='deny'))
    assert client.get('/api/cases').status_code==403
    assert client.get('/api/cases/1').status_code==403


def test_disabled_account_invalidates_existing_session(admin):
    with SessionLocal() as db,db.begin():db.get(m.User,1).is_active=False
    assert admin.get('/api/cases').status_code==401


def test_logout_revokes_captured_cookie(admin):
    cookie=admin.cookies.get(COOKIE)
    assert admin.post('/api/auth/logout').status_code==200
    assert admin.get('/api/cases',headers={'Cookie':f'{COOKIE}={cookie}'}).status_code==401


def test_unknown_scope_mode_and_authoritative_warehouse_fail_closed(client):
    sign_in(client,'demo_east')
    with SessionLocal() as db,db.begin():db.get(m.DataScopeRule,2).scope_mode='unexpected'
    assert client.get('/api/cases').json()['total']==0
    with SessionLocal() as db,db.begin():
        db.get(m.DataScopeRule,2).scope_mode='warehouse'
        db.get(m.InventorySnapshot,2).warehouse_name='演示西仓'
    assert client.get('/api/cases').json()['total']==3
    assert client.get('/api/cases/1').status_code==404


def test_normal_end_to_end_api_worker_result_and_audit(admin):
    job=enqueue(admin)
    assert job['status']=='queued'
    assert run_one_diagnosis_job(worker_id='normal-worker')=='completed'
    detail=admin.get('/api/cases/1').json()
    assert detail['diagnosis']['current'] and detail['diagnosis']['model']=='mock-fixed-v1'
    assert set(detail['diagnosis']['evidence_refs'])<=set(detail['evidence']['canonical_evidence_refs'])
    assert detail['jobs'][0]['status']=='completed' and detail['jobs'][0]['generation']==1
    assert any(e['type']=='diagnosed' for e in detail['events'])
    assert any(a['action']=='diagnosis_requested' for a in admin.get('/api/audit').json()['items'])
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(m.ExceptionNotification))==1
