from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    MODE: Literal["local", "hosted"] = "local"
    WORKSPACE_PATH: str = "."

    DATABASE_URL: str = ""
    SUPABASE_URL: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str = ""
    QUOTA_MAX_STORAGE_BYTES: int = 1_073_741_824
    LOGFIRE_TOKEN: str = ""
    STAGE: str = "dev"
    APP_URL: str = "http://localhost:3000"
    API_URL: str = "http://localhost:8000"
    MCP_URL: str = "http://localhost:8080/mcp"
    SENTRY_DSN: str = ""


settings = Settings()
