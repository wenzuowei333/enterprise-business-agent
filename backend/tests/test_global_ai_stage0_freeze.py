from app.api.routes import crm_assistant, exceptions
from app.core.config import Settings
from app.services.seed_stage1 import PERMISSION_SEEDS


CRM_AI_ROUTES = {
    ("GET", "/crm/assistant/runtime"),
    ("GET", "/crm/assistant/agents"),
    ("GET", "/crm/assistant/messages"),
    ("DELETE", "/crm/assistant/messages"),
    ("POST", "/crm/assistant/messages"),
    ("POST", "/crm/assistant/messages/{message_id}/cancel"),
    ("POST", "/crm/assistant/project-draft"),
    ("POST", "/crm/assistant/daily-judgements"),
    ("GET", "/crm/assistant/actions/page"),
    ("GET", "/crm/assistant/insights/page"),
    ("POST", "/crm/assistant/insights/{insight_id}/review"),
}

EXCEPTION_AI_ROUTES = {
    ("POST", "/exceptions/{case_no}/diagnoses"),
    ("GET", "/exception-jobs/page"),
    ("GET", "/exception-jobs/{job_id}"),
    ("POST", "/exception-jobs/{job_id}/retry"),
    ("POST", "/exception-jobs/{job_id}/cancel"),
    ("GET", "/exception-diagnoses/quality"),
    ("POST", "/exception-diagnoses/{diagnosis_id}/feedback"),
    ("POST", "/exceptions/{case_no}/actions/validate"),
    ("POST", "/exceptions/{case_no}/actions"),
    ("GET", "/exception-actions/{action_id}"),
    ("GET", "/exception-policies"),
    ("PUT", "/exception-policies"),
    ("PATCH", "/exception-policies"),
}


def _route_contract(router) -> set[tuple[str, str]]:  # noqa: ANN001
    return {
        (method, route.path)
        for route in router.routes
        for method in (route.methods or set())
        if method not in {"HEAD", "OPTIONS"}
    }


def test_future_global_ai_flags_are_default_off() -> None:
    fields = Settings.model_fields
    names = {
        "exception_ai_global_enabled",
        "exception_ai_crm_enabled",
        "exception_ai_data_enabled",
        "exception_ai_finance_enabled",
        "exception_ai_global_actions_enabled",
        "exception_ai_high_risk_actions_enabled",
    }
    assert {name: fields[name].default for name in names} == {name: False for name in names}


def test_existing_ai_route_contract_is_frozen() -> None:
    assert CRM_AI_ROUTES <= _route_contract(crm_assistant.router)
    assert EXCEPTION_AI_ROUTES <= _route_contract(exceptions.router)


def test_existing_ai_skill_contract_is_frozen() -> None:
    assert {skill["operation"] for skill in crm_assistant.ASSISTANT_SKILLS} == {
        "dashboard.summary",
        "project.progress_analysis",
        "action.pending_list",
        "followup.draft",
        "project.draft",
        "task.create_from_context",
        "action.confirmation",
        "agent.status",
        "ai.daily_judgement",
    }


def test_existing_ai_permissions_are_frozen() -> None:
    permission_codes = {row[0] for row in PERMISSION_SEEDS}
    assert {
        "crm_insight.view",
        "crm_insight.export",
        "crm_insight.generate",
        "crm_insight.review",
        "exception_center.view",
        "exception_center.diagnose",
        "exception_center.manage",
        "exception_center.action_execute",
        "exception_center.policy_manage",
    } <= permission_codes
