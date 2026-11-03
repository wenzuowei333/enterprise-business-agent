from __future__ import annotations
import json
import re
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from app.core.config import settings


class HermesResponseError(RuntimeError):
    """Raised when the provider returns an unusable response."""


class ExceptionDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_cause_code: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    impact: str = Field(min_length=1, max_length=2000)
    recommended_steps: list[str] = Field(default_factory=list, max_length=20)
    missing_evidence: list[str] = Field(default_factory=list, max_length=50)
    disposition: Literal["actionable", "manual_review", "blocked"]

    @field_validator("root_cause_code")
    @classmethod
    def validate_root_cause_code(cls, value: str) -> str:
        normalized = value.strip()
        if not _ROOT_CAUSE_CODE_RE.fullmatch(normalized):
            raise ValueError("root_cause_code must be lowercase snake_case")
        return normalized

    @field_validator("summary", "impact")
    @classmethod
    def validate_chinese_text(cls, value: str, info: ValidationInfo) -> str:
        normalized = value.strip()
        if not _contains_han_text(normalized):
            raise ValueError(f"{info.field_name} must use Simplified Chinese")
        return normalized

    @field_validator("evidence_refs", "recommended_steps", "missing_evidence")
    @classmethod
    def normalize_string_list(cls, value: list[str], info: ValidationInfo) -> list[str]:
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if info.field_name == "evidence_refs":
            normalized = list(dict.fromkeys(normalized))
        max_item_length = 2000 if info.field_name == "recommended_steps" else 500
        if any(len(item) > max_item_length for item in normalized):
            raise ValueError(f"{info.field_name} contains an oversized item")
        if info.field_name != "evidence_refs" and any(not _contains_han_text(item) for item in normalized):
            raise ValueError(f"{info.field_name} must use Simplified Chinese")
        return normalized


_SENSITIVE_KEY_MARKERS = {
    "api_key",
    "apikey",
    "authorization",
    "bank_account",
    "contact",
    "email",
    "mobile",
    "note",
    "password",
    "phone",
    "remark",
    "secret",
    "token",
    "联系人",
    "手机号",
    "电话",
    "邮箱",
    "备注",
    "密码",
    "密钥",
}


_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


_SECRET_RE = re.compile(
    r"(?i)\b(?:bearer\s+|sk-[a-z0-9_-]{12,}|(?:api[_ -]?key|password|secret|token)\s*[:=]\s*)\S+"
)


_ROOT_CAUSE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


_HAN_TEXT_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


_CANONICAL_REF_KIND_RE = re.compile(r"[^a-z0-9_]+")


_MAX_EVIDENCE_STRING_LENGTH = 4000


def _contains_han_text(value: str) -> bool:
    return bool(_HAN_TEXT_RE.search(value))


_COMMON_EVIDENCE_KEYS = {
    "kind",
    "rule_code",
    "rule_version",
    "rule_description",
    "reason",
    "expected_rule",
    "recommended_action",
    "resource",
    "data_window",
    "affected",
    "source",
    "metadata",
    "allowed_root_cause_codes",
}


_DOMAIN_EVIDENCE_KEYS = {
    "inventory": _COMMON_EVIDENCE_KEYS
    | {
        "inventory_case_no",
        "snapshot_id",
        "batch_id",
        "data_date",
        "product",
        "warehouse",
        "observed",
        "reason_code",
        "flow_id",
        "calculation",
        "anomaly_type",
        "anomaly_flags",
        "source_batch_ids",
        "rows",
        "system_data_dates",
        "suppressed_result_ids",
        "unit_relation",
        "stock_qty",
        "platform_stock_qty",
        "system_stock_qty",
        "diff_qty",
        "system_data_date",
        "source_row_numbers",
        "result_id",
        "result_type",
        "batch",
    },
    "receivable": _COMMON_EVIDENCE_KEYS,
    "master_data": _COMMON_EVIDENCE_KEYS,
    "import": _COMMON_EVIDENCE_KEYS
    | {
        "batch",
        "errors",
        "errors_truncated",
        "content_sha256",
        "file_type",
        "original_batch",
        "duplicate_batch",
        "calendar_rule",
        "latest_committed_batch",
        "expected_data_date",
        "overdue_days",
    },
}


