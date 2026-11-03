"""Run only dedicated demo migration, seed and data checks."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--export-only', action='store_true')
    args=parser.parse_args()
    env=os.environ.copy()
    env['PYTHONPATH']=os.pathsep.join([str(ROOT/'backend'),str(ROOT)])
    env['PYTHONDONTWRITEBYTECODE']='1'
    if args.export_only:
        subprocess.run([sys.executable,'-m','demo.seed','--export-only'],cwd=ROOT,env=env,check=True)
        return
    subprocess.run([sys.executable,'-m','alembic','-c','backend/alembic.ini','upgrade','head'],cwd=ROOT,env=env,check=True)
    subprocess.run([sys.executable,'-m','demo.seed'],cwd=ROOT,env=env,check=True)
    subprocess.run([sys.executable,'-m','demo.verify_data'],cwd=ROOT,env=env,check=True)


if __name__=='__main__':
    main()
