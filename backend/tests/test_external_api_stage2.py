import unittest
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.mobile_errors import install_mobile_error_contract
from app.api.routes.external_api_v2 import router as external_v2_router
from app.core.database import Base, get_db
from app.models import (
    ApprovalInstance,
    CrmFollowup,
    CrmProject,
    CrmProjectCustomerTask,
    CrmProjectReview,
    CustomerMaster,
    ExternalApiKey,
    User,
    WorkItem,
)
from app.services.external_api_service import hash_external_token


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class ExternalApiStage2Test(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.token = "pb-ext-stage2-full"
        self.project_only_token = "pb-ext-stage2-project-only"
        self._seed_data()

        app = FastAPI()
        install_mobile_error_contract(app)
        app.include_router(external_v2_router)

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _seed_data(self):
        now = datetime.now(timezone.utc)
        owner = User(username="owner", password_hash="hash", real_name="项目负责人", role="salesperson", status="active", is_active=True)
        manager = User(username="manager", password_hash="hash", real_name="项目经理", role="manager", status="active", is_active=True)
        executor = User(username="executor", password_hash="hash", real_name="执行人员", role="salesperson", status="active", is_active=True)
        east_a = CustomerMaster(customer_code="C-EAST-A", customer_name="East A", region="East")
        east_b = CustomerMaster(customer_code="C-EAST-B", customer_name="East B", region="East")
        west = CustomerMaster(customer_code="C-WEST", customer_name="West secret", region="West")
        self.db.add_all([owner, manager, executor, east_a, east_b, west])
        self.db.flush()

        blocked = CrmProject(
            project_code="P-BLOCKED",
            project_name="Blocked project",
            purpose="Collect verified customer needs",
            business_line="Bags",
            owner_user_id=owner.id,
            project_manager_user_id=manager.id,
            start_date=date.today() - timedelta(days=10),
            due_date=date.today() + timedelta(days=20),
            status="active",
            approval_status="approved",
        )
        ready = CrmProject(
            project_code="P-READY",
            project_name="Ready project",
            purpose="Complete closed-loop validation",
            owner_user_id=owner.id,
            project_manager_user_id=manager.id,
            status="active",
            approval_status="approved",
        )
        hidden = CrmProject(project_code="P-HIDDEN", project_name="Hidden project", purpose="Do not expose", status="active", approval_status="approved")
        self.db.add_all([blocked, ready, hidden])
        self.db.flush()
        self.blocked_project_id = blocked.id
        self.ready_project_id = ready.id
        self.hidden_project_id = hidden.id

        open_task = CrmProjectCustomerTask(
            project_id=blocked.id,
            task_code="T-OPEN",
            customer_code=east_a.customer_code,
            customer_name_snapshot=east_a.customer_name,
            executor_user_id=executor.id,
            executor_name_snapshot=executor.real_name,
            business_issue_point="Decision maker not confirmed",
            round_target="Confirm decision maker",
            feedback_due_at=now - timedelta(days=1),
            status="need_support",
            need_support=True,
            is_blocked=True,
            latest_blocker_reason="customer_unreachable",
            latest_blocker_note="Needs manager introduction",
            latest_owner_next_status="contact_manager",
            latest_owner_next_action="Arrange introduction",
            latest_owner_next_followup_at=now + timedelta(days=1),
        )
        closed_task = CrmProjectCustomerTask(
            project_id=blocked.id,
            task_code="T-CLOSED",
            customer_code=east_b.customer_code,
            customer_name_snapshot=east_b.customer_name,
            executor_name_snapshot=executor.real_name,
            status="closed",
            is_closed=True,
        )
        cross_region_task = CrmProjectCustomerTask(
            project_id=blocked.id,
            task_code="T-CROSS-REGION",
            customer_code=west.customer_code,
            customer_name_snapshot=west.customer_name,
            status="closed",
            is_closed=True,
        )
        ready_task = CrmProjectCustomerTask(
            project_id=ready.id,
            task_code="T-READY",
            customer_code=east_b.customer_code,
            customer_name_snapshot=east_b.customer_name,
            status="closed",
            is_closed=True,
        )
        hidden_task = CrmProjectCustomerTask(
            project_id=hidden.id,
            task_code="T-HIDDEN",
            customer_code=west.customer_code,
            customer_name_snapshot=west.customer_name,
            status="in_progress",
        )
        self.db.add_all([open_task, closed_task, cross_region_task, ready_task, hidden_task])
        self.db.flush()
        self.open_task_id = open_task.id

        approved = CrmFollowup(
            followup_no="F-APPROVED",
            project_id=blocked.id,
            task_id=open_task.id,
            customer_code=east_a.customer_code,
            executor_name_snapshot=executor.real_name,
            followup_date=date.today(),
            method="phone",
            frontline_action="Called customer",
            customer_feedback="Customer requested manager support",
            current_need="Manager introduction",
            blocker_reason="customer_unreachable",
            blocker_note="Approved blocker detail",
            next_action="Arrange introduction",
            need_support=True,
            valid_feedback=True,
            review_status="approved",
            reviewed_at=now - timedelta(hours=2),
        )
        pending = CrmFollowup(
            followup_no="F-PENDING",
            project_id=blocked.id,
            task_id=closed_task.id,
            customer_code=east_b.customer_code,
            customer_feedback="PENDING SECRET MUST NOT APPEAR",
            valid_feedback=True,
            review_status="pending",
        )
        ready_followup = CrmFollowup(
            followup_no="F-READY",
            project_id=ready.id,
            task_id=ready_task.id,
            customer_code=east_b.customer_code,
            customer_feedback="Closure confirmed",
            valid_feedback=True,
            review_status="approved",
            reviewed_at=now - timedelta(hours=1),
            is_closed=True,
        )
        hidden_followup = CrmFollowup(
            followup_no="F-HIDDEN",
            project_id=hidden.id,
            task_id=hidden_task.id,
            customer_code=west.customer_code,
            customer_feedback="HIDDEN FOLLOWUP",
            valid_feedback=True,
            review_status="approved",
        )
        self.db.add_all([approved, pending, ready_followup, hidden_followup])
        self.db.flush()

        self.db.add_all(
            [
                WorkItem(
                    item_no="W-OPEN",
                    source_type="crm_followup",
                    source_id=str(approved.id),
                    resource_type="crm_task",
                    resource_id=str(open_task.id),
                    project_id=blocked.id,
                    customer_code=east_a.customer_code,
                    item_type="manager_support",
                    title="Manager support needed",
                    detail="Introduce project owner",
                    priority="high",
                    status="open",
                    assignee_user_id=manager.id,
                ),
                WorkItem(
                    item_no="W-CROSS",
                    source_type="crm_task",
                    source_id=str(cross_region_task.id),
                    project_id=blocked.id,
                    customer_code=west.customer_code,
                    item_type="support",
                    title="WEST SECRET WORK ITEM",
                    status="open",
                ),
            ]
        )
        pending_approval = ApprovalInstance(
            approval_no="A-PENDING",
            approval_type="crm_followup_submit",
            resource_type="crm_followup",
            resource_id=str(approved.id),
            title="Blocked project approval",
            status="under_review",
            payload_json={"followup": {"project_id": blocked.id, "task_id": open_task.id, "customer_code": east_a.customer_code}, "secret": "APPROVAL SECRET"},
        )
        hidden_approval = ApprovalInstance(
            approval_no="A-HIDDEN",
            approval_type="crm_followup_submit",
            resource_type="crm_followup",
            resource_id=str(hidden_followup.id),
            title="Hidden approval",
            status="under_review",
            payload_json={"followup": {"project_id": hidden.id, "task_id": hidden_task.id, "customer_code": west.customer_code}},
        )
        self.db.add_all([pending_approval, hidden_approval])
        self.db.add(CrmProjectReview(review_no="R-READY", project_id=ready.id, review_date=date.today(), status="confirmed", conclusion="ready"))
        self.db.flush()

        full_key = ExternalApiKey(
            key_id="ext_stage2_full",
            name="Stage 2 full agent",
            key_prefix=self.token[:16],
            key_hash=hash_external_token(self.token),
            scope_region="East",
            scope_project_ids=[blocked.id, ready.id],
            allowed_customer_fields=["customer_code", "customer_name"],
            can_read_projects=True,
            can_read_customers=True,
            can_read_followups=True,
            can_read_judgements=False,
            can_read_tasks=True,
            can_read_approvals=True,
            can_read_audit_summary=False,
        )
        project_only_key = ExternalApiKey(
            key_id="ext_stage2_project_only",
            name="Stage 2 project agent",
            key_prefix=self.project_only_token[:16],
            key_hash=hash_external_token(self.project_only_token),
            scope_region="East",
            scope_project_ids=[blocked.id, ready.id],
            allowed_customer_fields=["customer_code", "customer_name"],
            can_read_projects=True,
            can_read_customers=False,
            can_read_followups=False,
            can_read_judgements=False,
            can_read_tasks=False,
            can_read_approvals=False,
            can_read_audit_summary=False,
        )
        self.db.add_all([full_key, project_only_key])
        self.db.commit()

    def _headers(self, token=None):
        return {"Authorization": f"Bearer {token or self.token}"}

    def test_project_list_is_scoped_and_returns_safe_progress_summary(self):
        response = self.client.get("/api/external/v2/projects", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        items = response.json()["data"]["items"]
        self.assertEqual({item["project_code"] for item in items}, {"P-BLOCKED", "P-READY"})
        blocked = next(item for item in items if item["project_code"] == "P-BLOCKED")
        self.assertEqual(blocked["task_total"], 2)
        self.assertEqual(blocked["task_closed"], 1)
        self.assertEqual(blocked["owner"], "项目负责人")
        self.assertNotIn("owner_user_id", response.text)
        self.assertNotIn("P-HIDDEN", response.text)
        self.assertNotIn("T-CROSS-REGION", response.text)

    def test_project_cursor_pagination_is_stable_without_duplicates(self):
        first = self.client.get("/api/external/v2/projects", headers=self._headers(), params={"limit": 1})
        cursor = first.json()["meta"]["next_cursor"]
        second = self.client.get("/api/external/v2/projects", headers=self._headers(), params={"limit": 1, "cursor": cursor})

        self.assertTrue(first.json()["meta"]["has_more"])
        self.assertIsNotNone(cursor)
        self.assertNotEqual(first.json()["data"]["items"][0]["id"], second.json()["data"]["items"][0]["id"])

    def test_malformed_cursor_returns_stable_bad_request(self):
        response = self.client.get("/api/external/v2/projects", headers=self._headers(), params={"cursor": "%%%not-a-cursor%%%"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "http_400")
        self.assertEqual(response.json()["error"]["message"], "Invalid pagination cursor")
        self.assertTrue(response.json()["error"]["request_id"])

    def test_limit_above_contract_maximum_is_rejected(self):
        response = self.client.get("/api/external/v2/projects", headers=self._headers(), params={"limit": 201})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "http_422")
        self.assertIn("between 1 and 200", response.json()["error"]["message"])

    def test_blocked_project_progress_uses_only_approved_visible_business_facts(self):
        response = self.client.get(f"/api/external/v2/projects/{self.blocked_project_id}/progress", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        metrics = data["metrics"]
        self.assertEqual(metrics["task_total"], 2)
        self.assertEqual(metrics["task_closed"], 1)
        self.assertEqual(metrics["task_overdue"], 1)
        self.assertEqual(metrics["task_blocked"], 1)
        self.assertEqual(metrics["feedback_task_count"], 1)
        self.assertEqual(metrics["no_feedback_task_count"], 1)
        self.assertEqual(metrics["support_open_count"], 1)
        self.assertEqual(metrics["pending_approval_count"], 1)
        self.assertEqual(metrics["task_closure_rate"], 50.0)
        self.assertFalse(data["closure_ready"])
        self.assertEqual(data["closure_state"], "blocked")
        self.assertNotIn("PENDING SECRET MUST NOT APPEAR", response.text)
        self.assertNotIn("WEST SECRET", response.text)

    def test_ready_project_reaches_closure_ready(self):
        response = self.client.get(f"/api/external/v2/projects/{self.ready_project_id}/progress", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["closure_ready"])
        self.assertEqual(data["closure_state"], "ready")
        self.assertEqual(data["metrics"]["valid_feedback_rate"], 100.0)
        self.assertEqual(data["latest_review_status"], "confirmed")
        self.assertEqual(data["closure_blockers"], [])

    def test_task_endpoints_enforce_scope_and_expose_project_purpose(self):
        page = self.client.get(f"/api/external/v2/projects/{self.blocked_project_id}/tasks", headers=self._headers())
        detail = self.client.get(f"/api/external/v2/tasks/{self.open_task_id}", headers=self._headers())

        self.assertEqual({item["task_code"] for item in page.json()["data"]["items"]}, {"T-OPEN", "T-CLOSED"})
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["project_purpose"], "Collect verified customer needs")
        self.assertTrue(detail.json()["data"]["overdue"])
        self.assertNotIn("T-CROSS-REGION", page.text)

    def test_followups_only_return_approved_records(self):
        response = self.client.get("/api/external/v2/followups", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        numbers = {item["followup_no"] for item in response.json()["data"]["items"]}
        self.assertEqual(numbers, {"F-APPROVED", "F-READY"})
        self.assertNotIn("PENDING SECRET MUST NOT APPEAR", response.text)
        self.assertNotIn("HIDDEN FOLLOWUP", response.text)

    def test_work_items_and_approvals_are_scoped_and_sanitized(self):
        work_items = self.client.get("/api/external/v2/work-items", headers=self._headers())
        approvals = self.client.get("/api/external/v2/approvals", headers=self._headers())

        self.assertEqual([item["item_no"] for item in work_items.json()["data"]["items"]], ["W-OPEN"])
        self.assertEqual([item["approval_no"] for item in approvals.json()["data"]["items"]], ["A-PENDING"])
        self.assertNotIn("APPROVAL SECRET", approvals.text)
        self.assertNotIn("payload_json", approvals.text)
        self.assertNotIn("A-HIDDEN", approvals.text)

    def test_timeline_respects_component_permissions_and_review_state(self):
        full = self.client.get(f"/api/external/v2/projects/{self.blocked_project_id}/timeline", headers=self._headers())
        project_only = self.client.get(
            f"/api/external/v2/projects/{self.blocked_project_id}/timeline",
            headers=self._headers(self.project_only_token),
        )

        self.assertEqual(full.status_code, 200)
        event_types = {item["event_type"] for item in full.json()["data"]["items"]}
        self.assertEqual(event_types, {"followup_approved", "work_item", "approval"})
        self.assertNotIn("PENDING SECRET MUST NOT APPEAR", full.text)
        self.assertEqual(project_only.status_code, 200)
        self.assertEqual(project_only.json()["data"]["items"], [])

    def test_permission_denial_and_hidden_project_use_safe_errors(self):
        denied = self.client.get("/api/external/v2/tasks", headers=self._headers(self.project_only_token))
        hidden = self.client.get(f"/api/external/v2/projects/{self.hidden_project_id}", headers=self._headers())

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "http_403")
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(hidden.json()["error"]["message"], "Project not found")

    def test_overview_only_populates_authorized_domains(self):
        full = self.client.get("/api/external/v2/overview", headers=self._headers())
        project_only = self.client.get("/api/external/v2/overview", headers=self._headers(self.project_only_token))

        self.assertEqual(full.status_code, 200)
        stats = full.json()["data"]["stats"]
        self.assertEqual(stats["projects"], 2)
        self.assertEqual(stats["tasks"], 3)
        self.assertEqual(stats["approved_followups"], 2)
        self.assertEqual(stats["open_work_items"], 1)
        self.assertEqual(stats["pending_approvals"], 1)
        project_stats = project_only.json()["data"]["stats"]
        self.assertEqual(project_stats["projects"], 2)
        self.assertIsNone(project_stats["tasks"])
        self.assertIsNone(project_stats["approved_followups"])
        self.assertIsNone(project_stats["pending_approvals"])

    def test_all_stage2_responses_exclude_internal_and_out_of_scope_data(self):
        paths = [
            "/api/external/v2/overview",
            "/api/external/v2/projects",
            f"/api/external/v2/projects/{self.blocked_project_id}",
            f"/api/external/v2/projects/{self.blocked_project_id}/progress",
            f"/api/external/v2/projects/{self.blocked_project_id}/tasks",
            f"/api/external/v2/projects/{self.blocked_project_id}/timeline",
            "/api/external/v2/tasks",
            f"/api/external/v2/tasks/{self.open_task_id}",
            "/api/external/v2/followups",
            "/api/external/v2/work-items",
            "/api/external/v2/approvals",
        ]
        forbidden = [
            "payload_json",
            "result_json",
            "password_hash",
            "owner_user_id",
            "PENDING SECRET MUST NOT APPEAR",
            "P-HIDDEN",
            "T-CROSS-REGION",
            "WEST SECRET",
        ]

        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path, headers=self._headers())
                self.assertEqual(response.status_code, 200)
                for value in forbidden:
                    self.assertNotIn(value, response.text)


if __name__ == "__main__":
    unittest.main()