_NESTED_EVIDENCE_KEYS = {
    "resource": {"type", "id", "code", "name"},
    "source": {"type", "id", "batch_id", "data_date"},
    "metadata": {
        "rule_code",
        "rule_version",
        "occurrence_type",
        "occurrence_cycle",
        "batch_id",
        "batch_no",
        "file_name",
        "file_type",
        "batch_status",
        "result_id",
        "result_type",
        "severity",
        "warehouse_name",
        "platform_stock_qty",
        "system_stock_qty",
        "diff_qty",
        "system_data_date",
        "receivable_ar_balance",
        "account_ar_balance",
        "missing_fields",
        "status",
        "source",
        "issue_ids",
        "issue_type",
        "source_file_types",
        "counterpart_master_kind",
        "counterpart_code",
        "counterpart_name",
        "inventory_case_no",
        "inventory_check_batch_no",
        "original_result_type",
        "reason_code",
        "anomaly_flags",
        "systemic",
        "flow_ids",
        "result_ids",
        "snapshot_ids",
        "system_data_dates",
        "content_sha256",
        "original_batch_id",
        "calendar_rule_code",
        "expected_data_date",
        "overdue_days",
    },
    "product": {"code", "name"},
    "warehouse": {"name", "scope"},
    "batch": {
        "id",
        "batch_no",
        "data_date",
        "status",
        "file_type",
        "total_rows",
        "success_rows",
        "error_rows",
    },
    "original_batch": {"id", "batch_no", "status", "data_date", "uploaded_at"},
    "duplicate_batch": {"id", "batch_no", "status", "data_date", "uploaded_at"},
    "latest_committed_batch": {"id", "batch_no", "data_date", "uploaded_at"},
    "calendar_rule": {"rule_code", "file_type", "label", "frequency", "deadline_hour", "owner_role"},
    "observed": {"stock_qty", "locked_qty"},
    "calculation": {
        "opening_stock_qty",
        "purchase_qty",
        "sales_qty",
        "calculated_closing_qty",
        "snapshot_stock_qty",
        "diff_qty",
    },
    "data_window": {"first_seen_date", "last_seen_date"},
    "affected": {"rows", "documents", "amount", "quantity"},
    "rows": {"total", "sample", "truncated", "digest"},
    "source_batch_ids": {"total", "sample", "truncated", "digest"},
    "suppressed_result_ids": {"total", "sample", "truncated", "digest"},
    "source_row_numbers": {"total", "sample", "truncated", "digest"},
    "errors": {"id", "row_number", "error_type", "error_message"},
    "sample": {
        "id",
        "flow_id",
        "snapshot_id",
        "result_id",
        "row_number",
        "product_code",
        "product_name",
        "warehouse_name",
        "warehouse_scope",
        "stock_qty",
        "locked_qty",
        "platform_stock_qty",
        "system_stock_qty",
        "diff_qty",
        "source_row_numbers",
    },
}


_DANGEROUS_RECOMMENDATION_PATTERNS = (
    re.compile(r"\b(?:update|insert\s+into|delete\s+from|drop\s+table|truncate\s+table)\b", re.IGNORECASE),
    re.compile(
        r"\bdirect(?:ly)?\s+(?:edit|modify|update|write|overwrite|delete)\s+(?:the\s+)?"
        r"(?:database|inventory[_ ]snapshot|stock_qty|raw\s+(?:import|source)\s+file)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:set|patch|overwrite)\s+(?:inventory[_ ]snapshot\.)?stock_qty\b", re.IGNORECASE),
    re.compile(r"(?:直接|绕过[^，。；;]{0,12})(?:修改|更新|写入|覆盖|删除)(?:数据库|库存快照|原始(?:导入|源)文件|stock_qty)", re.IGNORECASE),
    re.compile(r"(?:执行|运行)(?:任意)?\s*SQL", re.IGNORECASE),
)


