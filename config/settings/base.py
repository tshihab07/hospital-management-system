"""
IHMS base settings.

Shared configuration for every environment. Environment specific overrides
live in ``dev.py``, ``staging.py``, ``prod.py`` and ``test.py``.

All secrets and environment specific values are read from the ``.env`` file
(or the real process environment). See ``.env.example`` for the full key list.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote_plus, urlparse

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------
def env(key: str, default: str | None = None) -> str | None:
    """Return an environment variable or ``default`` when unset/blank."""
    value = os.getenv(key, default)
    if isinstance(value, str):
        value = value.strip()
    return value or default


def env_bool(key: str, default: bool = False) -> bool:
    """Return an environment variable coerced to a boolean."""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int = 0) -> int:
    """Return an environment variable coerced to an int."""
    try:
        return int(str(os.getenv(key, default)).strip())
    except (TypeError, ValueError):
        return default


def env_list(key: str, default: str = "") -> list[str]:
    """Return a comma separated environment variable as a list."""
    raw = os.getenv(key, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core security
# ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY", "django-insecure-ihms-development-only-key")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "axes",
    "widget_tweaks",
]

LOCAL_APPS = [
    "core",
    "apps.accounts",
    "apps.adminpanel",
    "apps.masters",
    "apps.patients",
    "apps.opd",
    "apps.hr",
    "apps.emr",
    "apps.ipd",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
    "core.middleware.AuditRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "core.context_processors.ihms_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def _build_database() -> dict:
    """Build the ``DATABASES`` mapping from environment variables.

    Preference order:
      1. Remote PostgreSQL (Supabase) when ``USE_REMOTE_DB`` is true,
         using the pooler URL when ``USE_POOLER`` is true.
      2. A dedicated local PostgreSQL URL (``DATABASE_URL_LOCAL``).
      3. SQLite fallback so the project always boots.
    """
    use_remote = env_bool("USE_REMOTE_DB", False)
    use_pooler = env_bool("USE_POOLER", True)

    url = None
    if use_remote:
        url = env("DATABASE_POOLER_URL") if use_pooler else env("DATABASE_URL")
    if not url:
        url = env("DATABASE_URL_LOCAL")

    if not url:
        return {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }

    parsed = urlparse(url)
    is_pooler = "pooler.supabase.com" in (parsed.hostname or "")

    options: dict = {"sslmode": env("DB_SSLMODE", "require")}
    if is_pooler:
        # pgbouncer (transaction mode) does not support prepared statements.
        options["prepare_threshold"] = None

    return {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote_plus(parsed.path.lstrip("/")) or "postgres",
            "USER": unquote_plus(parsed.username or ""),
            "PASSWORD": unquote_plus(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 0),
            "DISABLE_SERVER_SIDE_CURSORS": True,
            "OPTIONS": options,
        }
    }


DATABASES = _build_database()

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
    "apps.accounts.backends.RolePermissionBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "panel:home"
LOGOUT_REDIRECT_URL = "accounts:login"

SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 60 * 60)  # 1 hour
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True

# django-axes (brute force lockout)
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
AXES_ENABLE_ACCESS_FAILURE_LOG = True
AXES_RESET_ON_SUCCESS = True

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LANGUAGES = [
    ("en", "English"),
    ("bn", "বাংলা"),
]

LOCALE_PATHS = [BASE_DIR / "locale"]

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "IHMS <no-reply@ihms.local>")

# ---------------------------------------------------------------------------
# Cache / Redis
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": 3600,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ihms-local",
        }
    }

# ---------------------------------------------------------------------------
# Celery (optional)
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL or "")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL or "")
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)
CELERY_TIMEZONE = TIME_ZONE

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
        "simple": {"format": "{levelname} {message}", "style": "{"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "ihms.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
    "loggers": {
        "django.security": {
            "level": "WARNING",
            "handlers": ["console", "file"],
            "propagate": False,
        },
        "axes": {"level": "INFO", "handlers": ["console", "file"], "propagate": False},
    },
}

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# IHMS domain configuration
IHMS = {
    "COUNTRY": "Bangladesh",
    "CURRENCY": "BDT",
    "CURRENCY_SYMBOL": "৳",
    "UHID_PREFIX": env("UHID_PREFIX", "DHK"),
    "IP_PREFIX": env("IP_PREFIX", "IP"),
    "IP_NUMBER_WIDTH": 5,
    "IP_DAILY_NURSING_RATE": "300",
    "IP_DAILY_DOCTOR_VISIT_RATE": "500",
    "DATE_FORMAT": "d/m/Y",
    "DATETIME_FORMAT": "d/m/Y H:i",
}

# Super admin seed values (consumed by the seed_superadmin command)
SUPER_ADMIN_USERNAME = env("ADMIN_USERNAME", "admin")
SUPER_ADMIN_PASSWORD = env("ADMIN_PASSWORD", "admin")
SUPER_ADMIN_EMAIL = env("ADMIN_EMAIL", "")
