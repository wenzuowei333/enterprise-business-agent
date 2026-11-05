from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "项目底座"
    app_version: str = "1.0.0"
    environment: str = "development"
    database_url: str = Field(
        default="postgresql+psycopg://project_base:project_base@db:5432/project_base",
        alias="DATABASE_URL",
    )
    jwt_secret: str = Field(default="change-me-before-production-use-32-bytes", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=720, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    initial_admin_username: str = Field(default="admin", alias="INITIAL_ADMIN_USERNAME")
    initial_admin_password: str = Field(default="change-me-now", alias="INITIAL_ADMIN_PASSWORD")
    initial_admin_real_name: str = Field(default="系统管理员", alias="INITIAL_ADMIN_REAL_NAME")
    upload_root: str = Field(default="../runtime/uploads", alias="UPLOAD_ROOT")
    cors_origins_raw: str = Field(default="http://localhost,http://127.0.0.1", alias="CORS_ORIGINS")
    hermes_api_base_url: str | None = Field(default=None, alias="HERMES_API_BASE_URL")
    hermes_api_key: str | None = Field(default=None, alias="HERMES_API_KEY")
    hermes_model: str = Field(default="glm-5.2", alias="HERMES_MODEL")
    hermes_request_timeout_seconds: int = Field(default=120, alias="HERMES_REQUEST_TIMEOUT_SECONDS")
    exception_ai_shutdown_timeout_seconds: int = Field(
        default=150,
        ge=10,
        le=600,
        alias="EXCEPTION_AI_SHUTDOWN_TIMEOUT_SECONDS",
    )
    exception_center_enabled: bool = Field(default=False, alias="EXCEPTION_CENTER_ENABLED")
    exception_ai_enabled: bool = Field(default=False, alias="EXCEPTION_AI_ENABLED")
    exception_ai_chat_enabled: bool = Field(default=False, alias="EXCEPTION_AI_CHAT_ENABLED")
    exception_ai_case_analysis_enabled: bool = Field(
        default=False,
        alias="EXCEPTION_AI_CASE_ANALYSIS_ENABLED",
    )
    exception_ai_remediation_enabled: bool = Field(default=False, alias="EXCEPTION_AI_REMEDIATION_ENABLED")
    exception_ai_supplement_upload_enabled: bool = Field(
        default=False,
        alias="EXCEPTION_AI_SUPPLEMENT_UPLOAD_ENABLED",
    )
    exception_ai_sandbox_enabled: bool = Field(default=False, alias="EXCEPTION_AI_SANDBOX_ENABLED")
    exception_ai_remediation_execution_enabled: bool = Field(
        default=False,
        alias="EXCEPTION_AI_REMEDIATION_EXECUTION_ENABLED",
    )
    ai_remediation_private_root: str = Field(
        default="../runtime/ai-remediation",
        alias="AI_REMEDIATION_PRIVATE_ROOT",
    )
    ai_remediation_scan_required: bool = Field(default=True, alias="AI_REMEDIATION_SCAN_REQUIRED")
    ai_remediation_sandbox_image: str = Field(
        default="localhost/handmade-ai-sandbox@sha256:disabled",
        alias="AI_REMEDIATION_SANDBOX_IMAGE",
    )
    exception_schedule_enabled: bool = Field(default=False, alias="EXCEPTION_SCHEDULE_ENABLED")
    exception_actions_enabled: bool = Field(default=False, alias="EXCEPTION_ACTIONS_ENABLED")
    exception_ai_global_enabled: bool = Field(default=False, alias="EXCEPTION_AI_GLOBAL_ENABLED")
    exception_ai_crm_enabled: bool = Field(default=False, alias="EXCEPTION_AI_CRM_ENABLED")
    exception_ai_data_enabled: bool = Field(default=False, alias="EXCEPTION_AI_DATA_ENABLED")
    exception_ai_finance_enabled: bool = Field(default=False, alias="EXCEPTION_AI_FINANCE_ENABLED")
    exception_ai_global_actions_enabled: bool = Field(
        default=False,
        alias="EXCEPTION_AI_GLOBAL_ACTIONS_ENABLED",
    )
    exception_ai_high_risk_actions_enabled: bool = Field(
        default=False,
        alias="EXCEPTION_AI_HIGH_RISK_ACTIONS_ENABLED",
    )
    crm_project_approval_withdraw_enabled: bool = Field(
        default=False,
        alias="CRM_PROJECT_APPROVAL_WITHDRAW_ENABLED",
    )
    exception_ai_max_retries: int = Field(default=2, alias="EXCEPTION_AI_MAX_RETRIES")
    exception_ai_concurrency: int = Field(default=1, alias="EXCEPTION_AI_CONCURRENCY")
    exception_ai_daily_limit: int = Field(default=100, alias="EXCEPTION_AI_DAILY_LIMIT")
    exception_ai_scheduled_batch_size: int = Field(default=50, alias="EXCEPTION_AI_SCHEDULED_BATCH_SIZE")
    exception_manual_ai_daily_limit: int = Field(default=20, alias="EXCEPTION_MANUAL_AI_DAILY_LIMIT")
    exception_manual_ai_require_provider_usage: bool = Field(
        default=True,
        alias="EXCEPTION_MANUAL_AI_REQUIRE_PROVIDER_USAGE",
    )
    exception_scheduled_ai_daily_limit: int = Field(default=0, alias="EXCEPTION_SCHEDULED_AI_DAILY_LIMIT")
    exception_scheduled_ai_batch_size: int = Field(default=20, alias="EXCEPTION_SCHEDULED_AI_BATCH_SIZE")
    exception_evidence_max_bytes: int = Field(default=32768, alias="EXCEPTION_EVIDENCE_MAX_BYTES")
    exception_evidence_max_tokens: int = Field(default=8000, alias="EXCEPTION_EVIDENCE_MAX_TOKENS")
    exception_runtime_heartbeat_seconds: int = Field(default=30, alias="EXCEPTION_RUNTIME_HEARTBEAT_SECONDS")
    exception_ai_circuit_failure_threshold: int = Field(default=5, alias="EXCEPTION_AI_CIRCUIT_FAILURE_THRESHOLD")
    exception_ai_circuit_cooldown_seconds: int = Field(
        default=900, alias="EXCEPTION_AI_CIRCUIT_COOLDOWN_SECONDS"
    )
    exception_job_lease_seconds: int = Field(default=300, alias="EXCEPTION_JOB_LEASE_SECONDS")
    exception_worker_poll_seconds: int = Field(default=5, alias="EXCEPTION_WORKER_POLL_SECONDS")
    exception_worker_heartbeat_seconds: int = Field(default=30, alias="EXCEPTION_WORKER_HEARTBEAT_SECONDS")
    exception_job_max_attempts: int = Field(default=3, alias="EXCEPTION_JOB_MAX_ATTEMPTS")
    exception_schedule_timezone: str = Field(default="Asia/Hong_Kong", alias="EXCEPTION_SCHEDULE_TIMEZONE")
    mobile_latest_version: str = Field(default="1.6.0", alias="MOBILE_LATEST_VERSION")
    mobile_latest_version_code: int = Field(default=7, alias="MOBILE_LATEST_VERSION_CODE")
    mobile_minimum_supported_version: str = Field(default="1.0.0", alias="MOBILE_MINIMUM_SUPPORTED_VERSION")
    mobile_minimum_supported_version_code: int = Field(default=1, alias="MOBILE_MINIMUM_SUPPORTED_VERSION_CODE")
    mobile_download_url: str = Field(
        default="https://example.invalid/downloads/demo-management.apk",
        alias="MOBILE_DOWNLOAD_URL",
    )
    mobile_apk_sha256: str = Field(
        default="088b4d76ffc56a72ef3f6c56751b8c9c6f982448b266b5af67414c30e8028fa0",
        alias="MOBILE_APK_SHA256",
    )
    mobile_update_mode: str = Field(default="optional", alias="MOBILE_UPDATE_MODE")
    mobile_release_notes: str = Field(
        default="Android 1.6.0 生产整合版：统一 CRM、线索运营与 Liquid UI 开发线，保留安全降级能力。",
        alias="MOBILE_RELEASE_NOTES",
    )
    mobile_feature_project_application: bool = Field(default=False, alias="MOBILE_FEATURE_PROJECT_APPLICATION")
    mobile_feature_crm_customers: bool = Field(default=False, alias="MOBILE_FEATURE_CRM_CUSTOMERS")
    mobile_feature_crm_tasks: bool = Field(default=False, alias="MOBILE_FEATURE_CRM_TASKS")
    mobile_feature_crm_followups: bool = Field(default=False, alias="MOBILE_FEATURE_CRM_FOLLOWUPS")
    mobile_feature_crm_approvals: bool = Field(default=True, alias="MOBILE_FEATURE_CRM_APPROVALS")
    mobile_feature_data_query: bool = Field(default=False, alias="MOBILE_FEATURE_DATA_QUERY")
    mobile_feature_checks: bool = Field(default=False, alias="MOBILE_FEATURE_CHECKS")
    mobile_feature_notifications: bool = Field(default=False, alias="MOBILE_FEATURE_NOTIFICATIONS")
    mobile_feature_scanner: bool = Field(default=False, alias="MOBILE_FEATURE_SCANNER")
    mobile_feature_manager_dashboard: bool = Field(default=False, alias="MOBILE_FEATURE_MANAGER_DASHBOARD")
    mobile_feature_ai: bool = Field(default=False, alias="MOBILE_FEATURE_AI")
    mobile_feature_offline_read: bool = Field(default=False, alias="MOBILE_FEATURE_OFFLINE_READ")
    mobile_feature_offline_outbox: bool = Field(default=False, alias="MOBILE_FEATURE_OFFLINE_OUTBOX")
    mobile_feature_sync_conflict: bool = Field(default=False, alias="MOBILE_FEATURE_SYNC_CONFLICT")
    mobile_feature_in_app_update: bool = Field(default=False, alias="MOBILE_FEATURE_IN_APP_UPDATE")
    mobile_feature_device_management: bool = Field(default=False, alias="MOBILE_FEATURE_DEVICE_MANAGEMENT")
    mobile_feature_operations_console: bool = Field(default=False, alias="MOBILE_FEATURE_OPERATIONS_CONSOLE")
    mobile_feature_onboarding: bool = Field(default=False, alias="MOBILE_FEATURE_ONBOARDING")
    mobile_feature_in_app_feedback: bool = Field(default=False, alias="MOBILE_FEATURE_IN_APP_FEEDBACK")
    mobile_feature_voice_input: bool = Field(default=False, alias="MOBILE_FEATURE_VOICE_INPUT")
    mobile_feature_contact_ocr: bool = Field(default=False, alias="MOBILE_FEATURE_CONTACT_OCR")
    mobile_feature_ai_drafts: bool = Field(default=False, alias="MOBILE_FEATURE_AI_DRAFTS")
    mobile_feature_smart_reminders: bool = Field(default=False, alias="MOBILE_FEATURE_SMART_REMINDERS")
    mobile_feature_adoption_dashboard: bool = Field(default=False, alias="MOBILE_FEATURE_ADOPTION_DASHBOARD")
    mobile_feature_exception_center: bool = Field(default=False, alias="MOBILE_FEATURE_EXCEPTION_CENTER")
    mobile_feature_customer_tags: bool = Field(default=False, alias="MOBILE_FEATURE_CUSTOMER_TAGS")
    mobile_feature_fulfillment: bool = Field(default=False, alias="MOBILE_FEATURE_FULFILLMENT")
    mobile_feature_lead_pool: bool = Field(default=False, alias="MOBILE_FEATURE_LEAD_POOL")
    mobile_feature_lead_ocr: bool = Field(default=False, alias="MOBILE_FEATURE_LEAD_OCR")
    mobile_feature_lead_offline: bool = Field(default=False, alias="MOBILE_FEATURE_LEAD_OFFLINE")
    mobile_feature_lead_conversion: bool = Field(default=False, alias="MOBILE_FEATURE_LEAD_CONVERSION")
    mobile_feature_lead_product_intent: bool = Field(default=False, alias="MOBILE_FEATURE_LEAD_PRODUCT_INTENT")
    mobile_feature_lead_analytics: bool = Field(default=False, alias="MOBILE_FEATURE_LEAD_ANALYTICS")
    mobile_feature_liquid_ui: bool = Field(default=True, alias="MOBILE_FEATURE_LIQUID_UI")
    mobile_feature_liquid_full_effect: bool = Field(default=True, alias="MOBILE_FEATURE_LIQUID_FULL_EFFECT")
    mobile_feature_dark_theme: bool = Field(default=True, alias="MOBILE_FEATURE_DARK_THEME")
    mobile_force_reduced_glass: bool = Field(default=False, alias="MOBILE_FORCE_REDUCED_GLASS")
    mobile_ui_theme_version: str = Field(default="liquid_v1", alias="MOBILE_UI_THEME_VERSION")
    lead_sla: bool = Field(default=False, alias="LEAD_SLA")
    lead_public_pool: bool = Field(default=False, alias="LEAD_PUBLIC_POOL")
    lead_campaign: bool = Field(default=False, alias="LEAD_CAMPAIGN")
    lead_team_dashboard: bool = Field(default=False, alias="LEAD_TEAM_DASHBOARD")
    lead_bulk_assignment: bool = Field(default=False, alias="LEAD_BULK_ASSIGNMENT")
    inventory_agent_upstream_actions_enabled: bool = Field(
        default=False, alias="INVENTORY_AGENT_UPSTREAM_ACTIONS_ENABLED"
    )
    inventory_agent_validation_ttl_seconds: int = Field(
        default=300, alias="INVENTORY_AGENT_VALIDATION_TTL_SECONDS"
    )
    inventory_agent_max_adjustment_qty: float = Field(
        default=1000, alias="INVENTORY_AGENT_MAX_ADJUSTMENT_QTY"
    )
    mobile_onboarding_version: int = Field(default=1, alias="MOBILE_ONBOARDING_VERSION")
    mobile_help_enabled: bool = Field(default=True, alias="MOBILE_HELP_ENABLED")
    mobile_feedback_enabled: bool = Field(default=True, alias="MOBILE_FEEDBACK_ENABLED")
    mobile_refresh_token_expire_days: int = Field(default=30, alias="MOBILE_REFRESH_TOKEN_EXPIRE_DAYS")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
