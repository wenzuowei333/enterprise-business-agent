from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.engine import Connection


CRM_AUDIT_ACTIONS = (
    "crm_assistant_message",
    "crm_assistant_project_draft",
    "crm_assistant_clear_messages",
    "crm_assistant_cancel_message",
    "crm_assistant_generate_judgements",
    "crm_assistant_review_insight",
)

BACKFILL_COUNTER_KEYS = (
    "conversations",
    "messages",
    "insights",
    "context_snapshots",
    "usage_events",
    "security_events",
)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str) and item.strip()))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _legacy_row(table: Table, connection: Connection, legacy_type: str, legacy_id: str):
    return connection.execute(
        select(table).where(
            table.c.source_system == "crm",
            table.c.legacy_type == legacy_type,
            table.c.legacy_id == legacy_id,
        )
    ).mappings().first()


def _reflect_table(name: str, metadata: MetaData, connection: Connection) -> Table:
    # Backfill only needs local columns. Avoid recursively reflecting unrelated FK
    # targets so partial migration fixtures remain valid.
    return Table(name, metadata, autoload_with=connection, resolve_fks=False)


def _insert_legacy_row(
    table: Table,
    connection: Connection,
    *,
    legacy_type: str,
    legacy_id: str,
    values: dict[str, Any],
) -> tuple[Any, bool]:
    existing = _legacy_row(table, connection, legacy_type, legacy_id)
    if existing is not None:
        return existing, False
    result = connection.execute(
        table.insert().values(
            source_system="crm",
            legacy_type=legacy_type,
            legacy_id=legacy_id,
            **values,
        )
    )
    inserted_id = result.inserted_primary_key[0]
    return connection.execute(select(table).where(table.c.id == inserted_id)).mappings().one(), True


