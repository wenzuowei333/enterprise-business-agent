from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    AiActionProposal,
    AssistantConversation,
    CrmProject,
    CrmProjectCustomerTask,
    CrmProjectInsight,
    User,
    WorkItem,
)
from app.schemas.crm import (
    CrmAssistantAgentStatus,
    CrmAssistantConversationPublic,
    CrmAssistantJudgementResult,
    CrmAssistantMessageCancelRequest,
    CrmAssistantMessageRequest,
    CrmAssistantMessageResponse,
    CrmAssistantProjectDraftRequest,
    CrmAssistantProjectDraftResponse,
    CrmAssistantRuntime,
    CrmAssistantSkill,
    CrmProjectInsightPage,
    CrmProjectInsightPublic,
    CrmProjectInsightReviewRequest,
)
from app.schemas.global_ai import GlobalAiResult
from app.services.audit_service import write_audit_log
from app.services.crm_access_service import crm_project_scope_filter, crm_task_scope_filter, crm_work_item_scope_filter
from app.services.crm_project_service import generated_code
from app.services.crm_ai_migration_service import (
    aggregate_conversation_counts,
    build_crm_context_snapshot,
    cancel_unified_conversation,
    consistency_report,
    crm_ai_unified_enabled,
    delete_unified_conversations,
    list_unified_conversations,
    list_unified_insights,
    mirror_audit_event,
    mirror_conversation,
    mirror_insight,
    mirror_insight_review,
)
from app.services.controlled_action_service import (
    controlled_actions_enabled,
    record_controlled_crm_execution_event,
)
from app.services.global_business_context_service import build_global_business_context_snapshot
from app.services.hermes_ai_service import call_hermes_chat, hermes_configured, hermes_provider_host
from app.services.permission_service import get_final_permission_codes, has_permission

router = APIRouter(prefix="/crm/assistant", tags=["crm-assistant"])

ASSISTANT_SKILLS = [
    {
        "operation": "dashboard.summary",
        "label": "经营首页摘要",
        "description": "汇总当前活跃项目、超期客户任务、待支持事项和下一步处理顺序。",
        "write_effect": "readonly",
    },
    {
        "operation": "project.progress_analysis",
        "label": "项目推进分析",
        "description": "按项目识别推进风险、执行阻塞、反馈缺口和闭环建议。",
        "write_effect": "readonly",
    },
    {
        "operation": "action.pending_list",
        "label": "待办优先级",
        "description": "从客户任务与待支持事项中整理今天优先处理清单。",
        "write_effect": "readonly",
    },
    {
        "operation": "followup.draft",
        "label": "跟进话术草稿",
        "description": "基于上下文生成客户跟进话术或记录草稿，需人工确认后落库。",
        "write_effect": "draft_only",
    },
    {
        "operation": "project.draft",
        "label": "项目申请草稿",
        "description": "生成项目申请字段建议，需带入项目申请并经审批后才能落库。",
        "write_effect": "draft_only",
    },
    {
        "operation": "task.create_from_context",
        "label": "任务建议",
        "description": "根据上下文给出任务拆解建议，正式待办需人工转入待支持事项。",
        "write_effect": "draft_only",
    },
    {
        "operation": "action.confirmation",
        "label": "动作确认队列",
        "description": "查看 AI 判断、采纳、忽略或转为待支持事项。",
        "write_effect": "review_required",
    },
    {
        "operation": "agent.status",
        "label": "Agent 状态",
        "description": "查看模型接入状态、技能清单和调用记录，不展示密钥明文。",
        "write_effect": "readonly",
    },
    {
        "operation": "ai.daily_judgement",
        "label": "每日 AI 判断",
        "description": "生成可复核的风险/机会判断，落入 AI 洞察列表，可转待办。",
        "write_effect": "review_required",
    },
]


