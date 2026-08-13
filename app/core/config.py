from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://setuhaul:setuhaul@localhost:5432/setuhaul"
    app_env: str = "development"


settings = Settings()
