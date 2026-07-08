import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # Core
    TESTING: bool = False
    ENVIRONMENT: str = Field("development", description="development | production")
    DATABASE_URL: str = Field(
        "postgresql://postgres:postgres@localhost:5432/archie_db",
        description="PostgreSQL connection URL (Railway injects this when a PG plugin is attached)",
    )

    # Auth
    API_KEY: str = Field("your-secret-api-key-here", description="API Key for securing endpoints")
    ADMIN_API_KEY: str = Field("your-secret-admin-key-here", description="API Key for administrative routes")
    ADMIN_USERNAME: str = Field("admin", description="Default author name for admin changes")

    # Authentication (Google OAuth2 + JWT)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    JWT_SECRET_KEY: str = "change-me-to-a-random-secret-key"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS: comma-separated exact origins; "*" (default) keeps the permissive dev behavior
    CORS_ORIGINS: str = Field("*", description='Comma-separated allowed origins, e.g. "https://archie.app,https://staging.archie.app"')

    # AI engine proxy target for POST /chat
    AI_ENGINE_URL: str = Field("http://127.0.0.1:8001/chat", description="Upstream AI interviewer engine")

    # Session engine tuning
    SESSION_HEARTBEAT_TIMEOUT_SECONDS: int = Field(180, description="Heartbeat gap after which a client is considered stale/crashed")
    SESSION_IDLE_TIMEOUT_SECONDS: int = Field(900, description="No-activity window before the frontend should warn/auto-pause")
    SESSION_RECOVERY_WINDOW_SECONDS: int = Field(86400, description="How long a crashed/stale live session stays recoverable before being abandoned")

    # Rate limiting (in-memory sliding window, per API key or client IP)
    RATE_LIMIT_PER_MINUTE: int = Field(120, description="Max requests per minute per caller; 0 disables")

    # Connection pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    model_config = SettingsConfigDict(
        env_file=[
            os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        ],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self):
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
