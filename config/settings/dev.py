"""Development settings for IHMS."""

from .base import *  # noqa: F401,F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

# django-debug-toolbar (development only)
INSTALLED_APPS += ["debug_toolbar", "nplusone.ext.django"]  # noqa: F405
MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
MIDDLEWARE.insert(1, "nplusone.ext.django.NPlusOneMiddleware")  # noqa: F405

INTERNAL_IPS = ["127.0.0.1", "localhost"]

NPLUSONE_RAISE = False

# Email is printed to the console in development.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Faster, friendlier password hashing in development.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
