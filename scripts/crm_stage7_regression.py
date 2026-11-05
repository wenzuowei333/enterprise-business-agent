#!/usr/bin/env python3
"""CRM stage 7 automated regression checks.

The script is intentionally lightweight enough to run before every deploy:

- build / compile / audit checks
- CRM naming and navigation source contract
- deployed SPA route smoke checks
- deployed React asset naming contract
- health and protected-route checks
- optional authenticated API smoke checks

Authentication can be provided with PROJECT_BASE_REGRESSION_USERNAME and
PROJECT_BASE_REGRESSION_PASSWORD. On a deployed server, --seed-temp-user creates
a short-lived admin user for the check and deletes it at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


CURRENT_CRM_TERMS = [
    "用来看：客户全景",
    "用来干具体的事：业务执行",
    "看清楚我该干什么：我的工作",
    "关联客户底盘",
    "跟进记录",
    "数据中心",
    "客户开发",
    "项目申请",
    "项目列表",
    "任务明细",
    "待支持填写",
    "今日待办",
    "待我补充",
    "执行中心",
    "我的提交",
    "保存经营资料",
]
FORBIDDEN_APP_TERMS = [
    'label: "项目台账"',
    'label: "提交中心"',
    'label: "客户基本资料填写"',
    'label: "客户经营资料填写"',
    'label: "独立经营分析"',
    'label: "独立复盘中心"',
]
SPA_ROUTES = [
    "/crm",
    "/crm/my-work",
    "/crm/submissions",
    "/crm/work",
    "/crm/projects",
    "/crm/tasks?scope=open",
    "/crm/followups?q=NO_STAGE7_EMPTY_FOLLOWUP",
    "/crm/data",
    "/crm/leads",
    "/crm/customers?q=NO_STAGE7_EMPTY_CUSTOMER",
    # Legacy deep links must continue to return the SPA shell so the client can
    # normalize them to the frozen stage 1 routes without producing a 404.
    "/crm/insights",
    "/crm/reviews",
    "/crm/followup-entry",
    "/crm/customer-profile-submit",
    "/crm/business-profile-submit",
    "/master-data?kind=customers",
]


@dataclass
class HttpResult:
    status: int
    body: Any
    headers: dict[str, str]


class RegressionError(AssertionError):
    pass


class ApiClient:
    def __init__(self, base_web_url: str, api_prefix: str = "/api/v1") -> None:
        self.base_web_url = base_web_url.rstrip("/")
        self.base_api_url = f"{self.base_web_url}{api_prefix.rstrip('/')}"

    def url(self, path: str, *, api: bool = True) -> str:
        base = self.base_api_url if api else self.base_web_url
        return f"{base}{path if path.startswith('/') else f'/{path}'}"

    def request(
        self,
        method: str,
        path: str,
        *,
        api: bool = True,
        token: str | None = None,
        payload: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> HttpResult:
        expected = expected or {200}
        headers = {"Accept": "application/json" if api else "text/html,application/xhtml+xml,*/*"}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(self.url(path, api=api), data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                raw = response.read().decode("utf-8", errors="replace")
                body: Any
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    body = json.loads(raw) if raw else None
                else:
                    body = raw
                result = HttpResult(response.status, body, {key.lower(): value for key, value in response.headers.items()})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else raw
            except json.JSONDecodeError:
                body = raw
            result = HttpResult(exc.code, body, {key.lower(): value for key, value in exc.headers.items()})
        if result.status not in expected:
            raise RegressionError(f"{method} {path} expected {sorted(expected)}, got {result.status}: {result.body}")
        return result

    def login(self, username: str, password: str) -> str:
        response = self.request("POST", "/auth/login", payload={"username": username, "password": password}, expected={200})
        token = response.body.get("access_token") if isinstance(response.body, dict) else None
        if not token:
            raise RegressionError(f"Login for {username} did not return access_token")
        return str(token)


def run_command(command: list[str], *, cwd: Path) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RegressionError(
            f"Command failed: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout[-3000:]}\n"
            f"stderr:\n{completed.stderr[-3000:]}"
        )
    return {"command": " ".join(command), "duration_seconds": round(time.time() - started, 2)}


def check_source_naming() -> dict[str, Any]:
    app_path = ROOT / "frontend" / "src" / "App.tsx"
    text = app_path.read_text(encoding="utf-8")
    missing = [term for term in CURRENT_CRM_TERMS if term not in text]
    forbidden = [term for term in FORBIDDEN_APP_TERMS if term in text]
    if missing or forbidden:
        raise RegressionError(f"CRM naming source contract failed. missing={missing}, forbidden={forbidden}")
    return {"path": str(app_path), "required_terms": len(CURRENT_CRM_TERMS), "forbidden_terms": 0}


def check_spa_routes(client: ApiClient) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for route in SPA_ROUTES:
        response = client.request("GET", route, api=False, expected={200})
        body = response.body if isinstance(response.body, str) else ""
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type or 'id="app"' not in body:
            raise RegressionError(f"SPA route {route} did not return the React app shell")
        results.append({"route": route, "status": response.status})
    return {"routes": results}


def check_remote_asset_naming(client: ApiClient) -> dict[str, Any]:
    html_response = client.request("GET", "/crm", api=False, expected={200})
    html = html_response.body if isinstance(html_response.body, str) else ""
    asset_paths = sorted(set(re.findall(r'src="([^"]+\.js)"', html)))
    if not asset_paths:
        raise RegressionError("No remote React JS asset found from /crm")
    combined = ""
    for asset_path in asset_paths:
        asset_url = urllib.parse.urljoin(f"{client.base_web_url}/", asset_path.lstrip("/"))
        with urllib.request.urlopen(asset_url, timeout=25) as response:
            combined += response.read().decode("utf-8", errors="replace")
    missing = [term for term in CURRENT_CRM_TERMS if term not in combined]
    forbidden = [term for term in FORBIDDEN_APP_TERMS if term in combined]
    if missing or forbidden:
        raise RegressionError(f"Remote asset naming contract failed. missing={missing}, forbidden={forbidden}")
    return {"assets": asset_paths, "required_terms": len(CURRENT_CRM_TERMS), "forbidden_terms": 0}


def check_public_api(client: ApiClient) -> dict[str, Any]:
    health = client.request("GET", "/health").body
    db = client.request("GET", "/health/db").body
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise RegressionError(f"Health check failed: {health}")
    if not isinstance(db, dict) or db.get("database") != "ok":
        raise RegressionError(f"DB health check failed: {db}")
    protected = client.request("GET", "/crm/summary", expected={401, 403})
    return {"health": health, "db": db, "protected_crm_summary_status": protected.status}


def generate_password(prefix: str) -> str:
    alphabet = string.ascii_letters + string.digits
    return f"{prefix}_" + "".join(secrets.choice(alphabet) for _ in range(24)) + "!"


def create_temp_user(prefix: str) -> tuple[str, str, dict[str, int]]:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.models import EmployeeProfile, Role, User

    username = f"{prefix.lower()}_admin"
    employee_code = f"{prefix}_ADMIN"
    password = generate_password(prefix)
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.role_code == "admin"))
        if role is None:
            raise RegressionError("Cannot seed temp regression user: role admin is missing")
        employee = EmployeeProfile(
            employee_code=employee_code,
            employee_name="阶段7自动回归",
            department="自动化回归",
            position="admin",
            role_code="admin",
            status="active",
        )
        db.add(employee)
        db.flush()
        user = User(
            username=username,
            password_hash=hash_password(password),
            real_name="阶段7自动回归",
            employee_code=employee_code,
            role="admin",
            is_active=True,
            status="active",
        )
        db.add(user)
        db.flush()
        employee.user_id = user.id
        ids = {"user_id": int(user.id), "employee_id": int(employee.id)}
        db.commit()
    return username, password, ids


def cleanup_temp_user(prefix: str) -> dict[str, int]:
    from sqlalchemy import delete, or_, select

    from app.core.database import SessionLocal
    from app.models import AuditLog, EmployeeProfile, User, UserPermissionOverride, UserStatusHistory

    username = f"{prefix.lower()}_admin"
    employee_code = f"{prefix}_ADMIN"
    with SessionLocal() as db:
        user_ids = list(db.scalars(select(User.id).where(or_(User.username == username, User.employee_code == employee_code))).all())
        db.execute(delete(AuditLog).where(or_(AuditLog.user_id.in_(user_ids or [-1]), AuditLog.resource_id.in_([username, *(str(user_id) for user_id in user_ids)] or ["__none__"]))))
        db.execute(delete(UserPermissionOverride).where(UserPermissionOverride.user_id.in_(user_ids or [-1])))
        db.execute(delete(UserStatusHistory).where(UserStatusHistory.user_id.in_(user_ids or [-1])))
        db.execute(delete(EmployeeProfile).where(EmployeeProfile.employee_code == employee_code))
        db.execute(delete(User).where(User.id.in_(user_ids or [-1])))
        db.commit()
        leftovers = {
            "users": db.scalar(select(User.id).where(or_(User.username == username, User.employee_code == employee_code)).limit(1)) or 0,
            "employees": db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.employee_code == employee_code).limit(1)) or 0,
        }
    return {key: int(value) for key, value in leftovers.items()}


def check_authenticated_api(client: ApiClient, username: str, password: str) -> dict[str, Any]:
    token = client.login(username, password)
    me = client.request("GET", "/auth/me", token=token).body
    permissions = client.request("GET", "/auth/my-permissions", token=token).body
    if not isinstance(permissions, list) or "crm_project.view" not in permissions:
        raise RegressionError("Authenticated regression user cannot view CRM projects")

    today = datetime.now().date().isoformat()
    checks = {
        "me": {"username": me.get("username") if isinstance(me, dict) else None},
        "permission_count": len(permissions),
        "capabilities": client.request("GET", "/crm/security/capabilities", token=token).body,
        "summary": client.request("GET", "/crm/summary", token=token).body,
        "projects": client.request("GET", "/crm/projects/page?limit=1&offset=0", token=token).body,
        "tasks": client.request("GET", "/crm/tasks/page?limit=1&offset=0", token=token).body,
        "followups": client.request("GET", "/crm/followups/page?limit=1&offset=0", token=token).body,
        "daily": client.request("GET", f"/crm/daily-summary?date={today}&limit=1", token=token).body,
        "governance_empty": client.request("GET", "/crm/governance/test-projects?marker=NO_STAGE7_REGRESSION&include_cancelled=true&limit=1&offset=0", token=token).body,
        "approvals": client.request("GET", "/approvals/page?limit=1&offset=0", token=token).body,
        "work_items": client.request("GET", "/work-items/page?limit=1&offset=0", token=token).body,
    }
    return {
        "username": checks["me"]["username"],
        "permission_count": checks["permission_count"],
        "summary_keys": sorted(checks["summary"].keys()) if isinstance(checks["summary"], dict) else [],
        "project_total": checks["projects"].get("total") if isinstance(checks["projects"], dict) else None,
        "task_total": checks["tasks"].get("total") if isinstance(checks["tasks"], dict) else None,
        "followup_total": checks["followups"].get("total") if isinstance(checks["followups"], dict) else None,
        "approval_total": checks["approvals"].get("total") if isinstance(checks["approvals"], dict) else None,
        "work_item_total": checks["work_items"].get("total") if isinstance(checks["work_items"], dict) else None,
        "governance_empty_total": checks["governance_empty"].get("total") if isinstance(checks["governance_empty"], dict) else None,
    }


def run_regression(args: argparse.Namespace) -> dict[str, Any]:
    client = ApiClient(args.base_web_url, args.api_prefix)
    started = time.time()
    result: dict[str, Any] = {
        "status": "passed",
        "base_web_url": args.base_web_url,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "checks": {},
    }

    if not args.skip_build:
        result["checks"]["frontend_build"] = run_command(["npm", "run", "build"], cwd=ROOT / "frontend")
    if not args.skip_compile:
        result["checks"]["backend_compile"] = run_command(["python3", "-m", "compileall", "backend/app"], cwd=ROOT)
    if not args.skip_audit:
        result["checks"]["npm_audit"] = run_command(["npm", "audit", "--omit=dev"], cwd=ROOT / "frontend")

    result["checks"]["source_naming"] = check_source_naming()
    result["checks"]["spa_routes"] = check_spa_routes(client)
    result["checks"]["remote_asset_naming"] = check_remote_asset_naming(client)
    result["checks"]["public_api"] = check_public_api(client)

    temp_prefix: str | None = None
    username = args.username or os.environ.get("PROJECT_BASE_REGRESSION_USERNAME")
    password = args.password or os.environ.get("PROJECT_BASE_REGRESSION_PASSWORD")
    if args.seed_temp_user:
        temp_prefix = f"STAGE7_REG_{int(time.time())}"
        username, password, ids = create_temp_user(temp_prefix)
        result["checks"]["temp_user"] = {"created": True, **ids}

    try:
        if args.skip_auth:
            result["checks"]["authenticated_api"] = {"skipped": "skip_auth enabled"}
        elif username and password:
            result["checks"]["authenticated_api"] = check_authenticated_api(client, username, password)
        else:
            result["checks"]["authenticated_api"] = {"skipped": "no username/password provided"}
    finally:
        if temp_prefix:
            leftovers = cleanup_temp_user(temp_prefix)
            result["checks"]["temp_user_cleanup"] = leftovers
            if any(leftovers.values()):
                raise RegressionError(f"Temporary regression user cleanup failed: {leftovers}")

    result["duration_seconds"] = round(time.time() - started, 2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CRM stage 7 automated regression checks.")
    parser.add_argument("--base-web-url", default=os.environ.get("PROJECT_BASE_REGRESSION_BASE_URL", "http://127.0.0.1:8082"))
    parser.add_argument("--api-prefix", default="/api/v1")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--seed-temp-user", action="store_true", help="Create and clean up a temporary admin user through the configured DB.")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--skip-auth", action="store_true")
    args = parser.parse_args()

    try:
        print(json.dumps(run_regression(args), ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
