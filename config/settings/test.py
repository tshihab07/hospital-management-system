"""Test settings for IHMS.

Tests always run against a fast in-memory SQLite database so the remote
Supabase database is never touched and the suite stays quick.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Run Celery tasks synchronously.
CELERY_TASK_ALWAYS_EAGER = True

# Keep background noise down during tests.
LOGGING["root"]["level"] = "WARNING"  # noqa: F405

# Disable the manifest static storage in tests.
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}

INTERNAL_IPS = ["127.0.0.1"]
