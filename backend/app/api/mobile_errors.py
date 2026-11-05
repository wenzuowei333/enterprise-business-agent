from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def mobile_error_payload(
    *,
    code: str,
    message: str,
    request_id: str,
    field_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "field_errors": field_errors or [],
        "request_id": request_id,
    }


def _is_mobile(request: Request) -> bool:
    return request.url.path.startswith("/api/v1/mobile/")


def _is_external_v2(request: Request) -> bool:
    return request.url.path.startswith("/api/external/v2/")


def _is_external(request: Request) -> bool:
    return request.url.path.startswith("/api/external/")


def external_error_payload(
    *, code: str, message: str, request_id: str, details: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or [], "request_id": request_id}}


def web_error_payload(
    *,
    code: str,
    message: str,
    request_id: str,
    module: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    case_no: str | None = None,
    retryable: bool = False,
    action_path: str | None = None,
    field_errors: list[dict[str, Any]] | None = None,
    compatibility_detail: Any | None = None,
) -> dict[str, Any]:
    """Return the Web error contract while preserving FastAPI's legacy detail field."""
    return {
        "error_code": code,
        "message": message,
        "request_id": request_id,
        "module": module,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "case_no": case_no,
        "retryable": retryable,
        "action_path": action_path,
        "field_errors": field_errors or [],
        "detail": message if compatibility_detail is None else jsonable_encoder(compatibility_detail),
    }


def _web_module(request: Request) -> str | None:
    parts = [part for part in request.url.path.split("/") if part]
    if len(parts) >= 3 and parts[:2] == ["api", "v1"]:
        return parts[2]
    return None


def _web_detail(detail: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(detail, str):
        return detail, {}
    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("detail") or "Request failed"
        context = {
            key: detail.get(key)
            for key in ("error_code", "module", "resource_type", "resource_id", "case_no", "retryable", "action_path")
            if detail.get(key) is not None
        }
        return str(message), context
    return "Request failed", {}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id") or uuid.uuid4().hex


def install_mobile_error_contract(app: FastAPI) -> None:
    @app.middleware("http")
    async def mobile_request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        response = await call_next(request)
        if _is_external(request):
            from app.services.external_api_service import finalize_external_usage

            finalize_external_usage(request, response.status_code)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(HTTPException)
    async def mobile_http_error(request: Request, exc: HTTPException):
        if _is_external_v2(request):
            message = exc.detail if isinstance(exc.detail, str) else "Request failed"
            return JSONResponse(
                status_code=exc.status_code,
                content=external_error_payload(code=f"http_{exc.status_code}", message=message, request_id=_request_id(request)),
                headers=exc.headers,
            )
        if not _is_mobile(request):
            message, context = _web_detail(exc.detail)
            return JSONResponse(
                status_code=exc.status_code,
                content=web_error_payload(
                    code=str(context.get("error_code") or f"http_{exc.status_code}"),
                    message=message,
                    request_id=_request_id(request),
                    module=context.get("module") or _web_module(request),
                    resource_type=context.get("resource_type"),
                    resource_id=str(context["resource_id"]) if context.get("resource_id") is not None else None,
                    case_no=context.get("case_no"),
                    retryable=bool(context.get("retryable", exc.status_code >= 500)),
                    action_path=context.get("action_path"),
                    compatibility_detail=exc.detail,
                ),
                headers=exc.headers,
            )
        message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
        return JSONResponse(
            status_code=exc.status_code,
            content=mobile_error_payload(
                code=f"http_{exc.status_code}",
                message=message,
                request_id=_request_id(request),
            ),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def mobile_validation_error(request: Request, exc: RequestValidationError):
        if _is_external_v2(request):
            details = [
                {"field": ".".join(str(part) for part in error.get("loc", [])[1:]), "message": error.get("msg", "Invalid input")}
                for error in exc.errors()
            ]
            return JSONResponse(
                status_code=422,
                content=external_error_payload(
                    code="validation_error", message="Request validation failed", request_id=_request_id(request), details=details
                ),
            )
        if not _is_mobile(request):
            field_errors = [
                {
                    "field": ".".join(str(part) for part in error.get("loc", [])[1:]),
                    "message": error.get("msg", "Invalid input"),
                }
                for error in exc.errors()
            ]
            return JSONResponse(
                status_code=422,
                content=web_error_payload(
                    code="validation_error",
                    message="Request validation failed",
                    request_id=_request_id(request),
                    module=_web_module(request),
                    field_errors=field_errors,
                    compatibility_detail=exc.errors(),
                ),
            )
        field_errors = [
            {
                "field": ".".join(str(part) for part in error.get("loc", [])[1:]),
                "message": error.get("msg", "输入不合法"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=mobile_error_payload(
                code="validation_error",
                message="请检查输入内容",
                request_id=_request_id(request),
                field_errors=field_errors,
            ),
        )

    @app.exception_handler(Exception)
    async def mobile_unexpected_error(request: Request, exc: Exception):
        if _is_external_v2(request):
            request_id = _request_id(request)
            logger.exception("Unhandled external API error request_id=%s", request_id, exc_info=exc)
            return JSONResponse(
                status_code=500,
                content=external_error_payload(code="internal_error", message="Service temporarily unavailable", request_id=request_id),
            )
        if not _is_mobile(request):
            request_id = _request_id(request)
            logger.exception("Unhandled Web API error request_id=%s", request_id, exc_info=exc)
            return JSONResponse(
                status_code=500,
                content=web_error_payload(
                    code="internal_error",
                    message="Service temporarily unavailable",
                    request_id=request_id,
                    module=_web_module(request),
                    retryable=True,
                ),
            )
        request_id = _request_id(request)
        logger.exception("Unhandled mobile API error request_id=%s", request_id, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=mobile_error_payload(
                code="internal_error",
                message="服务暂时不可用，请稍后重试",
                request_id=request_id,
            ),
        )
