from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://setuhaul:setuhaul@localhost:5432/setuhaul"
    app_env: str = "development"

    llm_provider: str = "fake"
    llm_api_key: str | None = None
    llm_model: str = "openai/gpt-4o-mini"
    llm_base_url: str = "https://openrouter.ai/api/v1"


settings = Settings()
