from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    DATABASE_URL: str
    SUPABASE_URL: str = ""
    VOYAGE_API_KEY: str = ""
    TURBOPUFFER_API_KEY: str = ""
    EMBEDDING_MODEL: str = "voyage-4-lite"
    EMBEDDING_DIM: int = 512
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str = "supavault-documents"
    LOGFIRE_TOKEN: str = ""
    STAGE: str = "dev"
    APP_URL: str = "http://localhost:3000"
    API_URL: str = "http://localhost:8000"
    MCP_URL: str = "http://localhost:8080/mcp"
    SENTRY_DSN: str = ""


settings = Settings()
