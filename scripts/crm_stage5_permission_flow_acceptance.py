#!/usr/bin/env python3
"""CRM stage 5 permission and flow acceptance checks.

Runs against a deployed API and validates the current delivery rules:

- admin is the fixed project approval handler and is displayed as 施总.
- 李乐 is the fixed followup review handler.
- 姚丽莉 can create CRM project approval drafts.
- Non-handler approvers cannot approve another handler's approval.
- Project approval creates project and task records.
- Followup approval creates formal followup records and support work items.

The script creates temporary customer/task/project records and deletes them
after the check. It does not need production passwords.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass
class ApiResponse:
    status: int
    body: Any


@dataclass
class AcceptanceState:
    prefix: str
    customer_code: str
    temp_user_ids: list[int] = field(default_factory=list)
    approval_ids: list[int] = field(default_factory=list)
    project_ids: list[int] = field(default_factory=list)
    task_ids: list[int] = field(default_factory=list)
    followup_ids: list[int] = field(default_factory=list)
    work_item_ids: list[int] = field(default_factory=list)


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> ApiResponse:
        expected = expected or {200}
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                raw = response.read().decode("utf-8")
                body = json.loads(raw) if raw else None
                result = ApiResponse(response.status, body)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                body = json.loads(raw) if raw else raw
            except json.JSONDecodeError:
                body = raw
            result = ApiResponse(exc.code, body)
        if result.status not in expected:
            raise AssertionError(f"{method} {path} expected {sorted(expected)}, got {result.status}: {result.body}")
        return result


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def business_date(value: datetime) -> str:
    return (value + timedelta(hours=8)).date().isoformat()


def now_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_token(username: str) -> str:
    from app.core.security import create_access_token

    return create_access_token(username)


def get_required_user(db: Any, username: str | None = None, real_name: str | None = None) -> Any:
    from sqlalchemy import or_, select

    from app.models import User

    conditions = []
    if username:
        conditions.append(User.username == username)
    if real_name:
        conditions.append(User.real_name == real_name)
    user = db.scalar(select(User).where(or_(*conditions), User.status == "active", User.is_active.is_(True)))
    label = username or real_name
    assert_true(user is not None, f"Required active user missing: {label}")
    return user


def permission_codes(db: Any, user: Any) -> set[str]:
    from app.services.permission_service import get_final_permission_codes

    return set(get_final_permission_codes(db, user))


def seed_temp_data(db: Any, state: AcceptanceState) -> dict[str, int]:
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models import CustomerMaster, EmployeeProfile, Role, User

    role = db.scalar(select(Role).where(Role.role_code == "salesperson"))
    assert_true(role is not None, "Missing salesperson role")

    employee = EmployeeProfile(
        employee_code=f"{state.prefix}_SALES",
        employee_name=f"{state.prefix} 一线执行",
        department="CRM 验收",
        position="salesperson",
        role_code="salesperson",
        status="active",
    )
    db.add(employee)
    db.flush()
    user = User(
        username=f"{state.prefix.lower()}_sales",
        password_hash=hash_password(f"{state.prefix}_unused_password"),
        real_name=f"{state.prefix} 一线执行",
        employee_code=employee.employee_code,
        role="salesperson",
        is_active=True,
        status="active",
    )
    db.add(user)
    db.flush()
    employee.user_id = user.id
    state.temp_user_ids.append(int(user.id))

    customer = CustomerMaster(
        customer_code=state.customer_code,
        customer_name=f"{state.prefix} 客户",
        customer_short_name="权限流程验收客户",
        customer_type="终端",
        region="验收区域",
        salesperson_employee_code=employee.employee_code,
        salesperson_name=employee.employee_name,
        contact_name="验收联系人",
        contact_phone="00000000000",
        status="active",
        source="crm_stage5_acceptance",
    )
    db.add(customer)
    db.commit()
    return {"sales_user_id": int(user.id)}


def cleanup(db: Any, state: AcceptanceState) -> dict[str, int]:
    from sqlalchemy import delete, or_, select

    from app.models import (
        ApprovalAttachment,
        ApprovalEvent,
        ApprovalInstance,
        AuditLog,
        CrmFollowup,
        CrmProject,
        CrmProjectCustomerTask,
        CustomerMaster,
        EmployeeProfile,
        User,
        WorkItem,
    )

    prefix = state.prefix
    project_ids = list(db.scalars(select(CrmProject.id).where(CrmProject.project_code.like(f"{prefix}%"))).all())
    task_ids = list(
        db.scalars(
            select(CrmProjectCustomerTask.id).where(
                or_(
                    CrmProjectCustomerTask.task_code.like(f"{prefix}%"),
                    CrmProjectCustomerTask.project_id.in_(project_ids or [-1]),
                    CrmProjectCustomerTask.customer_code == state.customer_code,
                )
            )
        ).all()
    )
    followup_ids = list(
        db.scalars(
            select(CrmFollowup.id).where(
                or_(
                    CrmFollowup.followup_no.like(f"{prefix}%"),
                    CrmFollowup.project_id.in_(project_ids or [-1]),
                    CrmFollowup.task_id.in_(task_ids or [-1]),
                    CrmFollowup.customer_code == state.customer_code,
                )
            )
        ).all()
    )
    approval_ids = list(
        db.scalars(
            select(ApprovalInstance.id).where(
                or_(
                    ApprovalInstance.id.in_(state.approval_ids or [-1]),
                    ApprovalInstance.title.like(f"{prefix}%"),
                    ApprovalInstance.resource_id.in_([str(project_id) for project_id in project_ids] or ["__none__"]),
                )
            )
        ).all()
    )
    work_item_ids = list(
        db.scalars(
            select(WorkItem.id).where(
                or_(
                    WorkItem.project_id.in_(project_ids or [-1]),
                    WorkItem.customer_code == state.customer_code,
                )
            )
        ).all()
    )

    db.execute(delete(ApprovalAttachment).where(ApprovalAttachment.approval_id.in_(approval_ids or [-1])))
    db.execute(delete(ApprovalEvent).where(ApprovalEvent.approval_id.in_(approval_ids or [-1])))
    db.execute(delete(WorkItem).where(WorkItem.id.in_(work_item_ids or [-1])))
    db.execute(delete(CrmFollowup).where(CrmFollowup.id.in_(followup_ids or [-1])))
    db.execute(delete(CrmProjectCustomerTask).where(CrmProjectCustomerTask.id.in_(task_ids or [-1])))
    db.execute(delete(CrmProject).where(CrmProject.id.in_(project_ids or [-1])))
    db.execute(delete(ApprovalInstance).where(ApprovalInstance.id.in_(approval_ids or [-1])))
    db.execute(delete(CustomerMaster).where(CustomerMaster.customer_code == state.customer_code))
    db.execute(delete(AuditLog).where(AuditLog.resource_id.like(f"%{prefix}%")))
    db.execute(delete(User).where(User.id.in_(state.temp_user_ids or [-1])))
    db.execute(delete(EmployeeProfile).where(EmployeeProfile.employee_code.like(f"{prefix}%")))
    db.commit()

    leftovers = {
        "customers": db.scalar(select(CustomerMaster.id).where(CustomerMaster.customer_code == state.customer_code).limit(1)) or 0,
        "projects": db.scalar(select(CrmProject.id).where(CrmProject.project_code.like(f"{prefix}%")).limit(1)) or 0,
        "tasks": db.scalar(select(CrmProjectCustomerTask.id).where(CrmProjectCustomerTask.task_code.like(f"{prefix}%")).limit(1)) or 0,
        "followups": db.scalar(select(CrmFollowup.id).where(CrmFollowup.followup_no.like(f"{prefix}%")).limit(1)) or 0,
        "work_items": db.scalar(select(WorkItem.id).where(WorkItem.customer_code == state.customer_code).limit(1)) or 0,
        "approvals": db.scalar(select(ApprovalInstance.id).where(ApprovalInstance.title.like(f"{prefix}%")).limit(1)) or 0,
        "users": db.scalar(select(User.id).where(User.id.in_(state.temp_user_ids or [-1])).limit(1)) or 0,
    }
    return {key: int(value) for key, value in leftovers.items()}


def run_acceptance(base_url: str) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import ApprovalInstance

    state = AcceptanceState(prefix=f"STAGE5_{int(time.time())}", customer_code=f"STAGE5_{int(time.time())}_CUST")
    client = ApiClient(base_url)
    checks: dict[str, Any] = {}

    with SessionLocal() as db:
        cleanup(db, state)
        temp = seed_temp_data(db, state)
        try:
            admin = get_required_user(db, username="admin")
            lile = get_required_user(db, username="李乐")
            yaolili = get_required_user(db, real_name="姚丽莉")

            checks["account_contract"] = {
                "admin_display_name": admin.real_name,
                "admin_role": admin.role,
                "lile_role": lile.role,
                "yaolili_username": yaolili.username,
                "yaolili_role": yaolili.role,
            }
            assert_true(admin.real_name == "施总", "admin must display as 施总")
            assert_true(admin.role == "admin", "admin must keep admin role")
            assert_true("approval.approve" in permission_codes(db, admin), "admin must approve project applications")
            assert_true("approval.approve" in permission_codes(db, lile), "李乐 must approve followup facts")
            assert_true("crm_project.create" in permission_codes(db, yaolili), "姚丽莉 must create project applications")

            admin_token = make_token(admin.username)
            lile_token = make_token(lile.username)
            yaolili_token = make_token(yaolili.username)
            sales_user = get_required_user(db, username=f"{state.prefix.lower()}_sales")
            sales_token = make_token(sales_user.username)

            capabilities = {
                "admin": client.request("GET", "/crm/security/capabilities", token=admin_token).body,
                "lile": client.request("GET", "/crm/security/capabilities", token=lile_token).body,
                "yaolili": client.request("GET", "/crm/security/capabilities", token=yaolili_token).body,
                "sales": client.request("GET", "/crm/security/capabilities", token=sales_token).body,
            }
            checks["permission_probe"] = {
                key: {
                    "role_code": value["role_code"],
                    "permission_count": len(value["permission_codes"]),
                }
                for key, value in capabilities.items()
            }

            due_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            project_payload = {
                "title": f"{state.prefix} 项目申请",
                "description": "阶段5权限与流程验收：项目申请固定给施总",
                "current_handler_user_id": int(lile.id),
                "priority": "normal",
                "submit": True,
                "project": {
                    "project_code": f"{state.prefix}_PROJECT",
                    "project_name": f"{state.prefix} 客户推进",
                    "project_type": "权限流程验收",
                    "purpose": "验证固定审批流",
                    "business_line": "crm_stage5",
                    "owner_user_id": int(yaolili.id),
                    "project_manager_user_id": int(yaolili.id),
                    "participant_user_ids": [temp["sales_user_id"]],
                    "start_date": business_date(datetime.now(timezone.utc)),
                    "due_date": business_date(datetime.now(timezone.utc) + timedelta(days=7)),
                    "minimum_action": "提交有效跟进",
                    "closure_standard": "跟进审核通过并生成待支持事项",
                    "status": "submitted",
                    "approval_status": "submitted",
                },
                "tasks": [
                    {
                        "task_code": f"{state.prefix}_TASK",
                        "customer_code": state.customer_code,
                        "executor_user_id": temp["sales_user_id"],
                        "business_issue_point": "阶段5客户任务",
                        "round_target": "验证跟进记录填写独立入口的底层流程",
                        "feedback_due_at": now_iso(due_at),
                        "status": "in_progress",
                    }
                ],
            }
            project_approval = client.request("POST", "/crm/projects/approval-draft", token=yaolili_token, payload=project_payload, expected={201}).body
            state.approval_ids.append(int(project_approval["id"]))
            assert_true(project_approval["current_handler_user_id"] == admin.id, "Project approval must be assigned to admin")

            client.request(
                "POST",
                f"/approvals/{project_approval['id']}/approve",
                token=lile_token,
                payload={"comment": "非处理人尝试审批"},
                expected={403},
            )
            approved_project = client.request(
                "POST",
                f"/approvals/{project_approval['id']}/approve",
                token=admin_token,
                payload={"comment": "阶段5项目审批通过"},
                expected={200},
            ).body
            project_result = approved_project["approval"]["result_json"]
            state.project_ids.append(int(project_result["project_id"]))
            state.task_ids.extend(int(task_id) for task_id in project_result["task_ids"])
            assert_true(state.project_ids and state.task_ids, "Project approval should create project and task")

            followup_payload = {
                "title": f"{state.prefix} 跟进事实",
                "description": "阶段5权限与流程验收：跟进事实固定给李乐",
                "current_handler_user_id": int(admin.id),
                "priority": "high",
                "submit": True,
                "followup": {
                    "followup_no": f"{state.prefix}_FOLLOWUP",
                    "project_id": state.project_ids[0],
                    "task_id": state.task_ids[0],
                    "followup_date": business_date(datetime.now(timezone.utc)),
                    "method": "电话",
                    "frontline_action": "完成阶段5客户跟进",
                    "customer_feedback": "客户需要报价支持",
                    "current_need": "需要主管协同",
                    "need_type": "内部支持",
                    "minimum_action_done": True,
                    "need_support": True,
                    "valid_feedback": True,
                    "review_status": "pending",
                },
            }
            followup_approval = client.request("POST", "/crm/followups/approval-draft", token=sales_token, payload=followup_payload, expected={201}).body
            state.approval_ids.append(int(followup_approval["id"]))
            assert_true(followup_approval["current_handler_user_id"] == lile.id, "Followup approval must be assigned to 李乐")

            client.request(
                "POST",
                f"/approvals/{followup_approval['id']}/approve",
                token=admin_token,
                payload={"comment": "非处理人尝试审核跟进"},
                expected={403},
            )
            approved_followup = client.request(
                "POST",
                f"/approvals/{followup_approval['id']}/approve",
                token=lile_token,
                payload={
                    "comment": "阶段5跟进审核通过",
                    "result_json": {
                        "review_status": "approved",
                        "review_result": "有效",
                        "review_note": "阶段5有效反馈",
                        "valid_feedback": True,
                        "owner_next_status": "继续推进",
                        "owner_next_followup_at": now_iso(datetime.now(timezone.utc) + timedelta(days=1)),
                    },
                },
                expected={200},
            ).body
            followup_result = approved_followup["approval"]["result_json"]
            state.followup_ids.append(int(followup_result["followup_id"]))
            state.work_item_ids.extend(int(item_id) for item_id in followup_result.get("work_item_ids", []))
            assert_true(state.followup_ids, "Followup approval should create formal followup")
            assert_true(state.work_item_ids, "Followup requiring support should create work item")

            context = client.request("GET", f"/context/customers/{urllib.parse.quote(state.customer_code)}", token=yaolili_token).body
            assert_true(context["crm"]["stats"]["project_total"] >= 1, "Customer context should include project")
            assert_true(context["crm"]["stats"]["task_total"] >= 1, "Customer context should include task")
            assert_true(context["crm"]["stats"]["followup_total"] >= 1, "Customer context should include followup")
            assert_true(context["crm"]["stats"]["work_item_open"] >= 1, "Customer context should include support work item")

            final_project_approval = db.get(ApprovalInstance, project_approval["id"])
            final_followup_approval = db.get(ApprovalInstance, followup_approval["id"])
            checks["flow_contract"] = {
                "project_approval_handler": final_project_approval.current_handler_user_id if final_project_approval else None,
                "followup_approval_handler": final_followup_approval.current_handler_user_id if final_followup_approval else None,
                "project_id": state.project_ids[0],
                "task_id": state.task_ids[0],
                "followup_id": state.followup_ids[0],
                "work_item_count": len(state.work_item_ids),
                "non_handler_project_approve_status": 403,
                "non_handler_followup_approve_status": 403,
            }
        finally:
            leftovers = cleanup(db, state)
            checks["cleanup_leftovers"] = leftovers

    assert_true(all(value == 0 for value in checks["cleanup_leftovers"].values()), f"Temporary cleanup failed: {checks['cleanup_leftovers']}")
    return {"status": "passed", "base_url": base_url, "prefix": state.prefix, "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8082/api/v1")
    args = parser.parse_args()
    result = run_acceptance(args.base_url)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
