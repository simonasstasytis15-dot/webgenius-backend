from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional
import secrets


class Settings(BaseSettings):
    # App
    APP_NAME: str = "WebGenius"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = secrets.token_urlsafe(32)
    FRONTEND_URL: str = "http://localhost:3000"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://webgenius:webgenius@localhost:5432/webgenius"
    DATABASE_URL_SYNC: str = "postgresql://webgenius:webgenius@localhost:5432/webgenius"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET: str = secrets.token_urlsafe(32)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080  # 7 days

    # Encryption for stored API keys
    ENCRYPTION_KEY: Optional[str] = None

    # Default rate limits (per student per day)
    DEFAULT_IMAGEN_CALLS_PER_STUDENT_PER_DAY: int = 20
    DEFAULT_GEMINI_CALLS_PER_STUDENT_PER_DAY: int = 100
    DEFAULT_TTS_CALLS_PER_STUDENT_PER_DAY: int = 15
    DEFAULT_VEO_CALLS_PER_STUDENT_PER_DAY: int = 5

    @field_validator("ENCRYPTION_KEY", mode="before")
    @classmethod
    def generate_encryption_key(cls, v):
        if not v:
            from cryptography.fernet import Fernet
            return Fernet.generate_key().decode()
        return v

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