def _safe_limit(limit: int, max_limit: int = 50) -> int:
    return max(1, min(limit, max_limit))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _count_stmt(db: Session, stmt: Select[tuple[Any, ...]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _count_by_column(db: Session, stmt: Select[tuple[Any, ...]], column: Any) -> dict[str, int]:
    subquery = stmt.with_only_columns(column).order_by(None).subquery()
    grouped_column = list(subquery.c)[0]
    rows = db.execute(select(grouped_column, func.count()).select_from(subquery).group_by(grouped_column)).all()
    return {str(key or "未设置"): int(count or 0) for key, count in rows}


def _runtime() -> CrmAssistantRuntime:
    return CrmAssistantRuntime(
        configured=hermes_configured(),
        model=settings.hermes_model if hermes_configured() else None,
        provider_host=hermes_provider_host(),
        source="exception_center_global_ai" if crm_ai_unified_enabled() else "project_base_hermes",
        direct_db_enabled=False,
        skills=[CrmAssistantSkill(**skill) for skill in ASSISTANT_SKILLS],
    )


def _user_permissions(db: Session, user: User) -> dict[str, bool]:
    return {
        "crm_project.view": has_permission(db, user, "crm_project.view"),
        "crm_task.view": has_permission(db, user, "crm_task.view"),
        "crm_issue.view": has_permission(db, user, "crm_issue.view"),
        "crm_insight.view": has_permission(db, user, "crm_insight.view"),
        "crm_insight.generate": has_permission(db, user, "crm_insight.generate"),
        "crm_insight.review": has_permission(db, user, "crm_insight.review"),
    }


def _build_migrated_context(
    db: Session,
    user: User,
    *,
    required_permission: str,
) -> tuple[dict[str, Any], Any]:
    raw_context = _build_context(db, user)
    permission_codes = get_final_permission_codes(db, user)
    if crm_ai_unified_enabled():
        snapshot = build_global_business_context_snapshot(
            db,
            user,
            crm_context=raw_context,
            permission_codes=permission_codes,
            required_permission=required_permission,
        )
    else:
        snapshot = build_crm_context_snapshot(
            raw_context,
            actor_user_id=user.id,
            permission_codes=permission_codes,
            required_permission=required_permission,
        )
    return snapshot.structured_fields, snapshot


def _require_ai_permission(db: Session, user: User, permission_code: str) -> None:
    if has_permission(db, user, permission_code):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing CRM AI permission: {permission_code}",
    )


def _global_ai_audit_fields(result: GlobalAiResult | None, request_id: str) -> dict[str, Any]:
    if result is None:
        return {
            "ai_request_id": request_id,
            "ai_contract_version": "global-ai-result.v1",
            "ai_status": "degraded",
        }
    return {
        "ai_request_id": result.request_id,
        "ai_contract_version": result.contract_version,
        "ai_status": result.status,
        "ai_latency_ms": result.latency_ms,
        "ai_attempts": result.attempts,
        "ai_usage": result.usage.model_dump(mode="json"),
    }


def _build_context(db: Session, user: User) -> dict[str, Any]:
    permissions = _user_permissions(db, user)
    now = datetime.now(timezone.utc)
    context: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "employee_code": user.employee_code,
        },
        "permission_flags": permissions,
        "summary": {
            "active_projects": 0,
            "open_tasks": 0,
            "blocked_tasks": 0,
            "support_tasks": 0,
            "overdue_tasks": 0,
            "open_work_items": 0,
        },
        "projects": [],
        "risky_tasks": [],
        "open_work_items": [],
    }
    if permissions["crm_project.view"]:
        active_stmt = crm_project_scope_filter(select(CrmProject).where(CrmProject.status == "active"), db, user)
        context["summary"]["active_projects"] = _count_stmt(db, active_stmt)
        projects = list(
            db.scalars(
                active_stmt.order_by(CrmProject.updated_at.desc(), CrmProject.id.desc()).limit(8)
            ).all()
        )
        context["projects"] = [
            {
                "id": row.id,
                "project_code": row.project_code,
                "project_name": row.project_name,
                "status": row.status,
                "due_date": row.due_date,
                "next_step_status": row.next_step_status,
                "next_step_action": row.next_step_action,
                "project_manager_user_id": row.project_manager_user_id,
            }
            for row in projects
        ]
    if permissions["crm_task.view"]:
        open_task_stmt = crm_task_scope_filter(
            select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.is_closed.is_(False)),
            db,
            user,
        )
        context["summary"]["open_tasks"] = _count_stmt(db, open_task_stmt)
        context["summary"]["blocked_tasks"] = _count_stmt(db, open_task_stmt.where(CrmProjectCustomerTask.is_blocked.is_(True)))
        context["summary"]["support_tasks"] = _count_stmt(
            db,
            open_task_stmt.where(
                or_(
                    CrmProjectCustomerTask.need_support.is_(True),
                    CrmProjectCustomerTask.need_manager_support.is_(True),
                    CrmProjectCustomerTask.need_boss_decision.is_(True),
                )
            ),
        )
        context["summary"]["overdue_tasks"] = _count_stmt(
            db,
            open_task_stmt.where(
                CrmProjectCustomerTask.feedback_due_at.is_not(None),
                CrmProjectCustomerTask.feedback_due_at < now,
            ),
        )
        risky_tasks = list(
            db.scalars(
                open_task_stmt.where(
                    or_(
                        CrmProjectCustomerTask.is_blocked.is_(True),
                        CrmProjectCustomerTask.need_support.is_(True),
                        CrmProjectCustomerTask.need_manager_support.is_(True),
                        CrmProjectCustomerTask.need_boss_decision.is_(True),
                        CrmProjectCustomerTask.feedback_due_at < now,
                    )
                )
                .order_by(CrmProjectCustomerTask.feedback_due_at.asc().nullslast(), CrmProjectCustomerTask.id.desc())
                .limit(12)
            ).all()
        )
        context["risky_tasks"] = [
            {
                "id": row.id,
                "project_id": row.project_id,
                "task_code": row.task_code,
                "customer_code": row.customer_code,
                "customer_name": row.customer_name_snapshot,
                "executor": row.executor_name_snapshot,
                "feedback_due_at": row.feedback_due_at,
                "status": row.status,
                "is_blocked": row.is_blocked,
                "need_support": row.need_support,
                "need_manager_support": row.need_manager_support,
                "need_boss_decision": row.need_boss_decision,
                "latest_blocker_reason": row.latest_blocker_reason,
                "latest_owner_next_action": row.latest_owner_next_action,
                "last_followup_at": row.last_followup_at,
            }
            for row in risky_tasks
        ]
    if permissions["crm_issue.view"]:
        work_item_stmt = crm_work_item_scope_filter(select(WorkItem).where(WorkItem.status.in_(["open", "processing"])), db, user)
        context["summary"]["open_work_items"] = _count_stmt(db, work_item_stmt)
        work_items = list(
            db.scalars(work_item_stmt.order_by(WorkItem.updated_at.desc(), WorkItem.id.desc()).limit(10)).all()
        )
        context["open_work_items"] = [
            {
                "id": row.id,
                "item_no": row.item_no,
                "title": row.title,
                "priority": row.priority,
                "status": row.status,
                "project_id": row.project_id,
                "customer_code": row.customer_code,
                "due_at": row.due_at,
            }
            for row in work_items
        ]
    return jsonable_encoder(context)


