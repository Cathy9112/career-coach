"""Environment-driven production configuration."""
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


def read_secret(name: str) -> str | None:
    secret_file = os.getenv(f"{name}_FILE")
    if secret_file:
        try:
            value = Path(secret_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"Unable to read secret file for {name}") from exc
        if not value:
            raise RuntimeError(f"Secret file for {name} is empty")
        return value
    return os.getenv(name)


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("APP_ENV", "development")
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "86400"))
    session_lock_timeout_seconds: int = int(os.getenv("SESSION_LOCK_TIMEOUT_SECONDS", "300"))
    auth_rate_limit: int = int(os.getenv("AUTH_RATE_LIMIT", "10"))
    auth_rate_window_seconds: int = int(os.getenv("AUTH_RATE_WINDOW_SECONDS", "60"))
    llm_rate_limit: int = int(os.getenv("LLM_RATE_LIMIT", "10"))
    llm_rate_window_seconds: int = int(os.getenv("LLM_RATE_WINDOW_SECONDS", "60"))
    daily_llm_request_quota: int = int(os.getenv("DAILY_LLM_REQUEST_QUOTA", "100"))
    knowledge_retention_days: int = int(os.getenv("KNOWLEDGE_RETENTION_DAYS", "90"))
    usage_retention_days: int = int(os.getenv("USAGE_RETENTION_DAYS", "180"))
    retention_cleanup_interval_seconds: int = int(os.getenv("RETENTION_CLEANUP_INTERVAL_SECONDS", "86400"))
    jwt_algorithm: str = "HS256"

    @property
    def redis_url(self) -> str:
        redis_url = read_secret("REDIS_URL")
        if redis_url:
            return redis_url
        password = read_secret("REDIS_PASSWORD")
        if password:
            return f"redis://:{quote(password, safe='')}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        if self.environment == "production":
            raise RuntimeError("REDIS_PASSWORD is required in production")
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def database_url(self) -> str:
        database_url = read_secret("DATABASE_URL")
        if database_url:
            return database_url
        if self.environment == "production":
            raise RuntimeError("DATABASE_URL is required in production")
        return "sqlite:///./career_coach.db"

    @property
    def jwt_secret(self) -> str:
        secret = read_secret("JWT_SECRET_KEY")
        if secret:
            return secret
        if self.environment == "production":
            raise RuntimeError("JWT_SECRET_KEY is required in production")
        return "development-only-change-me"


settings = Settings()
