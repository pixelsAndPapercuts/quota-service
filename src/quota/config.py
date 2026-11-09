from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_path: str = "/app/data/quota.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_timeout_ms: int = 50
    redis_connect_timeout_ms: int = 2000
    redis_max_connections: int = 2000

    monthly_window_seconds: int = 30 * 24 * 60 * 60
    idem_ttl_seconds: int = 24 * 60 * 60

    config_cache_max_entries: int = 10_000
    config_cache_ttl_seconds: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