def _system_prompt() -> str:
    return (
        "你是异常中心统一 AI 平台中的经营协同助手，承接原客户 CRM 的 Hermes 业务能力。"
        "只能基于消息中提供且已按当前用户权限裁剪的管理中心上下文回答，不得声称已直连外部数据库。"
        "availability 标记为不可用的业务域不得推断、补全或引用；金额为 null 时必须说明受字段权限限制。"
        "不要输出数据库连接、密钥、Token 或内部实现细节。"
        "写入类建议必须先进入人工复核、审批或待办，不得绕过权限直接落库。"
        "回答要面向经营管理，按风险、原因、建议动作组织，中文、简洁、可执行。"
    )


def _operation_instruction(operation: str | None) -> str:
    instructions = {
        "dashboard.summary": "请生成一份经营首页摘要，包含总体态势、风险数字、优先处理顺序。",
        "project.progress_analysis": "请分析项目推进风险，指出阻塞任务、反馈缺口和细节审批人需要关注的下一步动作。",
        "action.pending_list": "请输出今天优先处理清单，按紧急程度排序。",
        "followup.draft": "请生成客户跟进话术或跟进记录草稿，提醒需要人工确认后保存。",
        "project.draft": "请生成项目申请草稿建议，强调需要人工带入项目申请并经过审批。",
        "task.create_from_context": "请拆解待办任务建议，但不要声称已经创建任务。",
        "action.confirmation": "请解释当前 AI 判断确认队列中的风险、建议动作和人工复核要求。",
        "agent.status": "请说明当前 Agent 的运行状态、可用技能和审计边界，不输出密钥。",
        "ai.daily_judgement": "请生成每日 AI 判断摘要，重点覆盖风险、机会和建议动作。",
    }
    return instructions.get(operation or "", "请结合上下文回答用户问题，必要时给出下一步动作。")


def _project_draft_from_payload(payload: CrmAssistantProjectDraftRequest) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    due_date = today + timedelta(days=payload.due_days)
    customer_name = _clean_text(payload.customer_name) or "目标客户"
    target = _clean_text(payload.target) or "完成一轮有效客户触达、反馈收集和下一步动作确认"
    risk_note = _clean_text(payload.risk_note) or "需确认客户范围、执行人、反馈截止时间和闭环标准"
    project_name = _clean_text(payload.project_name) or f"{customer_name}专项推进"
    purpose = _clean_text(payload.purpose) or f"围绕{target}推进客户经营动作，沉淀可复盘的客户反馈和责任动作。"
    customer_scope_note = _clean_text(payload.customer_scope_note) or f"{customer_name}相关客户，提交前需在客户任务底盘中逐一选择。"
    minimum_action = "每个客户至少完成一次有效跟进，记录执行动作、客户反馈、当前需求和下一步动作。"
    closure_standard = "客户任务均已补充有效反馈；阻塞、待支持和需决策事项已进入待支持或审批闭环；细节审批人完成复盘确认。"
    return {
        "project": {
            "project_name": project_name,
            "project_type": _clean_text(payload.project_type) or "客户项目",
            "business_line": _clean_text(payload.business_line),
            "purpose": purpose,
            "customer_scope_note": customer_scope_note,
            "start_date": today.isoformat(),
            "due_date": due_date.isoformat(),
            "minimum_action": minimum_action,
            "closure_standard": closure_standard,
            "status": "submitted",
            "approval_status": "draft",
        },
        "tasks": [],
        "suggestions": {
            "target": target,
            "risk_note": risk_note,
            "recommended_priority": "high" if any(keyword in risk_note for keyword in ["紧急", "风险", "阻塞", "超期"]) else "normal",
            "recommended_due_days": payload.due_days,
            "manual_checks": [
                "在项目申请中选择真实客户主数据，生成客户任务底盘。",
                "补齐每条客户任务的执行人、问题点、轮次目标和反馈截止时间。",
                "确认审批处理人后再提交审批。",
            ],
        },
    }


def _project_draft_message(draft: dict[str, Any]) -> str:
    project = draft["project"]
    suggestions = draft["suggestions"]
    return "\n".join(
        [
            "已生成项目申请草稿，尚未写入正式项目。",
            f"项目名称：{project['project_name']}",
            f"项目类型：{project['project_type']}；业务线：{project.get('business_line') or '-'}",
            f"建议周期：{project['start_date']} 至 {project['due_date']}，优先级：{suggestions['recommended_priority']}",
            f"项目目的：{project['purpose']}",
            f"最小动作：{project['minimum_action']}",
            "下一步：进入项目申请，选择客户、补齐执行人与反馈截止时间，再提交审批。",
        ]
    )


