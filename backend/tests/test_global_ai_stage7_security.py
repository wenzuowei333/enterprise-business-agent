from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.api.routes.global_ai_actions import router
from app.core.config import Settings
from app.schemas.global_ai import ControlledActionExecuteRequest, ControlledCrmActionReviewRequest
from app.services.global_ai_orchestrator import global_ai_orchestrator


ACTION_CENTER_READ_PERMISSIONS = {
    "crm_insight.review",
    "exception_center.action_execute",
}


def _current_user_dependency(route):  # noqa: ANN001
    return next(dependency.call for dependency in route.dependant.dependencies if dependency.name == "current_user")


def test_global_ai_release_flags_fail_closed_and_orchestrator_has_no_tools() -> None:
    fields = Settings.model_fields
    flag_names = {
        "exception_ai_global_enabled",
        "exception_ai_crm_enabled",
        "exception_ai_data_enabled",
        "exception_ai_finance_enabled",
        "exception_ai_global_actions_enabled",
        "exception_ai_high_risk_actions_enabled",
    }
    assert {name: fields[name].default for name in flag_names} == {name: False for name in flag_names}
    assert global_ai_orchestrator.registered_tools == frozenset()


def test_all_controlled_action_routes_keep_explicit_permission_dependencies() -> None:
    expected = {
        ("GET", "/ai/actions/catalog"): {"required": ACTION_CENTER_READ_PERMISSIONS},
        ("GET", "/ai/actions/proposals"): {"required": ACTION_CENTER_READ_PERMISSIONS},
        ("GET", "/ai/actions/proposals/{proposal_no}"): {"required": ACTION_CENTER_READ_PERMISSIONS},
        ("GET", "/ai/actions/executions"): {"required": ACTION_CENTER_READ_PERMISSIONS},
        ("POST", "/ai/actions/exceptions/{case_no}/validate"): {
            "permission_code": "exception_center.action_execute"
        },
        ("POST", "/ai/actions/proposals/{proposal_no}/execute"): {
            "permission_code": "exception_center.action_execute"
        },
        ("POST", "/ai/actions/proposals/{proposal_no}/crm-review"): {
            "permission_code": "crm_insight.review"
        },
    }
    actual = {}
    for route in router.routes:
        dependency = _current_user_dependency(route)
        closure = inspect.getclosurevars(dependency).nonlocals
        for method in route.methods or set():
            if method not in {"HEAD", "OPTIONS"}:
                actual[(method, route.path)] = closure
    assert actual == expected


@pytest.mark.parametrize(
    ("request_model", "payload"),
    [
        (
            ControlledActionExecuteRequest,
            {
                "expected_updated_at": "2026-08-30T00:00:00Z",
                "confirmation": False,
                "idempotency_key": "stage7-action",
                "validation_token": "stage7-validation-token",
            },
        ),
        (
            ControlledCrmActionReviewRequest,
            {
                "expected_updated_at": "2026-08-30T00:00:00Z",
                "confirmation": False,
                "decision": "accept",
                "idempotency_key": "stage7-review",
            },
        ),
    ],
)
def test_controlled_writes_cannot_be_submitted_without_human_confirmation(request_model, payload) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError):
        request_model.model_validate(payload)
