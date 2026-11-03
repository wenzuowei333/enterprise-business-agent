"""Showcase-only configuration; no implicit .env or parent directory loading."""
from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.demo_safety import ensure_demo_database

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    environment: str = "demo"
    app_name: str = "库存异常诊断演示"
    database_url: str = "postgresql+psycopg://portfolio_demo:local-demo-only@127.0.0.1:25434/inventory_demo"
    ai_mode: str = "mock"
    exception_evidence_max_bytes: int = 32768
    exception_evidence_max_tokens: int = 8000
    exception_center_enabled: bool = True
    exception_ai_enabled: bool = True
    exception_manual_ai_daily_limit: int = 20
    exception_scheduled_ai_daily_limit: int = 0
    exception_scheduled_ai_batch_size: int = 1
    exception_job_lease_seconds: float = Field(default=6, ge=0.5, le=300)
    exception_worker_heartbeat_seconds: float = Field(default=1, ge=0.05)
    exception_job_max_attempts: int = Field(default=2, ge=1, le=5)
    exception_retry_seconds: float = Field(default=1, ge=0, le=60)
    provider_timeout_seconds: float = Field(default=3, ge=0.1, le=30)
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)

    @model_validator(mode="after")
    def isolated(self):
        ensure_demo_database(self.database_url, "inventory_demo", ROOT)
        if self.environment != "demo" or self.ai_mode != "mock":
            raise ValueError("This showcase only supports environment=demo, ai_mode=mock")
        if self.exception_worker_heartbeat_seconds >= self.exception_job_lease_seconds / 3:
            raise ValueError("Heartbeat interval must be less than one third of the lease")
        return self


settings = Settings()
