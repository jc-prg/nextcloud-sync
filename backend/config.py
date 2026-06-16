from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    secret_key: str = ""
    fernet_key: str = ""
    app_password_hash: str = ""
    data_dir: Path = Path("data")
    port: int = 8080
    access_token_expire_minutes: int = 60


settings = Settings()
