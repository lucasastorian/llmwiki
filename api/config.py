from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    MODE: Literal["local", "hosted"] = "local"
    WORKSPACE_PATH: str = "."

    DATABASE_URL: str = ""
    # Non-pooler URL for LISTEN/NOTIFY: Supavisor recycles pooled sessions, silently killing LISTEN.
    DIRECT_DATABASE_URL: str = ""
    SUPABASE_URL: str = ""
    LOGFIRE_TOKEN: str = ""
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str = ""
    MISTRAL_API_KEY: str = ""
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_AUTH_TOKEN: str = ""
    CLOUDFLARE_AI_GATEWAY_ID: str = ""
    QUIZ_GRADE_DAILY_LIMIT: int = Field(default=100, ge=1, le=10_000)
    # Only "mistral" is special-cased; anything else goes to the converter, which picks its own PDF_ENGINE.
    PDF_BACKEND: str = "opendataloader"
    STAGE: str = "dev"
    APP_URL: str = "http://localhost:3000"
    API_URL: str = "http://localhost:8000"
    # Comma-separated; an unpacked dev build needs its chrome://extensions ID here.
    LOCAL_EXTENSION_ORIGINS: str = (
        "chrome-extension://dibilaenlekndomfbampadehjeahemha"
    )

    QUOTA_MAX_PAGES_PER_DOC: int = 300
    QUOTA_MAX_STORAGE_BYTES: int = 1_073_741_824  # 1 GiB

    CONVERTER_URL: str = ""
    CONVERTER_SECRET: str = ""
    # Must not exceed the converter's MAX_CONCURRENT_EXTRACTIONS, or excess requests exhaust 503 retries.
    CONVERTER_MAX_CONCURRENCY: int = Field(default=2, ge=1, le=64)

    GLOBAL_OCR_ENABLED: bool = True
    GLOBAL_MAX_PAGES: int = 1_000_000
    GLOBAL_MAX_USERS: int = 10_000

    SENTRY_DSN: str = ""

    @model_validator(mode="after")
    def require_isolated_parser_for_hosted_uploads(self) -> "Settings":
        """Fail at settings load, before any network client starts, if hosted uploads would parse in-process."""
        hosted_uploads_enabled = bool(self.S3_BUCKET)
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

    @property
    def local_extension_origins(self) -> tuple[str, ...]:
        return tuple(
            origin.strip()
            for origin in self.LOCAL_EXTENSION_ORIGINS.split(",")
            if origin.strip()
        )


settings = Settings()
