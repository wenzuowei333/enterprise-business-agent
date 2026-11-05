import unittest

from sqlalchemy import UniqueConstraint

from app.models import (
    AiActionExecution,
    AiActionProposal,
    AiContextSnapshotRecord,
    AiConversation,
    AiInsight,
    AiMessage,
    AiSecurityEvent,
    AiUsageEvent,
    AssistantConversation,
    CrmProjectInsight,
)


class GlobalAiStageTwoModelTest(unittest.TestCase):
    def test_unified_tables_and_legacy_sources_coexist(self):
        expected_tables = {
            AiConversation: "ai_conversation",
            AiMessage: "ai_message",
            AiInsight: "ai_insight",
            AiContextSnapshotRecord: "ai_context_snapshot",
            AiActionProposal: "ai_action_proposal",
            AiActionExecution: "ai_action_execution",
            AiUsageEvent: "ai_usage_event",
            AiSecurityEvent: "ai_security_event",
        }
        self.assertEqual({model.__tablename__ for model in expected_tables}, set(expected_tables.values()))
        self.assertEqual(AssistantConversation.__tablename__, "assistant_conversation")
        self.assertEqual(CrmProjectInsight.__tablename__, "crm_project_insight")

    def test_every_unified_table_has_a_legacy_dedupe_constraint(self):
        for model in (
            AiConversation,
            AiMessage,
            AiInsight,
            AiContextSnapshotRecord,
            AiActionProposal,
            AiActionExecution,
            AiUsageEvent,
            AiSecurityEvent,
        ):
            constraints = [
                constraint
                for constraint in model.__table__.constraints
                if isinstance(constraint, UniqueConstraint)
            ]
            column_sets = [{column.name for column in constraint.columns} for constraint in constraints]
            self.assertIn(
                {"source_system", "legacy_type", "legacy_id"},
                column_sets,
                f"{model.__tablename__} lacks the legacy backfill dedupe key",
            )

    def test_model_does_not_store_credentials_or_raw_provider_prompts(self):
        forbidden = {"token", "api_key", "secret", "credential", "prompt", "raw_prompt"}
        for model in (
            AiConversation,
            AiMessage,
            AiInsight,
            AiContextSnapshotRecord,
            AiActionProposal,
            AiActionExecution,
            AiUsageEvent,
            AiSecurityEvent,
        ):
            columns = {column.name for column in model.__table__.columns}
            self.assertFalse(columns & forbidden, f"{model.__tablename__} stores forbidden fields")


if __name__ == "__main__":
    unittest.main()
