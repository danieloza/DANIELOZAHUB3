import os

from dotenv import load_dotenv

load_dotenv()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except Exception:
        return int(default)


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./salonos.db")
    DATABASE_READ_REPLICA_URL = os.getenv("DATABASE_READ_REPLICA_URL", "").strip()
    DB_AUTO_CREATE_ALL = _get_bool("DB_AUTO_CREATE_ALL", False)
    DB_SCHEMA_CHECK_ON_STARTUP = _get_bool("DB_SCHEMA_CHECK_ON_STARTUP", True)
    REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0").strip()
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
    DEFAULT_TENANT_SLUG = os.getenv("DEFAULT_TENANT_SLUG", "danex")
    DEFAULT_TENANT_NAME = os.getenv("DEFAULT_TENANT_NAME", "Danex")
    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()

    PUBLIC_RL_IP_PER_MIN = _get_int("PUBLIC_RL_IP_PER_MIN", 20)
    PUBLIC_RL_IP_PER_HOUR = _get_int("PUBLIC_RL_IP_PER_HOUR", 200)
    PUBLIC_RL_PHONE_PER_MIN = _get_int("PUBLIC_RL_PHONE_PER_MIN", 5)
    PUBLIC_RL_PHONE_PER_HOUR = _get_int("PUBLIC_RL_PHONE_PER_HOUR", 40)
    PUBLIC_RL_EVENT_RETENTION_HOURS = _get_int("PUBLIC_RL_EVENT_RETENTION_HOURS", 4)

    OPS_TIMEOUT_LIKE_MS = _get_int("OPS_TIMEOUT_LIKE_MS", 1500)
    OPS_ALERTS_WINDOW_MINUTES = _get_int("OPS_ALERTS_WINDOW_MINUTES", 15)
    OPS_EVENTS_PERSIST_ENABLED = _get_bool("OPS_EVENTS_PERSIST_ENABLED", True)
    OPS_EVENTS_STREAM = os.getenv("OPS_EVENTS_STREAM", "salonos.http_events").strip()
    DEFAULT_ACTOR_ROLE = os.getenv("DEFAULT_ACTOR_ROLE", "reception").strip().lower()
    CALENDAR_SYNC_DEFAULT_PROVIDER = os.getenv("CALENDAR_SYNC_DEFAULT_PROVIDER", "google").strip().lower()

    AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change-this-in-prod").strip()
    AUTH_JWT_KEYS = os.getenv("AUTH_JWT_KEYS", "").strip()
    AUTH_JWT_ACTIVE_KID = os.getenv("AUTH_JWT_ACTIVE_KID", "").strip()
    AUTH_ALGORITHM = os.getenv("AUTH_ALGORITHM", "HS256").strip()
    AUTH_ACCESS_TOKEN_MINUTES = _get_int("AUTH_ACCESS_TOKEN_MINUTES", 60)
    AUTH_REFRESH_TOKEN_DAYS = _get_int("AUTH_REFRESH_TOKEN_DAYS", 14)
    AUTH_REQUIRED = _get_bool("AUTH_REQUIRED", False)
    AUTH_ISSUER = os.getenv("AUTH_ISSUER", "salonos").strip()
    AUTH_AUDIENCE = os.getenv("AUTH_AUDIENCE", "salonos-api").strip()
    AUTH_PASSWORD_MIN_LENGTH = _get_int("AUTH_PASSWORD_MIN_LENGTH", 10)
    AUTH_PASSWORD_REQUIRE_UPPER = _get_bool("AUTH_PASSWORD_REQUIRE_UPPER", True)
    AUTH_PASSWORD_REQUIRE_LOWER = _get_bool("AUTH_PASSWORD_REQUIRE_LOWER", True)
    AUTH_PASSWORD_REQUIRE_DIGIT = _get_bool("AUTH_PASSWORD_REQUIRE_DIGIT", True)
    AUTH_PASSWORD_REQUIRE_SPECIAL = _get_bool("AUTH_PASSWORD_REQUIRE_SPECIAL", True)
    AUTH_MAX_ACTIVE_SESSIONS_PER_USER = _get_int("AUTH_MAX_ACTIVE_SESSIONS_PER_USER", 8)
    AUTH_REQUIRE_MFA = _get_bool("AUTH_REQUIRE_MFA", False)

    FEATURE_FLAGS_SALT = os.getenv("FEATURE_FLAGS_SALT", "salonos-flags").strip()
    EVENT_BUS_ENABLED = _get_bool("EVENT_BUS_ENABLED", True)
    EVENT_BUS_STREAM = os.getenv("EVENT_BUS_STREAM", "salonos.events").strip()

    PAYMENT_PROVIDER_MODE = os.getenv("PAYMENT_PROVIDER_MODE", "mock").strip().lower()
    PAYMENT_DEFAULT_CURRENCY = os.getenv("PAYMENT_DEFAULT_CURRENCY", "PLN").strip().upper()

    BACKUP_ENCRYPTION_KEY = os.getenv("BACKUP_ENCRYPTION_KEY", "").strip()
    OFFSITE_S3_BUCKET = os.getenv("OFFSITE_S3_BUCKET", "").strip()
    OFFSITE_S3_REGION = os.getenv("OFFSITE_S3_REGION", "").strip()
    OFFSITE_S3_ENDPOINT_URL = os.getenv("OFFSITE_S3_ENDPOINT_URL", "").strip()

    MAINTENANCE_MODE = _get_bool("MAINTENANCE_MODE", False)
    MAINTENANCE_READ_ONLY = _get_bool("MAINTENANCE_READ_ONLY", False)
    MAINTENANCE_RETRY_AFTER_SECONDS = _get_int("MAINTENANCE_RETRY_AFTER_SECONDS", 120)

    SECURITY_HEADERS_ENABLED = _get_bool("SECURITY_HEADERS_ENABLED", True)

    AUTH_LOGIN_RL_PER_MIN = _get_int("AUTH_LOGIN_RL_PER_MIN", 8)
    AUTH_LOGIN_RL_PER_HOUR = _get_int("AUTH_LOGIN_RL_PER_HOUR", 40)
    AUTH_LOGIN_RL_EVENT_RETENTION_HOURS = _get_int("AUTH_LOGIN_RL_EVENT_RETENTION_HOURS", 4)

    CALENDAR_WEBHOOK_SIGNATURE_REQUIRED = _get_bool("CALENDAR_WEBHOOK_SIGNATURE_REQUIRED", False)
    CALENDAR_WEBHOOK_SIGNATURE_TTL_SECONDS = _get_int("CALENDAR_WEBHOOK_SIGNATURE_TTL_SECONDS", 300)
    OUTBOX_MAX_RETRIES = _get_int("OUTBOX_MAX_RETRIES", 8)


settings = Settings()
