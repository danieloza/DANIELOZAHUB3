import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./salonos.db")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    DEFAULT_TENANT_SLUG = os.getenv("DEFAULT_TENANT_SLUG", "danex")
    DEFAULT_TENANT_NAME = os.getenv("DEFAULT_TENANT_NAME", "Danex")


settings = Settings()