def _rule_answer(context: dict[str, Any], message: str, operation: str | None, *, warning: str | None = None) -> str:
    crm_context = context.get("crm") if isinstance(context.get("crm"), dict) else context
    summary = crm_context["summary"]
    risky_tasks = crm_context["risky_tasks"]
    work_items = crm_context["open_work_items"]
    first_task = risky_tasks[0] if risky_tasks else None
    first_item = work_items[0] if work_items else None
    lines = [
        "项目推进智能体摘要：",
        f"活跃项目 {summary['active_projects']} 个，未闭环客户任务 {summary['open_tasks']} 条，阻塞 {summary['blocked_tasks']} 条，需支持 {summary['support_tasks']} 条，超期 {summary['overdue_tasks']} 条。",
        f"待支持事项 {summary['open_work_items']} 条。",
    ]
    if first_task:
        lines.append(
            f"优先关注客户任务：{first_task['customer_name']}，原因："
            f"{first_task.get('latest_blocker_reason') or ('已超期' if first_task.get('feedback_due_at') else '需要支持')}。"
        )
    elif first_item:
        lines.append(f"优先关注待支持事项：{first_item['title']}，优先级：{first_item['priority']}。")
    else:
        lines.append("当前没有明显高风险对象，可继续检查今日应跟客户和项目下一步动作。")
    if operation == "ai.daily_judgement":
        lines.append("已按规则生成可复核 AI 判断；请在 AI 洞察区查看、采纳、忽略或转待办。")
    elif operation == "followup.draft":
        lines.append("跟进草稿建议：先确认客户当前反馈，再明确下一次行动、负责人和预计完成时间。")
    elif operation == "task.create_from_context":
        lines.append("任务拆解建议：把阻塞原因、支持责任人、截止时间和闭环口径拆成独立待办。")
    if warning:
        lines.append(f"模型调用未完成，已使用规则摘要兜底：{warning}")
    return "\n".join(lines)


def _insight_scope_filter(stmt: Select[tuple[Any, ...]], db: Session, user: User) -> Select[tuple[Any, ...]]:
    filters: list[Any] = [CrmProjectInsight.generated_by_user_id == user.id]
    if has_permission(db, user, "crm_project.view"):
        project_ids = crm_project_scope_filter(select(CrmProject.id), db, user)
        filters.append(CrmProjectInsight.project_id.in_(project_ids))
    if has_permission(db, user, "crm_task.view"):
        task_ids = crm_task_scope_filter(select(CrmProjectCustomerTask.id), db, user)
        filters.append(CrmProjectInsight.task_id.in_(task_ids))
    if not filters:
        return stmt.where(false())
    return stmt.where(or_(*filters))


def _assert_insight_visible(db: Session, user: User, insight: CrmProjectInsight) -> None:
    if insight.generated_by_user_id == user.id:
        return
    if insight.project_id and has_permission(db, user, "crm_project.view"):
        project = db.scalar(crm_project_scope_filter(select(CrmProject).where(CrmProject.id == insight.project_id), db, user))
        if project is not None:
            return
    if insight.task_id and has_permission(db, user, "crm_task.view"):
        task = db.scalar(
            crm_task_scope_filter(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.id == insight.task_id), db, user)
        )
        if task is not None:
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM insight not found")


def _insight_exists_today(db: Session, task: CrmProjectCustomerTask, insight_type: str, now: datetime) -> bool:
    day_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    existing = db.scalar(
        select(CrmProjectInsight.id)
        .where(
            CrmProjectInsight.task_id == task.id,
            CrmProjectInsight.insight_type == insight_type,
            CrmProjectInsight.status.in_(["draft", "accepted"]),
            CrmProjectInsight.created_at >= day_start,
        )
        .limit(1)
    )
    return existing is not None


def _task_insight_spec(task: CrmProjectCustomerTask, now: datetime) -> dict[str, Any] | None:
    if task.is_blocked:
        return {
            "type": "execution_risk",
            "risk": "high",
            "opportunity": None,
            "confidence": 88,
            "summary": f"{task.customer_name_snapshot} 的项目任务存在阻塞，可能影响本轮推进闭环。",
            "action": task.latest_blocker_note or task.latest_blocker_reason or "请负责人补充阻塞原因，并指定支持人和下一步处理时间。",
        }
    if task.need_boss_decision or task.need_manager_support or task.need_support:
        risk = "high" if task.need_boss_decision or task.need_manager_support else "medium"
        return {
            "type": "support_risk",
            "risk": risk,
            "opportunity": None,
            "confidence": 82,
            "summary": f"{task.customer_name_snapshot} 需要协同支持，当前执行可能无法单人闭环。",
            "action": task.latest_owner_next_action or "请中台确认支持事项、责任人和完成时限。",
        }
    if task.feedback_due_at and task.feedback_due_at < now and not task.is_closed:
        return {
            "type": "followup_overdue",
            "risk": "medium",
            "opportunity": None,
            "confidence": 78,
            "summary": f"{task.customer_name_snapshot} 已超过反馈时间，存在跟进断点。",
            "action": task.latest_owner_next_action or "请负责人当天补充客户反馈，并更新下一步动作。",
        }
    if task.minimum_action_done and not task.is_closed and not task.need_support:
        return {
            "type": "conversion_opportunity",
            "risk": "low",
            "opportunity": "medium",
            "confidence": 70,
            "summary": f"{task.customer_name_snapshot} 已完成最低动作，可进一步判断是否进入深度经营或转化推进。",
            "action": "请复核客户反馈质量，确认是否需要升级经营动作或形成复盘结论。",
        }
    return None


