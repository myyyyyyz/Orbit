from pydantic_settings import BaseSettings
import os


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./lovediary.db"
    UPLOAD_DIR: str = "uploads"
    SECRET_KEY: str = "lovediary-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    class Config:
        env_file = ".env"


settings = Settings()

# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