def _confidence(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        score = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if score > 1:
        score /= Decimal("100")
    return min(Decimal("1"), max(Decimal("0"), score))


def _conversation_result(payload: Any) -> dict[str, Any]:
    return _mapping(_mapping(payload).get("global_ai_result"))


def _source_refs(payload: Any) -> list[str]:
    return _list_of_strings(_conversation_result(payload).get("source_refs"))


def _review_status(status: Any) -> str:
    normalized = str(status or "draft").strip().lower()
    return {
        "draft": "pending",
        "accepted": "accepted",
        "rejected": "rejected",
        "ignored": "rejected",
    }.get(normalized, normalized[:40] or "pending")


def _audit_detail(row: dict[str, Any], after_data: dict[str, Any]) -> dict[str, Any]:
    allowed_after_keys = (
        "operation",
        "source",
        "status",
        "channel",
        "context_type",
        "context_id",
        "permission",
        "ai_request_id",
        "ai_contract_version",
        "ai_status",
        "ai_latency_ms",
        "ai_attempts",
        "created",
        "skipped",
        "deleted",
        "work_item_created",
    )
    return {
        "legacy_action_type": row["action_type"],
        "role_code": row.get("role_code"),
        "fields": {key: after_data[key] for key in allowed_after_keys if key in after_data},
        "migration_version": "global-ai-stage2.v1",
    }


def _audit_outcome(after_data: dict[str, Any]) -> str:
    value = str(after_data.get("ai_status") or after_data.get("status") or "completed").lower()
    if value in {"failed", "rejected", "cancelled", "degraded", "completed_with_warning"}:
        return value[:40]
    return "completed"


def _find_conversation_by_legacy_number(
    connection: Connection,
    conversation_table: Table,
    resource_id: Any,
):
    if not resource_id:
        return None
    return connection.execute(
        select(conversation_table).where(conversation_table.c.conversation_no == str(resource_id))
    ).mappings().first()


def _backfill_conversations(
    connection: Connection,
    legacy: Table,
    tables: dict[str, Table],
    counters: dict[str, int],
) -> None:
    for source_row in connection.execute(select(legacy).order_by(legacy.c.id)).mappings():
        legacy_id = str(source_row["id"])
        payload = source_row.get("payload_json")
        result = _conversation_result(payload)
        created_at = source_row["created_at"]
        conversation, created = _insert_legacy_row(
            tables["ai_conversation"],
            connection,
            legacy_type="assistant_conversation",
            legacy_id=legacy_id,
            values={
                "conversation_no": source_row["conversation_no"],
                "domain": "crm",
                "channel": source_row.get("channel") or "web",
                "session_id": source_row.get("session_id"),
                "context_type": source_row.get("context_type"),
                "context_id": source_row.get("context_id"),
                "operation": source_row.get("operation"),
                "status": source_row.get("status") or "completed",
                "actor_user_id": source_row.get("user_id"),
                "created_by_user_id": source_row.get("user_id"),
                "model_name": source_row.get("model_name"),
                "metadata_json": payload,
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
        counters["conversations"] += int(created)

        message_common = {
            "conversation_id": conversation["id"],
            "status": source_row.get("status") or "completed",
            "created_by_user_id": source_row.get("user_id"),
            "request_id": result.get("request_id"),
            "model_name": result.get("model") or source_row.get("model_name"),
            "contract_version": result.get("contract_version"),
            "source_refs_json": _source_refs(payload),
            "created_at": created_at,
            "updated_at": created_at,
        }
        _, message_created = _insert_legacy_row(
            tables["ai_message"],
            connection,
            legacy_type="assistant_conversation.user_message",
            legacy_id=legacy_id,
            values={
                **message_common,
                "message_no": f"AI-CRM-MSG-{legacy_id}-USER",
                "sequence_no": 1,
                "role": "user",
                "content": source_row["user_message"],
                "payload_json": None,
            },
        )
        counters["messages"] += int(message_created)
        _, message_created = _insert_legacy_row(
            tables["ai_message"],
            connection,
            legacy_type="assistant_conversation.assistant_message",
            legacy_id=legacy_id,
            values={
                **message_common,
                "message_no": f"AI-CRM-MSG-{legacy_id}-ASSISTANT",
                "sequence_no": 2,
                "role": "assistant",
                "content": source_row["assistant_message"],
                "payload_json": result or None,
            },
        )
        counters["messages"] += int(message_created)

        context_fields = {
            "context_type": source_row.get("context_type"),
            "context_id": source_row.get("context_id"),
            "operation": source_row.get("operation"),
        }
        _, context_created = _insert_legacy_row(
            tables["ai_context_snapshot"],
            connection,
            legacy_type="assistant_conversation.context",
            legacy_id=legacy_id,
            values={
                "snapshot_no": f"AI-CRM-CTX-{legacy_id}",
                "conversation_id": conversation["id"],
                "domain": "crm",
                "context_version": "legacy-crm-assistant.v1",
                "resource_type": source_row.get("context_type"),
                "resource_id": source_row.get("context_id"),
                "structured_fields_json": context_fields,
                "source_refs_json": _source_refs(payload),
                "redacted_fields_json": [],
                "created_by_user_id": source_row.get("user_id"),
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
        counters["context_snapshots"] += int(context_created)


def _backfill_insights(
    connection: Connection,
    legacy: Table,
    table: Table,
    counters: dict[str, int],
) -> None:
    for source_row in connection.execute(select(legacy).order_by(legacy.c.id)).mappings():
        legacy_id = str(source_row["id"])
        evidence = source_row.get("evidence_json")
        source_refs = _list_of_strings(_mapping(evidence).get("source_refs"))
        if not source_refs and isinstance(evidence, list):
            source_refs = _list_of_strings(evidence)
        resource_type = "crm_project"
        resource_id = str(source_row["project_id"]) if source_row.get("project_id") is not None else None
        if resource_id is None and source_row.get("task_id") is not None:
            resource_type = "crm_project_customer_task"
            resource_id = str(source_row["task_id"])
        if resource_id is None and source_row.get("customer_code"):
            resource_type = "customer_master"
            resource_id = str(source_row["customer_code"])
        _, created = _insert_legacy_row(
            table,
            connection,
            legacy_type="crm_project_insight",
            legacy_id=legacy_id,
            values={
                "insight_no": source_row["insight_no"],
                "conversation_id": None,
                "domain": "crm",
                "insight_type": source_row["insight_type"],
                "resource_type": resource_type,
                "resource_id": resource_id,
                "summary": source_row["summary"],
                "suggested_action": source_row.get("suggested_action"),
                "risk_level": source_row.get("risk_level"),
                "opportunity_level": source_row.get("opportunity_level"),
                "confidence_score": _confidence(source_row.get("confidence_score")),
                "status": "active",
                "review_status": _review_status(source_row.get("status")),
                "reviewed_by_user_id": source_row.get("reviewed_by_user_id"),
                "reviewed_at": source_row.get("reviewed_at"),
                "review_note": source_row.get("review_note"),
                "created_by_user_id": source_row.get("generated_by_user_id"),
                "source_refs_json": source_refs,
                "evidence_json": evidence,
                "model_name": _mapping(source_row.get("payload_json")).get("model_name"),
                "payload_json": source_row.get("payload_json"),
                "created_at": source_row["created_at"],
                "updated_at": source_row["updated_at"],
            },
        )
        counters["insights"] += int(created)


def _backfill_audits(
    connection: Connection,
    legacy: Table,
    tables: dict[str, Table],
    counters: dict[str, int],
) -> None:
    stmt = select(legacy).where(legacy.c.action_type.in_(CRM_AUDIT_ACTIONS)).order_by(legacy.c.id)
    for source_row in connection.execute(stmt).mappings():
        legacy_id = str(source_row["id"])
        after_data = _mapping(source_row.get("after_data"))
        request_id = after_data.get("ai_request_id")
        outcome = _audit_outcome(after_data)
        _, created = _insert_legacy_row(
            tables["ai_security_event"],
            connection,
            legacy_type="audit_log",
            legacy_id=legacy_id,
            values={
                "event_no": f"AI-CRM-SEC-{legacy_id}",
                "event_type": source_row["action_type"],
                "severity": "warning" if outcome in {"failed", "degraded", "completed_with_warning"} else "info",
                "outcome": outcome,
                "actor_user_id": source_row.get("user_id"),
                "service_identity": "exception_ai_service" if request_id else None,
                "domain": "crm",
                "resource_type": source_row.get("resource_type"),
                "resource_id": source_row.get("resource_id"),
                "request_id": request_id,
                "detail_json": _audit_detail(source_row, after_data),
                "occurred_at": source_row["created_at"],
                "created_at": source_row["created_at"],
            },
        )
        counters["security_events"] += int(created)

        if not request_id:
            continue
        conversation = _find_conversation_by_legacy_number(
            connection, tables["ai_conversation"], source_row.get("resource_id")
        )
        conversation_payload = _mapping(conversation.get("metadata_json")) if conversation else {}
        global_result = _conversation_result(conversation_payload)
        usage = _mapping(after_data.get("ai_usage"))
        if not usage:
            usage = _mapping(global_result.get("usage"))
        assistant_message = None
        if conversation:
            assistant_message = connection.execute(
                select(tables["ai_message"]).where(
                    tables["ai_message"].c.conversation_id == conversation["id"],
                    tables["ai_message"].c.role == "assistant",
                )
            ).mappings().first()
        _, usage_created = _insert_legacy_row(
            tables["ai_usage_event"],
            connection,
            legacy_type="audit_log.ai_usage",
            legacy_id=legacy_id,
            values={
                "event_no": f"AI-CRM-USAGE-{legacy_id}",
                "conversation_id": conversation["id"] if conversation else None,
                "message_id": assistant_message["id"] if assistant_message else None,
                "insight_id": None,
                "request_id": request_id,
                "provider_request_id": global_result.get("provider_request_id"),
                "service_identity": "exception_ai_service",
                "domain": "crm",
                "operation": after_data.get("operation") or source_row["action_type"],
                "status": after_data.get("ai_status") or global_result.get("status") or "completed",
                "model_name": global_result.get("model"),
                "prompt_version": global_result.get("prompt_version"),
                "contract_version": after_data.get("ai_contract_version") or global_result.get("contract_version"),
                "latency_ms": after_data.get("ai_latency_ms") or global_result.get("latency_ms"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "attempts": after_data.get("ai_attempts") or global_result.get("attempts") or 1,
                "metadata_json": {"migration_version": "global-ai-stage2.v1"},
                "occurred_at": source_row["created_at"],
                "created_at": source_row["created_at"],
            },
        )
        counters["usage_events"] += int(usage_created)


def backfill_legacy_global_ai_data(connection: Connection) -> dict[str, int]:
    """Copy legacy CRM AI records without changing or deleting their source rows."""

    inspector = inspect(connection)
    required_targets = {
        "ai_conversation",
        "ai_message",
        "ai_insight",
        "ai_context_snapshot",
        "ai_usage_event",
        "ai_security_event",
    }
    existing_tables = set(inspector.get_table_names())
    missing_targets = sorted(required_targets - existing_tables)
    if missing_targets:
        raise RuntimeError(f"Global AI target tables are missing: {', '.join(missing_targets)}")

    metadata = MetaData()
    target_tables = {name: _reflect_table(name, metadata, connection) for name in sorted(required_targets)}
    counters = {key: 0 for key in BACKFILL_COUNTER_KEYS}

    if "assistant_conversation" in existing_tables:
        _backfill_conversations(
            connection,
            _reflect_table("assistant_conversation", metadata, connection),
            target_tables,
            counters,
        )
    if "crm_project_insight" in existing_tables:
        _backfill_insights(
            connection,
            _reflect_table("crm_project_insight", metadata, connection),
            target_tables["ai_insight"],
            counters,
        )
    if "audit_log" in existing_tables:
        _backfill_audits(
            connection,
            _reflect_table("audit_log", metadata, connection),
            target_tables,
            counters,
        )
    return counters


def global_ai_backfill_status(connection: Connection) -> dict[str, int]:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    counts: dict[str, int] = {}
    metadata = MetaData()
    for key, table_name in (
        ("conversations", "ai_conversation"),
        ("messages", "ai_message"),
        ("insights", "ai_insight"),
        ("context_snapshots", "ai_context_snapshot"),
        ("usage_events", "ai_usage_event"),
        ("security_events", "ai_security_event"),
    ):
        if table_name not in table_names:
            counts[key] = 0
            continue
        table = _reflect_table(table_name, metadata, connection)
        counts[key] = len(connection.execute(select(table.c.id).where(table.c.source_system == "crm")).all())
    counts["checked_at_epoch"] = int(_utc_now().timestamp())
    return counts


def enrich_legacy_crm_read_models(connection: Connection) -> dict[str, int]:
    """Add reversible compatibility projections needed by the stage-three read path."""

    table_names = set(inspect(connection).get_table_names())
    required = {
        "assistant_conversation",
        "crm_project_insight",
        "ai_conversation",
        "ai_insight",
        "ai_action_proposal",
    }
    if not required.issubset(table_names):
        return {"conversations": 0, "insights": 0, "action_proposals": 0}
    metadata = MetaData()
    legacy_conversation = _reflect_table("assistant_conversation", metadata, connection)
    legacy_insight = _reflect_table("crm_project_insight", metadata, connection)
    conversation = _reflect_table("ai_conversation", metadata, connection)
    insight = _reflect_table("ai_insight", metadata, connection)
    action_proposal = _reflect_table("ai_action_proposal", metadata, connection)
    counts = {"conversations": 0, "insights": 0, "action_proposals": 0}

    legacy_conversations = {
        str(row["id"]): row
        for row in connection.execute(select(legacy_conversation)).mappings()
    }
    for target in connection.execute(
        select(conversation).where(
            conversation.c.source_system == "crm",
            conversation.c.legacy_type == "assistant_conversation",
        )
    ).mappings():
        source = legacy_conversations.get(str(target["legacy_id"]))
        if source is None:
            continue
        current = _mapping(target.get("metadata_json"))
        if current.get("projection_version") == "crm-ai-stage3.v1":
            continue
        connection.execute(
            conversation.update()
            .where(conversation.c.id == target["id"])
            .values(
                metadata_json={
                    "projection_version": "crm-ai-stage3.v1",
                    "legacy_payload": current,
                    "compatibility": {
                        "username_snapshot": source.get("username_snapshot"),
                        "source": source.get("source") or "rule",
                    },
                }
            )
        )
        counts["conversations"] += 1

    legacy_insights = {
        str(row["id"]): row for row in connection.execute(select(legacy_insight)).mappings()
    }
    for target in connection.execute(
        select(insight).where(
            insight.c.source_system == "crm",
            insight.c.legacy_type == "crm_project_insight",
        )
    ).mappings():
        source = legacy_insights.get(str(target["legacy_id"]))
        if source is None:
            continue
        current = _mapping(target.get("payload_json"))
        if current.get("projection_version") != "crm-ai-stage3.v1":
            connection.execute(
                insight.update()
                .where(insight.c.id == target["id"])
                .values(
                    payload_json={
                        "projection_version": "crm-ai-stage3.v1",
                        "legacy_payload": current,
                        "compatibility": {
                            "project_id": source.get("project_id"),
                            "task_id": source.get("task_id"),
                            "customer_code": source.get("customer_code"),
                            "source": source.get("source") or "rule",
                            "confidence_score": source.get("confidence_score"),
                            "legacy_status": source.get("status") or "draft",
                        },
                    }
                )
            )
            counts["insights"] += 1
        proposal_exists = connection.execute(
            select(action_proposal.c.id).where(
                action_proposal.c.source_system == "crm",
                action_proposal.c.legacy_type == "crm_project_insight.action_proposal",
                action_proposal.c.legacy_id == str(source["id"]),
            )
        ).first()
        if proposal_exists is None:
            status = str(source.get("status") or "draft")
            review_status = _review_status(status)
            connection.execute(
                action_proposal.insert().values(
                    proposal_no=f"AI-CRM-PROP-{source['id']}",
                    insight_id=target["id"],
                    domain="crm",
                    action_type="crm_insight.review",
                    resource_type=target.get("resource_type"),
                    resource_id=target.get("resource_id"),
                    status="proposed" if status == "draft" else "completed",
                    review_status=review_status,
                    risk_level=source.get("risk_level"),
                    requires_confirmation=True,
                    parameters_json={"suggested_action": source.get("suggested_action")},
                    source_refs_json=target.get("source_refs_json") or [],
                    created_by_user_id=source.get("generated_by_user_id"),
                    reviewed_by_user_id=source.get("reviewed_by_user_id"),
                    reviewed_at=source.get("reviewed_at"),
                    review_note=source.get("review_note"),
                    source_system="crm",
                    legacy_type="crm_project_insight.action_proposal",
                    legacy_id=str(source["id"]),
                    created_at=source["created_at"],
                    updated_at=source["updated_at"],
                )
            )
            counts["action_proposals"] += 1
    return counts


def revert_legacy_crm_read_models(connection: Connection) -> dict[str, int]:
    table_names = set(inspect(connection).get_table_names())
    required = {"ai_conversation", "ai_insight", "ai_action_proposal"}
    if not required.issubset(table_names):
        return {"conversations": 0, "insights": 0, "action_proposals": 0}
    metadata = MetaData()
    conversation = _reflect_table("ai_conversation", metadata, connection)
    insight = _reflect_table("ai_insight", metadata, connection)
    action_proposal = _reflect_table("ai_action_proposal", metadata, connection)
    counts = {"conversations": 0, "insights": 0, "action_proposals": 0}

    proposal_ids = list(
        connection.scalars(
            select(action_proposal.c.id).where(
                action_proposal.c.source_system == "crm",
                action_proposal.c.legacy_type == "crm_project_insight.action_proposal",
            )
        )
    )
    if proposal_ids:
        protected_ids: set[int] = set()
        if "ai_action_execution" in table_names:
            action_execution = _reflect_table("ai_action_execution", metadata, connection)
            protected_ids = set(
                connection.scalars(
                    select(action_execution.c.proposal_id).where(
                        action_execution.c.proposal_id.in_(proposal_ids)
                    )
                )
            )
        removable_ids = [proposal_id for proposal_id in proposal_ids if proposal_id not in protected_ids]
        if removable_ids:
            connection.execute(action_proposal.delete().where(action_proposal.c.id.in_(removable_ids)))
            counts["action_proposals"] = len(removable_ids)

    for target in connection.execute(
        select(conversation).where(
            conversation.c.source_system == "crm",
            conversation.c.legacy_type == "assistant_conversation",
        )
    ).mappings():
        current = _mapping(target.get("metadata_json"))
        if current.get("projection_version") != "crm-ai-stage3.v1":
            continue
        connection.execute(
            conversation.update()
            .where(conversation.c.id == target["id"])
            .values(metadata_json=current.get("legacy_payload"))
        )
        counts["conversations"] += 1

    for target in connection.execute(
        select(insight).where(
            insight.c.source_system == "crm",
            insight.c.legacy_type == "crm_project_insight",
        )
    ).mappings():
        current = _mapping(target.get("payload_json"))
        if current.get("projection_version") != "crm-ai-stage3.v1":
            continue
        connection.execute(
            insight.update()
            .where(insight.c.id == target["id"])
            .values(payload_json=current.get("legacy_payload"))
        )
        counts["insights"] += 1
    return counts
