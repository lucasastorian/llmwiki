from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    MODE: Literal["local", "hosted"] = "local"
    WORKSPACE_PATH: str = "."

    DATABASE_URL: str = ""
    # Direct (non-pooler) connection used only for the long-lived LISTEN/NOTIFY
    # socket. Supavisor recycles pooled sessions, which silently kills LISTEN;
    # a direct connection sidesteps that. Falls back to DATABASE_URL when unset.
    DIRECT_DATABASE_URL: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_JWT_SECRET: str = ""
    VOYAGE_API_KEY: str = ""
    TURBOPUFFER_API_KEY: str = ""
    EMBEDDING_MODEL: str = "voyage-4-lite"
    EMBEDDING_DIM: int = 512
    LOGFIRE_TOKEN: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str = "supavault-documents"
    MISTRAL_API_KEY: str = ""
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_AI_TOKEN: str = ""
    CLOUDFLARE_AI_GATEWAY_ID: str = ""
    QUIZ_GRADE_DAILY_LIMIT: int = Field(default=100, ge=1, le=10_000)
    PDF_BACKEND: str = "opendataloader"  # "opendataloader" or "mistral"
    STAGE: str = "dev"
    APP_URL: str = "http://localhost:3000"
    API_URL: str = "http://localhost:8000"

    QUOTA_MAX_PAGES_PER_DOC: int = 300  # max pages per single document
    QUOTA_MAX_STORAGE_BYTES: int = 1_073_741_824  # 1 GB per user

    CONVERTER_URL: str = ""
    CONVERTER_SECRET: str = ""

    GLOBAL_OCR_ENABLED: bool = True
    GLOBAL_MAX_PAGES: int = 1_000_000
    GLOBAL_MAX_USERS: int = 10_000

    SENTRY_DSN: str = ""

    @model_validator(mode="after")
    def require_isolated_parser_for_hosted_uploads(self) -> "Settings":
        """Never let the hosted upload service fall back to local parsing.

        ``main.lifespan`` constructs S3 and OCR services when the access key
        and bucket are configured. Validate the matching condition while
        settings are loaded, before startup can initialize JWKS, Postgres, or
        any other network client.
        """
        hosted_uploads_enabled = bool(self.AWS_ACCESS_KEY_ID and self.S3_BUCKET)
        if (
            self.MODE == "hosted"
            and hosted_uploads_enabled
            and not self.CONVERTER_URL.strip()
        ):
            raise ValueError(
                "CONVERTER_URL is required when hosted uploads are enabled; "
                "the hosted API must not parse uploaded PDF or Office files in-process"
            )
        if (
            self.MODE == "hosted"
            and hosted_uploads_enabled
            and not self.CONVERTER_SECRET.strip()
        ):
            raise ValueError(
                "CONVERTER_SECRET is required when hosted uploads are enabled"
            )
        return self

    @property
    def listen_database_url(self) -> str:
        """Connection for the LISTEN loop — direct if configured, else the pooler."""
        return self.DIRECT_DATABASE_URL or self.DATABASE_URL


settings = Settings()
