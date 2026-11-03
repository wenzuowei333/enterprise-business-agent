"""Showcase-only configuration; no implicit .env or parent directory loading."""
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.demo_safety import ensure_demo_database

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    environment: str = "demo"
    app_name: str = "库存异常诊断演示"
    database_url: str = "postgresql+psycopg://portfolio_demo:local-demo-only@127.0.0.1:25432/inventory_demo"
    ai_mode: str = "mock"
    exception_evidence_max_bytes: int = 32768
    exception_evidence_max_tokens: int = 8000

    @model_validator(mode="after")
    def isolated(self):
        ensure_demo_database(self.database_url, "inventory_demo", ROOT)
        if self.environment != "demo" or self.ai_mode != "mock":
            raise ValueError("This data-stage candidate only supports environment=demo, ai_mode=mock")
        return self


settings = Settings()
