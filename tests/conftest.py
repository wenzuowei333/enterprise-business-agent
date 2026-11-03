"""All tests use the dedicated, disposable PostgreSQL service on 25435."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
from sqlalchemy.engine import make_url

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT)]
url=make_url(os.environ.get('DATABASE_URL',''))
if os.environ.get('SHOWCASE_TEST_DATABASE')!='1' or url.host!='127.0.0.1' or url.port!=25435 or url.database!='inventory_demo':
    raise RuntimeError('Use demo/run_checks.py: tests may only reset the dedicated local port 25435 database')

from app import models as m
from app.core.database import Base, SessionLocal
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_database():
    with SessionLocal() as db:
        names=','.join(db.get_bind().dialect.identifier_preparer.quote(t.name) for t in Base.metadata.sorted_tables)
        db.connection().exec_driver_sql('TRUNCATE '+names+' RESTART IDENTITY CASCADE')
        db.commit()
    subprocess.run([sys.executable,'-m','demo.seed'],cwd=ROOT,env=os.environ.copy(),check=True,capture_output=True,text=True)


@pytest.fixture
def client():
    with TestClient(create_app()) as c:yield c


@pytest.fixture
def admin(client):
    result=client.post('/api/auth/login',json={'username':'demo_admin','password':'LocalDemo-2026!'})
    assert result.status_code==200,result.text
    client.headers['X-CSRF-Token']=result.json()['csrf_token']
    return client


def enqueue(client,case_id=1,scenario='success',force=False):
    case=client.get(f'/api/cases/{case_id}').json()['case']
    response=client.post(f'/api/cases/{case_id}/diagnose',json={
        'expected_evidence_version':case['evidence_version'],'scenario':scenario,'force':force})
    assert response.status_code==200,response.text
    return response.json()['job']
