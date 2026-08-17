from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://setuhaul:setuhaul@localhost:5433/setuhaul"
    test_database_url: str = "postgresql+psycopg://setuhaul:setuhaul@localhost:5433/setuhaul_test"
    app_env: str = "development"
    run_migrations_on_startup: bool = False

    llm_provider: str = "fake"
    llm_api_key: str | None = None
    llm_model: str = "openai/gpt-4o-mini"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5175,http://127.0.0.1:5175,http://localhost:5177,http://127.0.0.1:5177"


settings = Settings()
