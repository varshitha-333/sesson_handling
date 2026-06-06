import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    TESTING: bool = False
    DATABASE_URL: str = Field("postgresql://postgres:postgres@localhost:5432/archie_db", description="PostgreSQL database connection URL")
    API_KEY: str = Field("your-secret-api-key-here", description="API Key for securing endpoints")

    # This configuration allows loading from a .env file if it exists,
    # or directly from environment variables.
    model_config = SettingsConfigDict(
        env_file=[
            os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
        ],
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
