"""Run against disposable PostgreSQL, never the interactive demo database."""
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    env=os.environ.copy()
    env.update({'DATABASE_URL':'postgresql+psycopg://portfolio_demo:local-demo-only@127.0.0.1:25435/inventory_demo',
                'SHOWCASE_TEST_DATABASE':'1','PYTHONPATH':os.pathsep.join([str(ROOT/'backend'),str(ROOT),env.get('PYTHONPATH','')]),
                'PYTHONDONTWRITEBYTECODE':'1','ENVIRONMENT':'demo','AI_MODE':'mock',
                'EXCEPTION_JOB_LEASE_SECONDS':'0.9','EXCEPTION_WORKER_HEARTBEAT_SECONDS':'0.1',
                'PROVIDER_TIMEOUT_SECONDS':'3','EXCEPTION_JOB_MAX_ATTEMPTS':'2'})
    subprocess.run(['docker','compose','--profile','checks','up','-d','test-postgres','--wait'],cwd=ROOT,check=True)
    subprocess.run([sys.executable,'-m','alembic','-c','backend/alembic.ini','upgrade','head'],cwd=ROOT,env=env,check=True)
    (ROOT/'runtime').mkdir(exist_ok=True)
    args=[sys.executable,'-m','pytest','tests','-q','--junitxml=runtime/validation.xml',*sys.argv[1:]]
    raise SystemExit(subprocess.run(args,cwd=ROOT,env=env).returncode)


if __name__=='__main__':main()
