import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.services.global_ai_backfill_service import (
    backfill_legacy_global_ai_data,
    enrich_legacy_crm_read_models,
)


class GlobalAiStageTwoMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "global-ai-stage2.db"
        self.engine = create_engine(f"sqlite:///{self.database_path.as_posix()}")
        self.backend_dir = Path(__file__).parents[1]
        self.environment = os.environ.copy()
        self.environment["DATABASE_URL"] = f"sqlite:///{self.database_path.as_posix()}"
        self._create_legacy_database()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def _create_legacy_database(self) -> None:
        with self.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            connection.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES ('20260808_0100')")
            connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO users (id) VALUES (7), (8)")
            connection.exec_driver_sql(
                """
                CREATE TABLE assistant_conversation (
                    id INTEGER PRIMARY KEY,
                    conversation_no VARCHAR(120) NOT NULL UNIQUE,
                    user_id INTEGER,
                    username_snapshot VARCHAR(80),
                    channel VARCHAR(80) NOT NULL,
                    session_id VARCHAR(120),
                    context_type VARCHAR(80),
                    context_id VARCHAR(160),
                    operation VARCHAR(120),
                    user_message TEXT NOT NULL,
                    assistant_message TEXT NOT NULL,
                    source VARCHAR(80) NOT NULL,
                    model_name VARCHAR(120),
                    status VARCHAR(40) NOT NULL,
                    payload_json JSON,
                    created_at DATETIME NOT NULL
                )
                """
            )
            conversation_payload = json.dumps(
                {
                    "context_summary": {"projects": 2},
                    "global_ai_result": {
                        "result_type": "text",
                        "structured_fields": {},
                        "summary": "结构化摘要",
                        "warnings": [],
                        "source_refs": ["crm_project:42", "crm_project:42", "customer:C-9"],
                        "model": "glm-5.2",
                        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                        "request_id": "crm-ai-stage2-request",
                        "provider_request_id": "provider-stage2-request",
                        "prompt_version": "crm-assistant.v1",
                        "contract_version": "global-ai-result.v1",
                        "status": "completed",
                        "latency_ms": 321,
                        "attempts": 1,
                    },
                }
            )
            connection.execute(
                text(
                    """
                    INSERT INTO assistant_conversation (
                        id, conversation_no, user_id, username_snapshot, channel, session_id,
                        context_type, context_id, operation, user_message, assistant_message,
                        source, model_name, status, payload_json, created_at
                    ) VALUES (
                        11, 'ASST-LEGACY-11', 7, 'legacy-admin', 'web', 'session-11',
                        'crm_project', '42', 'crm.assistant.message', :user_message, :assistant_message,
                        'hermes', 'glm-5.2', 'completed', :payload_json, '2026-07-01 10:11:12'
                    )
                    """
                ),
                {
                    "user_message": "请分析项目风险",
                    "assistant_message": "项目存在交付风险",
                    "payload_json": conversation_payload,
                },
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE crm_project_insight (
                    id INTEGER PRIMARY KEY,
                    insight_no VARCHAR(120) NOT NULL UNIQUE,
                    project_id INTEGER,
                    task_id INTEGER,
                    customer_code VARCHAR(120),
                    insight_type VARCHAR(120) NOT NULL,
                    summary TEXT NOT NULL,
                    suggested_action TEXT,
                    risk_level VARCHAR(40) NOT NULL,
                    opportunity_level VARCHAR(40),
                    confidence_score INTEGER NOT NULL,
                    status VARCHAR(40) NOT NULL,
                    evidence_json JSON,
                    source VARCHAR(80) NOT NULL,
                    generated_by_user_id INTEGER,
                    reviewed_by_user_id INTEGER,
                    reviewed_at DATETIME,
                    review_note TEXT,
                    payload_json JSON,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            connection.execute(
                text(
                    """
                    INSERT INTO crm_project_insight (
                        id, insight_no, project_id, task_id, customer_code, insight_type,
                        summary, suggested_action, risk_level, opportunity_level,
                        confidence_score, status, evidence_json, source,
                        generated_by_user_id, reviewed_by_user_id, reviewed_at, review_note,
                        payload_json, created_at, updated_at
                    ) VALUES (
                        21, 'INSIGHT-LEGACY-21', 42, NULL, 'C-9', 'delivery_risk',
                        '交付时间存在风险', '建议人工复核交付计划', 'high', 'medium',
                        85, 'accepted', :evidence_json, 'rule', 7, 8,
                        '2026-07-03 12:13:14', '复核通过', :payload_json,
                        '2026-07-02 10:00:00', '2026-07-03 12:13:14'
                    )
                    """
                ),
                {
                    "evidence_json": json.dumps({"source_refs": ["crm_project:42", "task:7"]}),
                    "payload_json": json.dumps({"model_name": "glm-5.2", "legacy": True}),
                },
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE audit_log (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    role_code VARCHAR(80),
                    action_type VARCHAR(80) NOT NULL,
                    resource_type VARCHAR(80) NOT NULL,
                    resource_id VARCHAR(160),
                    before_data JSON,
                    after_data JSON,
                    ip_address VARCHAR(80),
                    user_agent TEXT,
                    created_at DATETIME NOT NULL
                )
                """
            )
            audit_after = json.dumps(
                {
                    "operation": "crm.assistant.message",
                    "source": "hermes",
                    "status": "completed",
                    "permission": "crm_insight.view",
                    "ai_request_id": "crm-ai-stage2-request",
                    "ai_contract_version": "global-ai-result.v1",
                    "ai_status": "completed",
                    "ai_latency_ms": 321,
                    "ai_attempts": 1,
                    "ai_usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                    "prompt": "不得迁移的提示词",
                    "token": "不得迁移的密钥",
                    "project_name": "不得进入安全审计的业务名称",
                    "note": "不得进入安全审计的复核正文",
                }
            )
            connection.execute(
                text(
                    """
                    INSERT INTO audit_log (
                        id, user_id, role_code, action_type, resource_type, resource_id,
                        before_data, after_data, ip_address, user_agent, created_at
                    ) VALUES (
                        31, 7, 'admin', 'crm_assistant_message', 'assistant_conversation',
                        'ASST-LEGACY-11', NULL, :after_data, '127.0.0.1', 'test-agent',
                        '2026-07-01 10:11:13'
                    ), (
                        32, 8, 'admin', 'crm_assistant_review_insight', 'crm_project_insight',
                        'INSIGHT-LEGACY-21', NULL, :review_after, '127.0.0.1', 'test-agent',
                        '2026-07-03 12:13:14'
                    )
                    """
                ),
                {
                    "after_data": audit_after,
                    "review_after": json.dumps(
                        {"status": "accepted", "permission": "crm_insight.review", "note": "敏感复核正文"}
                    ),
                },
            )

    def _alembic(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=self.backend_dir,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_upgrade_backfill_is_idempotent_and_downgrade_preserves_legacy(self):
        upgraded = self._alembic("upgrade", "head")
        self.assertEqual(upgraded.returncode, 0, upgraded.stderr)

        expected_tables = {
            "ai_conversation",
            "ai_message",
            "ai_insight",
            "ai_context_snapshot",
            "ai_action_proposal",
            "ai_action_execution",
            "ai_usage_event",
            "ai_security_event",
        }
        self.assertTrue(expected_tables.issubset(set(inspect(self.engine).get_table_names())))

        with self.engine.begin() as connection:
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM ai_conversation")), 1)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM ai_message")), 2)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM ai_insight")), 1)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM ai_context_snapshot")), 1)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM ai_action_proposal")), 1)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM ai_usage_event")), 1)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM ai_security_event")), 2)

            conversation = connection.execute(text("SELECT * FROM ai_conversation")).mappings().one()
            self.assertEqual(conversation["source_system"], "crm")
            self.assertEqual(conversation["legacy_type"], "assistant_conversation")
            self.assertEqual(conversation["legacy_id"], "11")
            self.assertEqual(conversation["created_by_user_id"], 7)
            self.assertTrue(str(conversation["created_at"]).startswith("2026-07-01 10:11:12"))
            self.assertTrue(str(conversation["updated_at"]).startswith("2026-07-01 10:11:12"))
            conversation_metadata = json.loads(conversation["metadata_json"])
            self.assertEqual(conversation_metadata["projection_version"], "crm-ai-stage3.v1")
            self.assertEqual(conversation_metadata["compatibility"]["username_snapshot"], "legacy-admin")
            self.assertEqual(conversation_metadata["legacy_payload"]["context_summary"], {"projects": 2})

            messages = connection.execute(
                text("SELECT role, content, source_refs_json FROM ai_message ORDER BY sequence_no")
            ).mappings().all()
            self.assertEqual([row["role"] for row in messages], ["user", "assistant"])
            self.assertEqual(messages[0]["content"], "请分析项目风险")
            self.assertEqual(messages[1]["content"], "项目存在交付风险")
            self.assertEqual(json.loads(messages[1]["source_refs_json"]), ["crm_project:42", "customer:C-9"])

            insight = connection.execute(text("SELECT * FROM ai_insight")).mappings().one()
            self.assertEqual(insight["review_status"], "accepted")
            self.assertEqual(insight["created_by_user_id"], 7)
            self.assertEqual(insight["reviewed_by_user_id"], 8)
            self.assertTrue(str(insight["created_at"]).startswith("2026-07-02 10:00:00"))
            self.assertTrue(str(insight["updated_at"]).startswith("2026-07-03 12:13:14"))
            self.assertEqual(json.loads(insight["source_refs_json"]), ["crm_project:42", "task:7"])
            insight_payload = json.loads(insight["payload_json"])
            self.assertEqual(insight_payload["projection_version"], "crm-ai-stage3.v1")
            self.assertEqual(insight_payload["compatibility"]["project_id"], 42)
            self.assertEqual(insight_payload["compatibility"]["legacy_status"], "accepted")
            self.assertEqual(insight_payload["legacy_payload"], {"model_name": "glm-5.2", "legacy": True})

            proposal = connection.execute(text("SELECT * FROM ai_action_proposal")).mappings().one()
            self.assertEqual(proposal["legacy_type"], "crm_project_insight.action_proposal")
            self.assertEqual(proposal["action_type"], "crm_insight.review")
            self.assertEqual(proposal["requires_confirmation"], 1)

            usage = connection.execute(text("SELECT * FROM ai_usage_event")).mappings().one()
            self.assertEqual(usage["request_id"], "crm-ai-stage2-request")
            self.assertEqual(usage["total_tokens"], 20)
            self.assertEqual(usage["contract_version"], "global-ai-result.v1")

            security_details = [
                json.loads(row[0])
                for row in connection.execute(text("SELECT detail_json FROM ai_security_event ORDER BY id"))
            ]
            serialized_details = json.dumps(security_details, ensure_ascii=False)
            self.assertNotIn("不得迁移的提示词", serialized_details)
            self.assertNotIn("不得迁移的密钥", serialized_details)
            self.assertNotIn("业务名称", serialized_details)
            self.assertNotIn("敏感复核正文", serialized_details)
            self.assertNotIn("prompt", serialized_details)
            self.assertNotIn("token", serialized_details)

            second_run = backfill_legacy_global_ai_data(connection)
            self.assertEqual(second_run, {key: 0 for key in second_run})
            second_enrichment = enrich_legacy_crm_read_models(connection)
            self.assertEqual(
                second_enrichment,
                {"conversations": 0, "insights": 0, "action_proposals": 0},
            )

            savepoint = connection.begin_nested()
            with self.assertRaises(IntegrityError):
                connection.execute(
                    text(
                        """
                        INSERT INTO ai_conversation (
                            conversation_no, domain, channel, status, source_system,
                            legacy_type, legacy_id, created_at, updated_at
                        ) VALUES (
                            'DUPLICATE-LEGACY-REF', 'crm', 'web', 'completed', 'crm',
                            'assistant_conversation', '11', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
            savepoint.rollback()

        stage_three_downgrade = self._alembic("downgrade", "20260830_0100")
        self.assertEqual(stage_three_downgrade.returncode, 0, stage_three_downgrade.stderr)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM ai_action_proposal")), 0)
            conversation_payload = connection.scalar(text("SELECT metadata_json FROM ai_conversation"))
            self.assertEqual(json.loads(conversation_payload)["context_summary"], {"projects": 2})
            insight_payload = connection.scalar(text("SELECT payload_json FROM ai_insight"))
            self.assertEqual(json.loads(insight_payload), {"model_name": "glm-5.2", "legacy": True})
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM assistant_conversation")), 1)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM crm_project_insight")), 1)

        stage_three_upgrade = self._alembic("upgrade", "20260830_0200")
        self.assertEqual(stage_three_upgrade.returncode, 0, stage_three_upgrade.stderr)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM ai_action_proposal")), 1)

        downgraded = self._alembic("downgrade", "20260808_0100")
        self.assertEqual(downgraded.returncode, 0, downgraded.stderr)
        remaining_tables = set(inspect(self.engine).get_table_names())
        self.assertFalse(expected_tables & remaining_tables)
        self.assertTrue({"assistant_conversation", "crm_project_insight", "audit_log"}.issubset(remaining_tables))
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM assistant_conversation")), 1)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM crm_project_insight")), 1)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM audit_log")), 2)


if __name__ == "__main__":
    unittest.main()
