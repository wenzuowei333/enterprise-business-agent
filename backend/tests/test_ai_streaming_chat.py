from __future__ import annotations

import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.ai_chat import router
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.models import AiChatRun, AiConversation, AiMessage, ExceptionCase, ExceptionEvidence, Permission, Role, RolePermission, User
from app.schemas.ai_chat import AiChatContextRequest
from app.services.ai_chat_service import _case_analysis_context
from app.services.hermes_ai_service import HermesCancelledError, HermesUnavailableError


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


def _events(response_text: str) -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    for frame in response_text.replace("\r\n", "\n").split("\n\n"):
        event = "message"
        data = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
        if data is not None:
            result.append((event, data))
    return result


class TestAiStreamingChat:
    def setup_method(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            role = Role(role_code="chat-user", role_name="Chat User")
            permissions = [
                Permission(
                    permission_code=code,
                    permission_name=code,
                    resource_type=code.split(".", 1)[0],
                    action_type="view",
                )
                for code in ("exception_center.view", "crm_insight.view")
            ]
            first = User(
                username="chat-first",
                password_hash="hash",
                real_name="Chat First",
                role="chat-user",
                status="active",
                is_active=True,
            )
            second = User(
                username="chat-second",
                password_hash="hash",
                real_name="Chat Second",
                role="chat-user",
                status="active",
                is_active=True,
            )
            db.add_all([role, *permissions, first, second])
            db.flush()
            db.add_all([RolePermission(role_id=role.id, permission_id=item.id) for item in permissions])
            first_case = ExceptionCase(
                case_no="EXC-CASE-0001",
                fingerprint="case-fingerprint-0001",
                domain="inventory",
                rule_code="inventory.negative_stock",
                title="库存数量异常",
                severity="critical",
                status="open",
                occurrence_type="new",
                source_type="inventory_snapshot_quality",
                evidence_version="evidence-v1",
                reason="库存结存为负数",
            )
            second_case = ExceptionCase(
                case_no="EXC-CASE-0002",
                fingerprint="case-fingerprint-0002",
                domain="import",
                rule_code="import.batch_failed",
                title="导入批次异常",
                severity="high",
                status="open",
                occurrence_type="new",
                source_type="import_batch",
                evidence_version="evidence-v2",
                reason="导入批次校验失败",
            )
            db.add_all([first_case, second_case])
            db.flush()
            db.add(
                ExceptionEvidence(
                    case_id=first_case.id,
                    evidence_version=first_case.evidence_version,
                    data_json={"reason": "联系 13800138000 核对", "stock_qty": -12},
                )
            )
            db.commit()
            self.first_id = first.id
            self.second_id = second.id
            self.first_case = first_case
            self.second_case = second_case

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        def override_db():
            with self.session_factory() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.first_headers = {"Authorization": f"Bearer {create_access_token('chat-first')}"}
        self.second_headers = {"Authorization": f"Bearer {create_access_token('chat-second')}"}

    def teardown_method(self) -> None:
        self.client.close()
        self.engine.dispose()

    def _patches(self, stream=None):  # noqa: ANN001
        stack = ExitStack()
        for name in (
            "exception_center_enabled",
            "exception_ai_enabled",
            "exception_ai_global_enabled",
            "exception_ai_chat_enabled",
            "exception_ai_case_analysis_enabled",
        ):
            stack.enter_context(patch(f"app.api.routes.ai_chat.settings.{name}", True))
            stack.enter_context(patch(f"app.services.ai_chat_service.settings.{name}", True))
        stack.enter_context(
            patch(
                "app.api.routes.ai_chat.SessionLocal",
                side_effect=lambda: self.session_factory(),
            )
        )
        stack.enter_context(
            patch(
                "app.services.ai_chat_service.build_chat_context",
                return_value=({"exception_center": {"case_count": 0}}, ["scope:test"], "当前筛选 · 0 条样本"),
            )
        )
        if stream is not None:
            stack.enter_context(patch("app.api.routes.ai_chat.stream_hermes_chat", side_effect=stream))
        return stack

    @staticmethod
    def _successful_stream(_messages, **_kwargs):  # noqa: ANN001
        yield {"type": "metadata", "provider_request_id": "provider-test-1"}
        yield {"type": "delta", "text": "第一段"}
        yield {"type": "delta", "text": "，第二段。"}
        yield {"type": "usage", "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16}}
        yield {"type": "done"}

    def _post(self, request_id: str, *, conversation_no: str | None = None, message: str = "请分析异常"):
        return self.client.post(
            "/api/v1/ai/chat/streams",
            headers=self.first_headers,
            json={
                "client_request_id": request_id,
                "conversation_no": conversation_no,
                "message": message,
                "channel": "exception_center_web",
                "operation": "assistant.message",
                "context": {"scope": "current_filters", "filters": {}, "case_nos": []},
            },
        )

    def _post_case(self, request_id: str, case_no: str = "EXC-CASE-0001"):
        return self.client.post(
            "/api/v1/ai/chat/streams",
            headers=self.first_headers,
            json={
                "client_request_id": request_id,
                "conversation_no": None,
                "message": "分析该异常发生的原因，并给出可验证的解决方案",
                "channel": "exception_center_web",
                "operation": "exception.case_analysis",
                "context": {"scope": "case", "filters": {}, "case_nos": [case_no]},
            },
        )

    def test_stream_persists_two_deltas_usage_and_completed_run(self) -> None:
        with self._patches(self._successful_stream):
            response = self._post("request-success-0001")
        assert response.status_code == 200, response.text
        events = _events(response.text)
        assert [name for name, _ in events] == [
            "run_started",
            "context_ready",
            "message_started",
            "delta",
            "delta",
            "usage",
            "message_completed",
            "done",
        ]
        assert [payload["text"] for name, payload in events if name == "delta"] == ["第一段", "，第二段。"]
        with self.session_factory() as db:
            run = db.scalar(select(AiChatRun))
            messages = list(db.scalars(select(AiMessage).order_by(AiMessage.sequence_no)).all())
            assert run is not None and run.status == "completed"
            assert run.provider_request_id == "provider-test-1"
            assert run.usage_json["total_tokens"] == 16
            assert [(row.role, row.status, row.content) for row in messages] == [
                ("user", "completed", "请分析异常"),
                ("assistant", "completed", "第一段，第二段。"),
            ]

    def test_idempotency_does_not_create_duplicate_messages(self) -> None:
        with self._patches(self._successful_stream):
            first = self._post("request-idempotent-0001")
            second = self._post("request-idempotent-0001")
        assert first.status_code == 200
        assert second.status_code == 409
        with self.session_factory() as db:
            assert len(list(db.scalars(select(AiChatRun)).all())) == 1
            assert len(list(db.scalars(select(AiMessage)).all())) == 2

    def test_multi_turn_keeps_one_conversation_and_ordered_history(self) -> None:
        provider_calls: list[list[dict[str, str]]] = []

        def stream(messages, **_kwargs):  # noqa: ANN001
            provider_calls.append(messages)
            yield from self._successful_stream(messages)

        with self._patches(stream):
            first = self._post("request-multi-0001", message="第一轮")
            conversation_no = next(payload["conversation_no"] for name, payload in _events(first.text) if name == "run_started")
            second = self._post("request-multi-0002", conversation_no=conversation_no, message="第二轮")
        assert second.status_code == 200
        with self.session_factory() as db:
            assert len(list(db.scalars(select(AiConversation)).all())) == 1
            rows = list(db.scalars(select(AiMessage).order_by(AiMessage.sequence_no)).all())
            assert [row.sequence_no for row in rows] == [1, 2, 3, 4]
        assert any(item["content"] == "第一段，第二段。" for item in provider_calls[1] if item["role"] == "assistant")

    def test_run_is_private_and_owner_can_request_cancellation(self) -> None:
        with self._patches(self._successful_stream):
            response = self._post("request-private-0001")
            run_no = next(payload["run_no"] for name, payload in _events(response.text) if name == "run_started")
            with self.session_factory() as db:
                run = db.scalar(select(AiChatRun).where(AiChatRun.run_no == run_no))
                run.status = "streaming"
                db.commit()
            denied = self.client.get(f"/api/v1/ai/chat/runs/{run_no}", headers=self.second_headers)
            cancelled = self.client.post(f"/api/v1/ai/chat/runs/{run_no}/cancel", headers=self.first_headers)
        assert denied.status_code == 404
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancel_requested"

    def test_cancel_before_first_delta_emits_cancelled_event(self) -> None:
        def cancelled_stream(_messages, **_kwargs):  # noqa: ANN001
            raise HermesCancelledError("cancelled before first delta")
            yield  # pragma: no cover

        with self._patches(cancelled_stream):
            response = self._post("request-cancel-early-0001")
        assert response.status_code == 200
        events = _events(response.text)
        assert [name for name, _ in events][-2:] == ["cancelled", "done"]
        cancelled_payload = next(payload for name, payload in events if name == "cancelled")
        assert cancelled_payload["partial"] is False
        with self.session_factory() as db:
            run = db.scalar(select(AiChatRun))
            assistant = db.scalar(select(AiMessage).where(AiMessage.role == "assistant"))
            assert run is not None and run.status == "cancelled"
            assert assistant is not None and assistant.status == "cancelled"
            assert assistant.content == ""

    def test_failed_stream_is_not_marked_as_successful_answer(self) -> None:
        def failing_stream(_messages, **_kwargs):  # noqa: ANN001
            yield {"type": "delta", "text": "未完成内容"}
            raise HermesUnavailableError("provider unavailable")

        with self._patches(failing_stream):
            response = self._post("request-failed-0001")
        assert response.status_code == 200
        assert [name for name, _ in _events(response.text)][-2:] == ["error", "done"]
        with self.session_factory() as db:
            run = db.scalar(select(AiChatRun))
            assistant = db.scalar(select(AiMessage).where(AiMessage.role == "assistant"))
            assert run is not None and run.status == "failed"
            assert assistant is not None and assistant.status == "failed"
            assert assistant.content == "未完成内容"

    def test_missing_permission_is_rejected_before_creating_a_run(self) -> None:
        with self.session_factory() as db:
            permission = db.scalar(select(Permission).where(Permission.permission_code == "crm_insight.view"))
            role = db.scalar(select(Role).where(Role.role_code == "chat-user"))
            mapping = db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            db.delete(mapping)
            db.commit()
        with self._patches(self._successful_stream):
            response = self._post("request-denied-0001")
        assert response.status_code == 403
        with self.session_factory() as db:
            assert db.scalar(select(AiChatRun)) is None

    def test_case_analysis_reuses_case_conversation_and_emits_deterministic_artifact(self) -> None:
        artifact = {
            "type": "exception_case_analysis",
            "case": {"case_no": self.first_case.case_no, "evidence_version": self.first_case.evidence_version},
            "action_path": "/inventory",
            "available_actions": ["rebuild_inventory_flow"],
        }
        context_meta = {
            "case_no": self.first_case.case_no,
            "title": self.first_case.title,
            "severity": self.first_case.severity,
            "status": self.first_case.status,
            "evidence_version": self.first_case.evidence_version,
            "evidence_truncated": False,
        }
        prepared = (
            {"case": context_meta},
            [f"exception_case:{self.first_case.case_no}"],
            f"当前案件 · {self.first_case.case_no}",
            context_meta,
            [artifact],
            self.first_case,
        )
        with self._patches(self._successful_stream), patch(
            "app.services.ai_chat_service._case_analysis_context",
            return_value=prepared,
        ):
            first = self._post_case("request-case-0001")
            second = self._post_case("request-case-0002")
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        first_events = _events(first.text)
        second_events = _events(second.text)
        assert next(payload for name, payload in first_events if name == "context_ready")["conversation_reused"] is False
        assert next(payload for name, payload in second_events if name == "context_ready")["conversation_reused"] is True
        assert next(payload for name, payload in first_events if name == "artifact")["artifact"] == artifact
        conversation_no = next(payload for name, payload in first_events if name == "run_started")["conversation_no"]
        with self._patches():
            public_messages = self.client.get(
                f"/api/v1/ai/chat/conversations/{conversation_no}/messages",
                headers=self.first_headers,
            )
        assert public_messages.status_code == 200
        assert public_messages.json()[-1]["context_meta"]["case_no"] == self.first_case.case_no
        assert public_messages.json()[-1]["artifacts"] == [artifact]
        with self.session_factory() as db:
            conversations = list(db.scalars(select(AiConversation)).all())
            messages = list(db.scalars(select(AiMessage).order_by(AiMessage.sequence_no)).all())
            assert len(conversations) == 1
            assert conversations[0].context_type == "exception_case"
            assert conversations[0].context_id == self.first_case.case_no
            assert [row.sequence_no for row in messages] == [1, 2, 3, 4]
            assert messages[-1].payload_json["artifacts"] == [artifact]

    def test_case_context_is_server_loaded_redacted_and_bounded(self) -> None:
        with self.session_factory() as db:
            user = db.get(User, self.first_id)
            case = db.scalar(select(ExceptionCase).where(ExceptionCase.case_no == self.first_case.case_no))
            request_context = AiChatContextRequest(scope="case", filters={}, case_nos=[case.case_no])
            with (
                patch("app.services.ai_chat_service.settings.exception_ai_case_analysis_enabled", True),
                patch("app.services.ai_chat_service._visible_context_cases", return_value=[case]),
                patch(
                    "app.services.ai_chat_service._build_migrated_context",
                    return_value=({}, SimpleNamespace(source_refs=[])),
                ),
                patch("app.services.ai_chat_service.available_exception_action_types", return_value=[]),
            ):
                context, refs, _, context_meta, artifacts, loaded_case = _case_analysis_context(db, user, request_context)
        encoded = json.dumps(context, ensure_ascii=False, default=str)
        assert loaded_case.case_no == self.first_case.case_no
        assert "13800138000" not in encoded
        assert "[REDACTED_PHONE]" in encoded
        assert context_meta["case_no"] == self.first_case.case_no
        assert refs[0] == f"exception_case:{self.first_case.case_no}"
        assert artifacts[0]["available_actions"] == []
