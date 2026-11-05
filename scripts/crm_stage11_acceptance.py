#!/usr/bin/env python3
"""Stage 11 CRM migration acceptance script.

This script is intended to run on the deployed 8082 environment. It creates
temporary users/customer/CRM records, verifies the HTTP API and permission
matrix, then cleans up all temporary business data.
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
class Stage11State:
    prefix: str
    user_ids: dict[str, int] = field(default_factory=dict)
    customer_code: str | None = None
    project_id: int | None = None
    project_code: str | None = None
    task_id: int | None = None
    approval_ids: list[int] = field(default_factory=list)
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
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
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

    def login(self, username: str, password: str) -> str:
        response = self.request("POST", "/auth/login", payload={"username": username, "password": password}, expected={200})
        token = response.body.get("access_token")
        if not token:
            raise AssertionError(f"Login for {username} did not return access_token")
        return str(token)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def now_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def business_date(value: datetime) -> str:
    return (value + timedelta(hours=8)).date().isoformat()


def cleanup_temp_data(db: Any, state: Stage11State) -> dict[str, int]:
    from sqlalchemy import delete, or_, select

    from app.models import (
        ApprovalEvent,
        ApprovalInstance,
        CrmFollowup,
        CrmProject,
        CrmProjectCustomerTask,
        CustomerMaster,
        EmployeeProfile,
        User,
        UserPermissionOverride,
        WorkItem,
    )

    prefix = state.prefix
    temp_user_ids = list(
        db.scalars(select(User.id).where(or_(User.username.like(f"{prefix.lower()}%"), User.employee_code.like(f"{prefix}%")))).all()
    )
    project_ids = list(db.scalars(select(CrmProject.id).where(CrmProject.project_code.like(f"{prefix}%"))).all())
    task_ids = list(
        db.scalars(
            select(CrmProjectCustomerTask.id).where(
                or_(
                    CrmProjectCustomerTask.task_code.like(f"{prefix}%"),
                    CrmProjectCustomerTask.project_id.in_(project_ids or [-1]),
                    CrmProjectCustomerTask.customer_code.like(f"{prefix}%"),
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
                    CrmFollowup.customer_code.like(f"{prefix}%"),
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
                    ApprovalInstance.applicant_user_id.in_(temp_user_ids or [-1]),
                    ApprovalInstance.current_handler_user_id.in_(temp_user_ids or [-1]),
                    ApprovalInstance.resource_id.in_([str(project_id) for project_id in project_ids] or ["__none__"]),
                )
            )
        ).all()
    )

    db.execute(delete(ApprovalEvent).where(ApprovalEvent.approval_id.in_(approval_ids or [-1])))
    db.execute(delete(WorkItem).where(or_(WorkItem.project_id.in_(project_ids or [-1]), WorkItem.customer_code.like(f"{prefix}%"))))
    db.execute(delete(CrmFollowup).where(CrmFollowup.id.in_(followup_ids or [-1])))
    db.execute(delete(CrmProjectCustomerTask).where(CrmProjectCustomerTask.id.in_(task_ids or [-1])))
    db.execute(delete(CrmProject).where(CrmProject.id.in_(project_ids or [-1])))
    db.execute(delete(ApprovalInstance).where(ApprovalInstance.id.in_(approval_ids or [-1])))
    db.execute(delete(CustomerMaster).where(CustomerMaster.customer_code.like(f"{prefix}%")))
    db.execute(delete(UserPermissionOverride).where(UserPermissionOverride.user_id.in_(temp_user_ids or [-1])))
    db.execute(delete(EmployeeProfile).where(EmployeeProfile.employee_code.like(f"{prefix}%")))
    db.execute(delete(User).where(User.id.in_(temp_user_ids or [-1])))
    db.commit()

    leftovers = {
        "users": db.scalar(select(User.id).where(or_(User.username.like(f"{prefix.lower()}%"), User.employee_code.like(f"{prefix}%"))).limit(1)) or 0,
        "customers": db.scalar(select(CustomerMaster.id).where(CustomerMaster.customer_code.like(f"{prefix}%")).limit(1)) or 0,
        "projects": db.scalar(select(CrmProject.id).where(CrmProject.project_code.like(f"{prefix}%")).limit(1)) or 0,
        "tasks": db.scalar(select(CrmProjectCustomerTask.id).where(CrmProjectCustomerTask.task_code.like(f"{prefix}%")).limit(1)) or 0,
        "followups": db.scalar(select(CrmFollowup.id).where(CrmFollowup.followup_no.like(f"{prefix}%")).limit(1)) or 0,
        "work_items": db.scalar(select(WorkItem.id).where(WorkItem.customer_code.like(f"{prefix}%")).limit(1)) or 0,
        "approvals": db.scalar(select(ApprovalInstance.id).where(ApprovalInstance.title.like(f"{prefix}%")).limit(1)) or 0,
    }
    return leftovers


def seed_temp_identities(db: Any, state: Stage11State, password: str) -> None:
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models import CustomerMaster, EmployeeProfile, Permission, Role, User, UserPermissionOverride

    required_roles = ["admin", "business_middle_office", "salesperson", "viewer"]
    missing_roles = [role for role in required_roles if db.scalar(select(Role).where(Role.role_code == role)) is None]
    assert_true(not missing_roles, f"Missing seed roles: {missing_roles}")

    crm_permissions = [
        "crm_project.view",
        "crm_project.create",
        "crm_task.view",
        "crm_followup.submit",
        "crm_followup.review",
        "crm_issue.view",
        "crm_issue.close",
        "approval.view",
        "approval.approve",
    ]
    missing_permissions = [code for code in crm_permissions if db.scalar(select(Permission).where(Permission.permission_code == code)) is None]
    assert_true(not missing_permissions, f"Missing seed permissions: {missing_permissions}")

    user_specs = {
        "admin": ("admin", "阶段11管理员"),
        "manager": ("business_middle_office", "阶段11业务主管"),
        "sales": ("salesperson", "阶段11一线执行"),
        "viewer": ("viewer", "阶段11只读用户"),
        "deny": ("viewer", "阶段11拒绝覆盖用户"),
    }
    for key, (role_code, real_name) in user_specs.items():
        employee_code = f"{state.prefix}_{key.upper()}"
        employee = EmployeeProfile(
            employee_code=employee_code,
            employee_name=real_name,
            department="阶段11验收",
            position=role_code,
            role_code=role_code,
            status="active",
        )
        db.add(employee)
        db.flush()
        user = User(
            username=f"{state.prefix.lower()}_{key}",
            password_hash=hash_password(password),
            real_name=real_name,
            employee_code=employee_code,
            role=role_code,
            is_active=True,
            status="active",
        )
        db.add(user)
        db.flush()
        employee.user_id = user.id
        state.user_ids[key] = user.id

    denied_permission = db.scalar(select(Permission).where(Permission.permission_code == "crm_project.view"))
    db.add(
        UserPermissionOverride(
            user_id=state.user_ids["deny"],
            permission_id=denied_permission.id,
            effect="deny",
            created_by=state.user_ids["admin"],
            updated_by=state.user_ids["admin"],
        )
    )

    state.customer_code = f"{state.prefix}_CUST"
    db.add(
        CustomerMaster(
            customer_code=state.customer_code,
            customer_name=f"{state.prefix} 客户",
            customer_short_name="阶段11客户",
            customer_type="终端",
            region="测试区域",
            salesperson_employee_code=f"{state.prefix}_SALES",
            salesperson_name="阶段11一线执行",
            contact_name="阶段11联系人",
            contact_phone="00000000000",
            status="active",
            source="stage11_acceptance",
        )
    )
    db.commit()


def run_acceptance(base_url: str) -> dict[str, Any]:
    from sqlalchemy import text

    from app.core.database import SessionLocal

    state = Stage11State(prefix=f"STAGE11_{int(time.time())}")
    password = f"{state.prefix}_Password_8082!"
    client = ApiClient(base_url)
    checks: dict[str, Any] = {}

    with SessionLocal() as db:
        cleanup_temp_data(db, state)
        try:
            revision = str(db.execute(text("select version_num from alembic_version")).scalar_one())
            minimum_revision = "20260701_0001"
            checks["alembic_revision"] = revision
            checks["minimum_required_revision"] = minimum_revision
            assert_true(revision >= minimum_revision, f"Unexpected alembic revision: {revision}")

            seed_temp_identities(db, state, password)

            tokens = {
                key: client.login(f"{state.prefix.lower()}_{key}", password)
                for key in ["admin", "manager", "sales", "viewer", "deny"]
            }

            capabilities = {key: client.request("GET", "/crm/security/capabilities", token=token).body for key, token in tokens.items()}
            checks["capabilities"] = {
                key: {
                    "role_code": value["role_code"],
                    "crm_permission_count": len(value["permission_codes"]),
                }
                for key, value in capabilities.items()
            }
            assert_true("approval.approve" in capabilities["manager"]["permission_codes"], "Manager should have approval.approve")
            assert_true("crm_followup.submit" in capabilities["sales"]["permission_codes"], "Salesperson should have crm_followup.submit")
            assert_true("crm_project.create" not in capabilities["viewer"]["permission_codes"], "Viewer should not create CRM projects")
            assert_true("crm_project.view" not in capabilities["deny"]["permission_codes"], "Deny override should remove crm_project.view")

            client.request("GET", "/crm/security/project-access", token=tokens["manager"], expected={200})
            client.request("GET", "/crm/security/project-access", token=tokens["deny"], expected={403})
            client.request("GET", "/crm/security/approval-access", token=tokens["manager"], expected={200})
            client.request("GET", "/crm/security/approval-access", token=tokens["sales"], expected={403})
            checks["permission_matrix"] = "passed"

            summary_base = client.request("GET", "/crm/summary", token=tokens["manager"]).body
            due_at = datetime.now(timezone.utc) - timedelta(minutes=10)
            project_payload = {
                "title": f"{state.prefix} 项目立项审批",
                "description": "阶段11验收：项目申请生成审批单",
                "current_handler_user_id": state.user_ids["manager"],
                "priority": "normal",
                "submit": True,
                "project": {
                    "project_code": f"{state.prefix}_PROJECT",
                    "project_name": f"{state.prefix} 客户推进项目",
                    "project_type": "阶段11验收",
                    "purpose": "验证项目申请、审批、任务和首页联动",
                    "business_line": "stage11",
                    "owner_user_id": state.user_ids["manager"],
                    "project_manager_user_id": state.user_ids["manager"],
                    "participant_user_ids": [state.user_ids["sales"]],
                    "start_date": business_date(datetime.now(timezone.utc)),
                    "due_date": business_date(datetime.now(timezone.utc) + timedelta(days=7)),
                    "minimum_action": "完成客户跟进",
                    "closure_standard": "有有效反馈并关闭支持事项",
                    "status": "submitted",
                    "approval_status": "submitted",
                },
                "tasks": [
                    {
                        "task_code": f"{state.prefix}_TASK",
                        "customer_code": state.customer_code,
                        "executor_user_id": state.user_ids["sales"],
                        "business_issue_point": "阶段11验收任务",
                        "round_target": "验证日历和跟进责任",
                        "feedback_due_at": now_iso(due_at),
                        "status": "in_progress",
                    }
                ],
            }
            project_approval = client.request("POST", "/crm/projects/approval-draft", token=tokens["manager"], payload=project_payload, expected={201}).body
            state.approval_ids.append(project_approval["id"])

            summary_pending = client.request("GET", "/crm/summary", token=tokens["manager"]).body
            assert_true(
                summary_pending["pending_project_approvals"] >= summary_base["pending_project_approvals"] + 1,
                "Pending project approval should increase after submitted draft",
            )

            duplicate_payload = json.loads(json.dumps(project_payload))
            duplicate_payload["title"] = f"{state.prefix} 重复客户校验"
            duplicate_payload["project"]["project_code"] = f"{state.prefix}_DUP_PROJECT"
            duplicate_payload["tasks"].append(dict(duplicate_payload["tasks"][0], task_code=f"{state.prefix}_DUP_TASK"))
            client.request("POST", "/crm/projects/approval-draft", token=tokens["manager"], payload=duplicate_payload, expected={400})

            rejected_payload = json.loads(json.dumps(project_payload))
            rejected_payload["title"] = f"{state.prefix} 驳回项目审批"
            rejected_payload["project"]["project_code"] = f"{state.prefix}_REJECT_PROJECT"
            rejected_payload["tasks"][0]["task_code"] = f"{state.prefix}_REJECT_TASK"
            rejected = client.request("POST", "/crm/projects/approval-draft", token=tokens["manager"], payload=rejected_payload, expected={201}).body
            state.approval_ids.append(rejected["id"])
            client.request("POST", f"/approvals/{rejected['id']}/reject", token=tokens["manager"], payload={"comment": "阶段11验收驳回"}, expected={200})

            approved_project = client.request(
                "POST",
                f"/approvals/{project_approval['id']}/approve",
                token=tokens["manager"],
                payload={"comment": "阶段11验收通过", "result_json": {"stage": "stage11"}},
                expected={200},
            ).body
            result_json = approved_project["approval"]["result_json"]
            state.project_id = int(result_json["project_id"])
            state.project_code = str(result_json["project_code"])
            state.task_id = int(result_json["task_ids"][0])

            summary_project = client.request("GET", "/crm/summary", token=tokens["manager"]).body
            assert_true(summary_project["active_projects"] >= summary_base["active_projects"] + 1, "Active projects should increase")
            assert_true(summary_project["due_today_tasks"] >= summary_base["due_today_tasks"] + 1, "Due tasks should increase")
            assert_true(summary_project["overdue_no_feedback_tasks"] >= summary_base["overdue_no_feedback_tasks"] + 1, "Overdue risk should increase")

            daily = client.request("GET", f"/crm/daily-summary?date={business_date(due_at)}", token=tokens["manager"]).body
            daily_task_ids = {item["id"] for item in daily["due_tasks"]}
            assert_true(state.task_id in daily_task_ids, "Daily summary should include the created task")
            assert_true(state.user_ids["sales"] in daily["responsible_user_ids"], "Daily summary should include responsible salesperson")
            assert_true(state.user_ids["sales"] in daily["missing_responsible_user_ids"], "Daily summary should show missing followup responsibility before valid followup")

            followup_payload = {
                "title": f"{state.prefix} 跟进事实审批",
                "description": "阶段11验收：一线提交跟进，负责人审核",
                "current_handler_user_id": state.user_ids["manager"],
                "priority": "high",
                "submit": True,
                "followup": {
                    "followup_no": f"{state.prefix}_FOLLOWUP",
                    "project_id": state.project_id,
                    "task_id": state.task_id,
                    "followup_date": business_date(datetime.now(timezone.utc)),
                    "method": "电话",
                    "frontline_action": "完成阶段11客户沟通",
                    "customer_feedback": "客户确认继续推进",
                    "current_need": "需要业务主管协调报价",
                    "need_type": "内部支持",
                    "minimum_action_done": True,
                    "need_support": True,
                    "valid_feedback": True,
                    "review_status": "pending",
                },
            }
            followup_approval = client.request("POST", "/crm/followups/approval-draft", token=tokens["sales"], payload=followup_payload, expected={201}).body
            state.approval_ids.append(followup_approval["id"])

            rejected_followup_payload = json.loads(json.dumps(followup_payload))
            rejected_followup_payload["title"] = f"{state.prefix} 跟进事实驳回"
            rejected_followup_payload["followup"]["followup_no"] = f"{state.prefix}_REJECT_FOLLOWUP"
            rejected_followup = client.request("POST", "/crm/followups/approval-draft", token=tokens["sales"], payload=rejected_followup_payload, expected={201}).body
            state.approval_ids.append(rejected_followup["id"])
            client.request("POST", f"/approvals/{rejected_followup['id']}/reject", token=tokens["manager"], payload={"comment": "阶段11验收退回"}, expected={200})

            approved_followup = client.request(
                "POST",
                f"/approvals/{followup_approval['id']}/approve",
                token=tokens["manager"],
                payload={
                    "comment": "阶段11验收跟进通过",
                    "result_json": {
                        "review_status": "approved",
                        "review_result": "有效",
                        "review_note": "有效反馈，仍需支持事项闭环",
                        "valid_feedback": True,
                        "owner_next_status": "继续推进",
                        "owner_next_followup_at": now_iso(datetime.now(timezone.utc) + timedelta(days=1)),
                    },
                },
                expected={200},
            ).body
            followup_result = approved_followup["approval"]["result_json"]
            state.followup_ids.append(int(followup_result["followup_id"]))
            state.work_item_ids.extend([int(item_id) for item_id in followup_result.get("work_item_ids", [])])
            assert_true(state.work_item_ids, "Approved followup requiring support should generate work item")

            summary_followup = client.request("GET", "/crm/summary", token=tokens["manager"]).body
            assert_true(summary_followup["valid_feedback_tasks"] >= summary_base["valid_feedback_tasks"] + 1, "Valid feedback count should increase")
            assert_true(summary_followup["overdue_no_feedback_tasks"] <= summary_project["overdue_no_feedback_tasks"] - 1, "Valid followup should reduce overdue risk")
            assert_true(summary_followup["open_work_items"] >= summary_base["open_work_items"] + 1, "Open work items should increase")

            context = client.request("GET", f"/context/customers/{urllib.parse.quote(state.customer_code or '')}", token=tokens["manager"]).body
            assert_true(context["crm"]["stats"]["project_total"] >= 1, "Customer context should include CRM project")
            assert_true(context["crm"]["stats"]["task_total"] >= 1, "Customer context should include CRM task")
            assert_true(context["crm"]["stats"]["followup_total"] >= 1, "Customer context should include CRM followup")
            assert_true(context["crm"]["stats"]["work_item_open"] >= 1, "Customer context should include open work item")

            for item_id in state.work_item_ids:
                client.request("POST", f"/work-items/{item_id}/close", token=tokens["manager"], payload={"resolution_note": "阶段11验收关闭"}, expected={200})
            summary_closed = client.request("GET", "/crm/summary", token=tokens["manager"]).body
            assert_true(summary_closed["open_work_items"] <= summary_followup["open_work_items"] - len(state.work_item_ids), "Closing work items should reduce open support count")

            checks["flow"] = {
                "project_approval_id": project_approval["id"],
                "project_id": state.project_id,
                "task_id": state.task_id,
                "followup_id": state.followup_ids[0],
                "closed_work_items": state.work_item_ids,
                "summary_base": summary_base,
                "summary_after_project": summary_project,
                "summary_after_followup": summary_followup,
                "summary_after_close": summary_closed,
                "daily_due_count": daily["due_count"],
                "daily_overdue_count": daily["overdue_count"],
            }

        finally:
            checks["cleanup_leftovers"] = cleanup_temp_data(db, state)

    assert_true(all(value == 0 for value in checks["cleanup_leftovers"].values()), f"Temporary data cleanup failed: {checks['cleanup_leftovers']}")
    return {"status": "passed", "base_url": base_url, "prefix": state.prefix, "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8082/api/v1")
    args = parser.parse_args()
    result = run_acceptance(args.base_url)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
