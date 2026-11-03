"""CI and local acceptance entry; run only in an isolated checkout/project.

Dependencies/browser binaries are installed before this command. Build/pulls may
use network; Python tests, browser requests and running containers are isolated.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
CREATIVE=(ROOT/"frontend/package.json").exists()
FOLDER=ROOT/"runtime/ci"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--fresh-data-check",action="store_true",help="Requires a new Compose project with no containers or volumes")
    parser.add_argument("--url",default="http://127.0.0.1:"+("18140" if CREATIVE else "18130"))
    args=parser.parse_args()
    FOLDER.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env.setdefault("COMPOSE_FILE",os.pathsep.join([str(ROOT/"docker-compose.yml"),str(ROOT/"ci/compose.offline.yml")]))
    steps=[]
    def run(label,command,*,active_env=None,cwd=ROOT):
        started=time.monotonic()
        result=subprocess.run(command,cwd=cwd,env=active_env or env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (FOLDER/(label+".log")).write_text(result.stdout)
        steps.append({"step":label,"exit_code":result.returncode,"duration_seconds":round(time.monotonic()-started,3)})
        print(label+": "+("passed" if result.returncode==0 else "FAILED"),flush=True)
        if result.returncode:
            print(result.stdout[-10000:],flush=True)
            raise RuntimeError(label+" failed")
        return result.stdout
    compose=["docker","compose"]
    project=None
    status="failed"
    try:
        config=json.loads(run("compose-config",compose+["config","--format","json"]))
        project=config["name"]
        if args.fresh_data_check:
            assert not run("existing-containers",compose+["ps","-aq"]).strip(),"Fresh-data check requires a new Compose project"
            assert not run("existing-volumes",["docker","volume","ls","-q","--filter","label=com.docker.compose.project="+project]).strip(),"Fresh-data check must not delete an existing data volume"
        app_services=["api","worker"]+(["recovery"] if CREATIVE else [])+["api-ingress"]
        run("build-and-start",compose+["--profile","app","up","-d","--build",*app_services,"--wait"])
        internal=run("runtime-network",["docker","network","inspect",project+"_default","--format","{{.Internal}}"]).strip()
        assert internal=="true","Runtime network must be internal"
        run("container-egress-probe",compose+["exec","-T","api","python","-c",
            "import socket; s=socket.socket(); s.settimeout(1); result=s.connect_ex(('192.0.2.1',443)); assert result != 0; print('external TCP blocked; result='+str(result))"])
        if args.fresh_data_check:
            def data_check(label):
                output=run(label,compose+["exec","-T","api","python","-m","demo.verify_data"])
                return json.loads(output.strip().splitlines()[-1])
            first=data_check("initial-data")
            run("repeat-seed",compose+["exec","-T","api","python","-m","demo.seed"])
            second=data_check("repeat-seed-data")
            assert first["normalized_data_sha256"]==second["normalized_data_sha256"]
            # Only allowed after proving this Compose project had no preexisting volumes/containers.
            run("remove-fresh-project",compose+["--profile","app","down","-v"])
            run("rebuild-empty-data",compose+["--profile","app","up","-d","--no-build",*app_services,"--wait"])
            rebuilt=data_check("rebuilt-data")
            assert first["normalized_data_sha256"]==rebuilt["normalized_data_sha256"]
            (FOLDER/"data-rebuild.json").write_text(json.dumps({"status":"passed","new_project_only":True,"repeat_seed_same_digest":True,"fresh_volume_rebuild_same_digest":True,"normalized_data_sha256":first["normalized_data_sha256"],"tables":first["tables"]},indent=2)+"\n")
        test_env=env.copy()
        test_env.update(SHOWCASE_LOCAL_ONLY="1",NETWORK_AUDIT_FILE=str(FOLDER/"network-denials.ndjson"),
            PYTHONPATH=os.pathsep.join([str(ROOT/"ci/network"),str(ROOT/"backend"),str(ROOT)]),PYTHONDONTWRITEBYTECODE="1")
        (FOLDER/"network-denials.ndjson").write_text("")
        run("python-network-policy",[sys.executable,"ci/network_probe.py"],active_env=test_env)
        test_services=["test-postgres","test-postgres-ingress"]+(["test-redis","test-redis-ingress"] if CREATIVE else [])
        run("start-test-ingress",compose+["--profile","checks","up","-d",*test_services,"--wait"])
        run("backend-tests",[sys.executable,"demo/run_checks.py"],active_env=test_env)
        if CREATIVE:
            frontend=ROOT/"frontend"
            run("frontend-tests",["npm","test","--","--reporter=junit","--outputFile=../runtime/frontend-validation.xml"],cwd=frontend)
            run("frontend-typecheck",["npm","run","typecheck"],cwd=frontend)
            browser_env=env.copy();browser_env["E2E_BASE_URL"]=args.url
            browser_env.setdefault("E2E_BROWSER_CHANNEL","chrome" if sys.platform=="darwin" else "chromium")
            run("browser-tests",["npm","run","test:e2e"],cwd=frontend,active_env=browser_env)
        else:
            run("browser-tests",[sys.executable,"demo/browser_smoke.py","--url",args.url],active_env=test_env)
        # The self-test produced 3 known denials; successful tests must add none.
        audit=(FOLDER/"network-denials.ndjson").read_text().splitlines()
        assert len(audit)==3,"Unexpected denied external network attempt in tests"
        status="passed"
    finally:
        execution={"status":status,"scope":"github_actions_clean_checkout" if os.environ.get("GITHUB_ACTIONS")=="true" else "local_CI_entry_from_clean_checkout","finished_at_utc":datetime.now(timezone.utc).isoformat(),"python":sys.version.split()[0],"steps":steps,"fresh_data_check_requested":args.fresh_data_check,"runtime_network_internal":True if status=="passed" else None,"hosted_github_actions_run":os.environ.get("GITHUB_ACTIONS")=="true"}
        (FOLDER/"execution.json").write_text(json.dumps(execution,indent=2)+"\n")
        from collect_results import collect
        collect()
    if status!="passed":raise SystemExit(1)


if __name__=="__main__":main()
