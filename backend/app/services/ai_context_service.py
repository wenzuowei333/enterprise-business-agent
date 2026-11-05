from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from typing import Any

from app.schemas.global_ai import AiContextPayload, AiContextRequest, AiContextSnapshot

AiContextAdapter = Callable[[AiContextRequest], AiContextPayload]

_SENSITIVE_MARKERS = {
    "api_key",
    "authorization",
    "contact",
    "email",
    "mobile",
    "password",
    "phone",
    "secret",
    "token",
    "密码",
    "密钥",
    "手机号",
    "联系人",
    "电话",
    "邮箱",
}
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SECRET_RE = re.compile(r"(?i)\b(?:bearer\s+|sk-[a-z0-9_-]{12,}|(?:api[_ -]?key|password|secret|token)\s*[:=]\s*)\S+")


def _redact_context(value: Any, *, key: str | None = None) -> Any:
    normalized_key = (key or "").strip().casefold()
    if normalized_key and any(marker in normalized_key for marker in _SENSITIVE_MARKERS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): _redact_context(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_redact_context(item) for item in list(value)[:200]]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        text = _PHONE_RE.sub("[REDACTED_PHONE]", value[:4000])
        text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
        return _SECRET_RE.sub("[REDACTED_SECRET]", text)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4000]


class AiContextProvider:
    """Registry for permission-aware, read-only domain context adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, AiContextAdapter] = {}
        self._allowed_fields: dict[str, frozenset[str]] = {}
        self._required_permissions: dict[str, frozenset[str]] = {}

    @property
    def registered_domains(self) -> frozenset[str]:
        return frozenset(self._adapters)

    def register(
        self,
        domain: str,
        adapter: AiContextAdapter,
        *,
        allowed_fields: Iterable[str],
        required_permissions: Iterable[str] = (),
    ) -> None:
        normalized = domain.strip()
        fields = frozenset(item.strip() for item in allowed_fields if item.strip())
        if not normalized or not fields:
            raise ValueError("AI context domain and allowed_fields are required")
        if normalized in self._adapters:
            raise ValueError(f"AI context domain is already registered: {normalized}")
        self._adapters[normalized] = adapter
        self._allowed_fields[normalized] = fields
        self._required_permissions[normalized] = frozenset(
            item.strip() for item in required_permissions if item.strip()
        )

    def build(self, request: AiContextRequest) -> AiContextSnapshot:
        adapter = self._adapters.get(request.domain)
        if adapter is None:
            raise KeyError(f"AI context domain is not registered: {request.domain}")
        missing_permissions = self._required_permissions[request.domain] - set(request.permission_codes)
        if missing_permissions:
            raise PermissionError(
                f"AI context permission denied for domain {request.domain}: "
                + ", ".join(sorted(missing_permissions))
            )
        payload = adapter(request)
        allowed = self._allowed_fields[request.domain]
        redacted_fields = sorted(set(payload.fields) - allowed)
        scoped = {key: value for key, value in payload.fields.items() if key in allowed}
        return AiContextSnapshot(
            domain=request.domain,
            context_version=payload.context_version,
            structured_fields=_redact_context(scoped),
            source_refs=list(dict.fromkeys(payload.source_refs)),
            redacted_fields=redacted_fields,
        )
