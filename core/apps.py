"""Core app configuration."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Shared foundation: base models, audit, exceptions and helpers."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core"

    def ready(self) -> None:
        """Register signal handlers when the app is ready."""
        from . import signals  # noqa: F401