def _generate_judgements(db: Session, user: User, *, limit: int = 30) -> tuple[list[CrmProjectInsight], int]:
    if not has_permission(db, user, "crm_task.view"):
        return [], 0
    now = datetime.now(timezone.utc)
    task_stmt = crm_task_scope_filter(
        select(CrmProjectCustomerTask).where(
            CrmProjectCustomerTask.is_closed.is_(False),
            or_(
                CrmProjectCustomerTask.is_blocked.is_(True),
                CrmProjectCustomerTask.need_support.is_(True),
                CrmProjectCustomerTask.need_manager_support.is_(True),
                CrmProjectCustomerTask.need_boss_decision.is_(True),
                CrmProjectCustomerTask.feedback_due_at < now,
                CrmProjectCustomerTask.minimum_action_done.is_(True),
            ),
        ),
        db,
        user,
    )
    tasks = list(
        db.scalars(
            task_stmt.order_by(CrmProjectCustomerTask.feedback_due_at.asc().nullslast(), CrmProjectCustomerTask.id.desc()).limit(limit)
        ).all()
    )
    created: list[CrmProjectInsight] = []
    skipped = 0
    for task in tasks:
        spec = _task_insight_spec(task, now)
        if spec is None:
            skipped += 1
            continue
        if _insight_exists_today(db, task, spec["type"], now):
            skipped += 1
            continue
        row = CrmProjectInsight(
            insight_no=generated_code("INS"),
            project_id=task.project_id,
            task_id=task.id,
            customer_code=task.customer_code,
            insight_type=spec["type"],
            summary=spec["summary"],
            suggested_action=spec["action"],
            risk_level=spec["risk"],
            opportunity_level=spec["opportunity"],
            confidence_score=spec["confidence"],
            status="draft",
            evidence_json={
                "task_code": task.task_code,
                "customer_name": task.customer_name_snapshot,
                "executor": task.executor_name_snapshot,
                "feedback_due_at": task.feedback_due_at.isoformat() if task.feedback_due_at else None,
                "is_blocked": task.is_blocked,
                "need_support": task.need_support,
                "need_manager_support": task.need_manager_support,
                "need_boss_decision": task.need_boss_decision,
                "latest_blocker_reason": task.latest_blocker_reason,
                "latest_owner_next_action": task.latest_owner_next_action,
                "last_followup_at": task.last_followup_at.isoformat() if task.last_followup_at else None,
            },
            source="rule",
            generated_by_user_id=user.id,
            payload_json={"generator": "crm_assistant", "generated_at": now.isoformat()},
        )
        db.add(row)
        if crm_ai_unified_enabled():
            mirror_insight(db, row)
        created.append(row)
    return created, skipped