def redact_exception_evidence(value: Any, *, key: str | None = None) -> Any:
    """Return a JSON-safe, minimally scoped evidence copy for an external model."""
    normalized_key = (key or "").strip().lower()
    if normalized_key and any(marker in normalized_key for marker in _SENSITIVE_KEY_MARKERS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact_exception_evidence(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_exception_evidence(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        result = value[:_MAX_EVIDENCE_STRING_LENGTH]
        result = _PHONE_RE.sub("[REDACTED_PHONE]", result)
        result = _EMAIL_RE.sub("[REDACTED_EMAIL]", result)
        return _SECRET_RE.sub("[REDACTED_SECRET]", result)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_EVIDENCE_STRING_LENGTH]


def _bounded_nested_value(value: Any, *, list_limit: int, string_limit: int) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _bounded_nested_value(item, list_limit=list_limit, string_limit=string_limit)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _bounded_nested_value(item, list_limit=list_limit, string_limit=string_limit)
            for item in value[:list_limit]
        ]
    if isinstance(value, str):
        return value[:string_limit]
    return value


def _project_evidence_value(value: Any, *, field_name: str) -> Any:
    if isinstance(value, dict):
        allowed = _NESTED_EVIDENCE_KEYS.get(field_name)
        if allowed is None:
            return {}
        return {
            str(key): _project_evidence_value(item, field_name=str(key))
            for key, item in value.items()
            if str(key) in allowed
        }
    if isinstance(value, (list, tuple, set)):
        projected = []
        for item in value:
            item_field = "sample" if field_name in {"rows", "sample"} else field_name
            projected.append(_project_evidence_value(item, field_name=item_field))
        return projected
    if value is None or isinstance(value, (bool, int, float, str, datetime)):
        return value
    return str(value)


def _canonical_ref_kind(raw_kind: str) -> str:
    normalized = _CANONICAL_REF_KIND_RE.sub("_", raw_kind.strip().casefold()).strip("_")
    aliases = {
        "source_batch": "batch",
        "source_batches": "batch",
        "original_batch": "batch",
        "duplicate_batch": "batch",
        "latest_committed_batch": "batch",
        "source_row": "row",
        "source_row_number": "row",
        "row_number": "row",
    }
    return aliases.get(normalized, normalized)


def canonical_evidence_refs(evidence: Any) -> list[str]:
    """Build the only reference identifiers a model may cite from projected evidence."""
    references: set[str] = set()

    def add(kind: str, raw_value: Any) -> None:
        if raw_value is None or isinstance(raw_value, (bool, dict, list, tuple, set)):
            return
        value = str(raw_value).strip()
        normalized_kind = _canonical_ref_kind(kind)
        if normalized_kind and value and len(value) <= 160:
            references.add(f"{normalized_kind}:{value}")

    def visit(value: Any, *, container: str = "") -> None:
        if isinstance(value, dict):
            explicit_ref = value.get("ref")
            if isinstance(explicit_ref, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}:[^\s:][^\r\n]{0,159}", explicit_ref.strip()):
                references.add(explicit_ref.strip())
            resource_type = value.get("type")
            if isinstance(resource_type, str) and value.get("id") is not None:
                add(resource_type, value.get("id"))
            for key, item in value.items():
                key_text = str(key)
                if key_text == "id" and container:
                    add(container, item)
                elif key_text.endswith("_id"):
                    add(key_text[:-3], item)
                elif key_text.endswith("_ids"):
                    kind = key_text[:-4]
                    if isinstance(item, dict):
                        for sample in item.get("sample") or []:
                            add(kind, sample)
                    elif isinstance(item, (list, tuple, set)):
                        for sample in item:
                            add(kind, sample)
                elif key_text == "row_number":
                    add("row", item)
                visit(item, container=key_text)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                visit(item, container=container)

    visit(evidence)
    return sorted(references)


def _assert_safe_recommendations(diagnosis: ExceptionDiagnosis) -> None:
    diagnosis_text = (
        diagnosis.summary,
        diagnosis.impact,
        *diagnosis.recommended_steps,
        *diagnosis.missing_evidence,
    )
    for value in diagnosis_text:
        if any(pattern.search(value) for pattern in _DANGEROUS_RECOMMENDATION_PATTERNS):
            raise HermesResponseError("Hermes diagnosis contains a prohibited remediation recommendation")


def prepare_exception_evidence(evidence: dict[str, Any], *, domain: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a domain allowlist and deterministic payload limits before provider access."""
    allowed_keys = _DOMAIN_EVIDENCE_KEYS.get(domain, _COMMON_EVIDENCE_KEYS)
    scoped = {
        key: _project_evidence_value(value, field_name=key)
        for key, value in evidence.items()
        if key in allowed_keys
    }
    sanitized = redact_exception_evidence(scoped)
    sanitized["canonical_evidence_refs"] = canonical_evidence_refs(sanitized)
    max_bytes = max(1024, settings.exception_evidence_max_bytes)
    max_tokens = max(256, settings.exception_evidence_max_tokens)
    byte_limit = min(max_bytes, max_tokens * 4)
    truncated = len(scoped) != len(evidence)
    encoded = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    for list_limit, string_limit in ((20, 1000), (10, 500), (5, 200)):
        if len(encoded) <= byte_limit:
            break
        sanitized = _bounded_nested_value(sanitized, list_limit=list_limit, string_limit=string_limit)
        encoded = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        truncated = True
    if len(encoded) > byte_limit:
        raise HermesResponseError("Exception evidence exceeds the configured model input limit")
    return sanitized, {
        "evidence_bytes": len(encoded),
        "evidence_approx_tokens": (len(encoded) + 3) // 4,
        "evidence_truncated": truncated,
    }
