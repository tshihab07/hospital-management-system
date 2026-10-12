"""Staging settings for IHMS — production-like with debug off."""

from .prod import *  # noqa: F401,F403

DEBUG = False

# Relax HTTPS-only redirects for a staging box without TLS termination.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