@router.get("/runtime", response_model=CrmAssistantRuntime)
def get_crm_assistant_runtime(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> CrmAssistantRuntime:
    _require_ai_permission(db, current_user, "crm_insight.view")
    return _runtime()


@router.get("/agents", response_model=CrmAssistantAgentStatus)
def get_crm_assistant_agent_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> CrmAssistantAgentStatus:
    _require_ai_permission(db, current_user, "crm_insight.view")
    runtime = _runtime()
    migration_status = consistency_report(db, user_id=current_user.id)
    base_stmt = select(AssistantConversation).where(AssistantConversation.user_id == current_user.id)
    if migration_status["read_source"] == "unified":
        all_calls = list_unified_conversations(db, user_id=current_user.id, limit=None)
        recent_calls = all_calls[:20]
        counts = aggregate_conversation_counts(all_calls)
    else:
        all_calls = list(
            db.scalars(
                base_stmt.order_by(AssistantConversation.created_at.desc(), AssistantConversation.id.desc())
            ).all()
        )
        recent_calls = all_calls[:20]
        counts = {
            "status_counts": _count_by_column(db, base_stmt, AssistantConversation.status),
            "source_counts": _count_by_column(db, base_stmt, AssistantConversation.source),
            "operation_counts": _count_by_column(db, base_stmt, AssistantConversation.operation),
        }
    pending_stmt = _insight_scope_filter(
        select(CrmProjectInsight).where(CrmProjectInsight.status == "draft"),
        db,
        current_user,
    )
    pending_actions = _count_stmt(db, pending_stmt)
    return CrmAssistantAgentStatus(
        runtime=runtime,
        status_counts=counts["status_counts"],
        source_counts=counts["source_counts"],
        operation_counts=counts["operation_counts"],
        pending_actions=pending_actions,
        recent_calls=recent_calls,
        last_call_at=recent_calls[0].created_at if recent_calls else None,
        migration_status=migration_status,
    )


@router.get("/messages", response_model=list[CrmAssistantConversationPublic])
def list_crm_assistant_messages(
    channel: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> list[AssistantConversation | CrmAssistantConversationPublic]:
    _require_ai_permission(db, current_user, "crm_insight.view")
    migration_status = consistency_report(db, user_id=current_user.id)
    if migration_status["read_source"] == "unified":
        return list_unified_conversations(
            db,
            user_id=current_user.id,
            channel=channel,
            limit=_safe_limit(limit),
        )
    stmt = select(AssistantConversation).where(AssistantConversation.user_id == current_user.id)
    if channel:
        stmt = stmt.where(AssistantConversation.channel == channel)
    return list(db.scalars(stmt.order_by(AssistantConversation.created_at.desc(), AssistantConversation.id.desc()).limit(_safe_limit(limit))).all())


@router.delete("/messages")
def clear_crm_assistant_messages(
    request: Request,
    channel: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> dict[str, int]:
    _require_ai_permission(db, current_user, "crm_insight.review")
    stmt = select(AssistantConversation).where(AssistantConversation.user_id == current_user.id)
    if channel:
        stmt = stmt.where(AssistantConversation.channel == channel)
    rows = list(db.scalars(stmt).all())
    count = len(rows)
    if crm_ai_unified_enabled():
        delete_unified_conversations(db, [row.id for row in rows])
    for row in rows:
        db.delete(row)
    audit = write_audit_log(
        db,
        action_type="crm_assistant_clear_messages",
        resource_type="assistant_conversation",
        resource_id=channel or "all",
        user=current_user,
        request=request,
        after_data={"deleted": count, "channel": channel, "permission": "crm_insight.review"},
    )
    if crm_ai_unified_enabled():
        mirror_audit_event(db, audit)
    db.commit()
    return {"deleted": count}


@router.post("/messages", response_model=CrmAssistantMessageResponse)
def send_crm_assistant_message(
    payload: CrmAssistantMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> CrmAssistantMessageResponse:
    _require_ai_permission(db, current_user, "crm_insight.view")
    context, context_snapshot = _build_migrated_context(
        db,
        current_user,
        required_permission="crm_insight.view",
    )
    runtime = _runtime()
    insights_created = 0
    source = "rule"
    model_name = None
    status_value = "completed"
    warning = None
    ai_request_id = f"crm-ai-{uuid4()}"
    ai_result: GlobalAiResult | None = None

    def capture_ai_result(result: GlobalAiResult) -> None:
        nonlocal ai_result
        ai_result = result

    if payload.operation == "ai.daily_judgement":
        _require_ai_permission(db, current_user, "crm_insight.generate")
        insights, _skipped = _generate_judgements(db, current_user)
        insights_created = len(insights)
    if runtime.configured:
        try:
            assistant_message = call_hermes_chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {
                        "role": "user",
                        "content": (
                            f"操作: {payload.operation or 'auto'}\n"
                            f"操作说明: {_operation_instruction(payload.operation)}\n"
                            f"用户问题: {payload.message}\n"
                            "项目底座上下文 JSON: "
                            f"{json.dumps(jsonable_encoder(context), ensure_ascii=False)}"
                        ),
                    },
                ],
                temperature=0.2,
                request_id=ai_request_id,
                domain="crm",
                operation=(
                    "crm.ai.daily_judgement"
                    if payload.operation == "ai.daily_judgement"
                    else "crm.assistant.message"
                ),
                source_refs=context_snapshot.source_refs,
                on_result=capture_ai_result,
            )
            source = "hermes"
            model_name = ai_result.model if ai_result else settings.hermes_model
        except RuntimeError as exc:
            warning = str(exc)[:240]
            assistant_message = _rule_answer(context, payload.message, payload.operation, warning=warning)
            source = "rule_fallback"
            status_value = "completed_with_warning"
    else:
        assistant_message = _rule_answer(context, payload.message, payload.operation, warning=warning)
    crm_context = context.get("crm") if isinstance(context.get("crm"), dict) else context
    row = AssistantConversation(
        conversation_no=generated_code("ASST"),
        user_id=current_user.id,
        username_snapshot=current_user.username,
        channel=payload.channel or "web",
        session_id=payload.session_id,
        context_type=payload.context_type,
        context_id=payload.context_id,
        operation=payload.operation,
        user_message=payload.message,
        assistant_message=assistant_message,
        source=source,
        model_name=model_name,
        status=status_value,
        payload_json={
            "context_summary": crm_context["summary"],
            "context_version": context_snapshot.context_version,
            "context_domain": context_snapshot.domain,
            "runtime": runtime.model_dump(),
            "warning": warning,
            "insights_created": insights_created,
            "global_ai_result": ai_result.model_dump(mode="json") if ai_result else None,
        },
    )
    db.add(row)
    unified_conversation = None
    if crm_ai_unified_enabled():
        unified_conversation = mirror_conversation(db, row, context_snapshot, ai_result)
    audit = write_audit_log(
        db,
        action_type="crm_assistant_message",
        resource_type="assistant_conversation",
        resource_id=row.conversation_no,
        user=current_user,
        request=request,
        after_data={
            "operation": payload.operation,
            "source": source,
            "status": status_value,
            "channel": payload.channel or "web",
            "context_type": payload.context_type,
            "context_id": payload.context_id,
            "message_length": len(payload.message),
            "insights_created": insights_created,
            "permission": "crm_insight.generate" if payload.operation == "ai.daily_judgement" else "crm_insight.view",
            **_global_ai_audit_fields(ai_result, ai_request_id),
        },
    )
    if crm_ai_unified_enabled():
        mirror_audit_event(
            db,
            audit,
            result=ai_result,
            conversation=unified_conversation,
        )
    db.commit()
    db.refresh(row)
    return CrmAssistantMessageResponse(message=row, runtime=runtime, insights_created=insights_created)


@router.post("/messages/{message_id}/cancel", response_model=CrmAssistantConversationPublic)
def cancel_crm_assistant_message(
    message_id: int,
    payload: CrmAssistantMessageCancelRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> AssistantConversation:
    _require_ai_permission(db, current_user, "crm_insight.review")
    row = db.get(AssistantConversation, message_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM assistant message not found")
    before_data = jsonable_encoder(CrmAssistantConversationPublic.model_validate(row))
    payload_json = row.payload_json if isinstance(row.payload_json, dict) else {"previous_payload": row.payload_json}
    payload_json = dict(payload_json or {})
    payload_json["cancelled"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "by_user_id": current_user.id,
        "reason": _clean_text(payload.reason),
    }
    row.status = "cancelled"
    row.payload_json = payload_json
    if crm_ai_unified_enabled():
        cancel_unified_conversation(db, row)
    audit = write_audit_log(
        db,
        action_type="crm_assistant_cancel_message",
        resource_type="assistant_conversation",
        resource_id=row.conversation_no,
        user=current_user,
        request=request,
        before_data=before_data,
        after_data={"status": row.status, "reason": payload.reason, "permission": "crm_insight.review"},
    )
    if crm_ai_unified_enabled():
        mirror_audit_event(db, audit)
    db.commit()
    db.refresh(row)
    return row


@router.post("/project-draft", response_model=CrmAssistantProjectDraftResponse)
def generate_crm_assistant_project_draft(
    payload: CrmAssistantProjectDraftRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> CrmAssistantProjectDraftResponse:
    _require_ai_permission(db, current_user, "crm_insight.generate")
    runtime = _runtime()
    _context, context_snapshot = _build_migrated_context(
        db,
        current_user,
        required_permission="crm_insight.generate",
    )
    draft = _project_draft_from_payload(payload)
    user_message = "\n".join(
        [
            "生成项目申请草稿",
            f"项目名称：{payload.project_name or '-'}",
            f"客户/范围：{payload.customer_name or payload.customer_scope_note or '-'}",
            f"目标：{payload.target or payload.purpose or '-'}",
            f"风险提示：{payload.risk_note or '-'}",
        ]
    )
    source = "rule"
    model_name = None
    status_value = "completed"
    warning = None
    ai_request_id = f"crm-ai-{uuid4()}"
    ai_result: GlobalAiResult | None = None

    def capture_ai_result(result: GlobalAiResult) -> None:
        nonlocal ai_result
        ai_result = result

    assistant_message = _project_draft_message(draft)
    if runtime.configured:
        try:
            assistant_message = call_hermes_chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {
                        "role": "user",
                        "content": (
                            "请基于下面的项目申请草稿，输出一段面向业务负责人可读的草稿说明。"
                            "必须说明该草稿未落库、需人工带入项目申请并经过审批。\n"
                            "草稿 JSON: "
                            f"{json.dumps(jsonable_encoder(draft), ensure_ascii=False)}"
                        ),
                    },
                ],
                temperature=0.15,
                request_id=ai_request_id,
                domain="crm",
                operation="crm.project.draft",
                source_refs=context_snapshot.source_refs,
                on_result=capture_ai_result,
            )
            source = "hermes"
            model_name = ai_result.model if ai_result else settings.hermes_model
        except RuntimeError as exc:
            warning = str(exc)[:240]
            source = "rule_fallback"
            status_value = "completed_with_warning"
            assistant_message = _project_draft_message(draft) + f"\n模型调用未完成，已使用规则草稿兜底：{warning}"
    row = AssistantConversation(
        conversation_no=generated_code("ASST"),
        user_id=current_user.id,
        username_snapshot=current_user.username,
        channel=payload.channel or "web",
        context_type="crm_project_draft",
        operation="project.draft",
        user_message=user_message,
        assistant_message=assistant_message,
        source=source,
        model_name=model_name,
        status=status_value,
        payload_json={
            "draft": draft,
            "runtime": runtime.model_dump(),
            "warning": warning,
            "global_ai_result": ai_result.model_dump(mode="json") if ai_result else None,
        },
    )
    db.add(row)
    unified_conversation = None
    if crm_ai_unified_enabled():
        unified_conversation = mirror_conversation(db, row, context_snapshot, ai_result)
    audit = write_audit_log(
        db,
        action_type="crm_assistant_project_draft",
        resource_type="assistant_conversation",
        resource_id=row.conversation_no,
        user=current_user,
        request=request,
        after_data={
            "source": source,
            "status": status_value,
            "project_name": draft["project"]["project_name"],
            "permission": "crm_insight.generate",
            **_global_ai_audit_fields(ai_result, ai_request_id),
        },
    )
    if crm_ai_unified_enabled():
        mirror_audit_event(
            db,
            audit,
            result=ai_result,
            conversation=unified_conversation,
        )
    db.commit()
    db.refresh(row)
    return CrmAssistantProjectDraftResponse(draft=draft, message=row, runtime=runtime)


@router.post("/daily-judgements", response_model=CrmAssistantJudgementResult)
def generate_crm_assistant_daily_judgements(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> CrmAssistantJudgementResult:
    _require_ai_permission(db, current_user, "crm_insight.generate")
    insights, skipped = _generate_judgements(db, current_user)
    audit = write_audit_log(
        db,
        action_type="crm_assistant_generate_judgements",
        resource_type="crm_project_insight",
        resource_id="daily",
        user=current_user,
        request=request,
        after_data={"created": len(insights), "skipped": skipped, "permission": "crm_insight.generate"},
    )
    if crm_ai_unified_enabled():
        mirror_audit_event(db, audit)
    db.commit()
    for row in insights:
        db.refresh(row)
    return CrmAssistantJudgementResult(created=len(insights), skipped=skipped, insights=insights)


@router.get("/actions/page", response_model=CrmProjectInsightPage)
def list_crm_assistant_actions(
    status_value: str | None = Query(default="draft"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> CrmProjectInsightPage:
    _require_ai_permission(db, current_user, "crm_insight.view")
    safe_limit = _safe_limit(limit, 100)
    safe_offset = _safe_offset(offset)
    stmt = _insight_scope_filter(select(CrmProjectInsight), db, current_user)
    if consistency_report(db, user_id=current_user.id)["read_source"] == "unified":
        legacy_ids = list(db.scalars(stmt.with_only_columns(CrmProjectInsight.id)).all())
        items, total = list_unified_insights(
            db,
            legacy_ids=legacy_ids,
            status_value=status_value,
            insight_type=None,
            limit=safe_limit,
            offset=safe_offset,
        )
        return CrmProjectInsightPage(items=items, total=total, limit=safe_limit, offset=safe_offset)
    if status_value:
        stmt = stmt.where(CrmProjectInsight.status == status_value)
    total = _count_stmt(db, stmt)
    items = list(
        db.scalars(stmt.order_by(CrmProjectInsight.created_at.desc(), CrmProjectInsight.id.desc()).offset(safe_offset).limit(safe_limit)).all()
    )
    return CrmProjectInsightPage(items=items, total=total, limit=safe_limit, offset=safe_offset)


@router.get("/insights/page", response_model=CrmProjectInsightPage)
def list_crm_assistant_insights(
    status_value: str | None = None,
    insight_type: str | None = None,
    project_id: int | None = None,
    customer_code: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> CrmProjectInsightPage:
    _require_ai_permission(db, current_user, "crm_insight.view")
    safe_limit = _safe_limit(limit, 100)
    safe_offset = _safe_offset(offset)
    stmt = _insight_scope_filter(select(CrmProjectInsight), db, current_user)
    if insight_type:
        stmt = stmt.where(CrmProjectInsight.insight_type == insight_type)
    if project_id:
        stmt = stmt.where(CrmProjectInsight.project_id == project_id)
    if customer_code:
        stmt = stmt.where(CrmProjectInsight.customer_code == customer_code)
    if consistency_report(db, user_id=current_user.id)["read_source"] == "unified":
        legacy_ids = list(db.scalars(stmt.with_only_columns(CrmProjectInsight.id)).all())
        items, total = list_unified_insights(
            db,
            legacy_ids=legacy_ids,
            status_value=status_value,
            insight_type=insight_type,
            limit=safe_limit,
            offset=safe_offset,
        )
        return CrmProjectInsightPage(items=items, total=total, limit=safe_limit, offset=safe_offset)
    if status_value:
        stmt = stmt.where(CrmProjectInsight.status == status_value)
    total = _count_stmt(db, stmt)
    items = list(
        db.scalars(stmt.order_by(CrmProjectInsight.created_at.desc(), CrmProjectInsight.id.desc()).offset(safe_offset).limit(safe_limit)).all()
    )
    return CrmProjectInsightPage(items=items, total=total, limit=safe_limit, offset=safe_offset)


@router.post("/insights/{insight_id}/review", response_model=CrmProjectInsightPublic)
def review_crm_assistant_insight(
    insight_id: int,
    payload: CrmProjectInsightReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> CrmProjectInsight:
    _require_ai_permission(db, current_user, "crm_insight.review")
    insight = db.get(CrmProjectInsight, insight_id)
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM insight not found")
    _assert_insight_visible(db, current_user, insight)
    before_data = jsonable_encoder(CrmProjectInsightPublic.model_validate(insight))
    now = datetime.now(timezone.utc)
    work_item_created = False
    if payload.action == "reject":
        insight.status = "rejected"
        insight.review_note = payload.note
    elif payload.action == "accept":
        insight.status = "accepted"
        insight.review_note = payload.note
    elif payload.action == "task":
        existing = db.scalar(
            select(WorkItem).where(WorkItem.source_type == "crm_ai_insight", WorkItem.source_id == insight.insight_no).limit(1)
        )
        if existing is None:
            item = WorkItem(
                item_no=generated_code("WI"),
                source_type="crm_ai_insight",
                source_id=insight.insight_no,
                resource_type="crm_project_insight",
                resource_id=str(insight.id),
                project_id=insight.project_id,
                customer_code=insight.customer_code,
                item_type="crm_ai_insight",
                title=insight.summary[:255],
                detail=insight.suggested_action,
                priority="high" if insight.risk_level == "high" else "normal",
                status="open",
                assignee_user_id=current_user.id,
            )
            db.add(item)
            work_item_created = True
        insight.status = "accepted"
        insight.review_note = payload.note or "已转为待支持事项"
    insight.reviewed_by_user_id = current_user.id
    insight.reviewed_at = now
    if crm_ai_unified_enabled():
        execution = mirror_insight_review(
            db,
            insight,
            action=payload.action,
            reviewer_user_id=current_user.id,
            work_item_created=work_item_created,
        )
        if controlled_actions_enabled() and execution is not None:
            proposal = db.get(AiActionProposal, execution.proposal_id)
            if proposal is not None:
                record_controlled_crm_execution_event(
                    db,
                    user=current_user,
                    proposal=proposal,
                    execution=execution,
                    decision=payload.action,
                )
    audit = write_audit_log(
        db,
        action_type="crm_assistant_review_insight",
        resource_type="crm_project_insight",
        resource_id=insight.insight_no,
        user=current_user,
        request=request,
        before_data=before_data,
        after_data={
            "action": payload.action,
            "status": insight.status,
            "note": payload.note,
            "work_item_created": work_item_created,
            "permission": "crm_insight.review",
        },
    )
    if crm_ai_unified_enabled():
        mirror_audit_event(db, audit)
    db.commit()
    db.refresh(insight)
    return insight
