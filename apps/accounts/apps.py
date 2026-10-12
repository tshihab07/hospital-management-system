"""Accounts app configuration (identity, auth, RBAC)."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Identity & Access"

    def ready(self) -> None:
        from . import signals  # noqa: F401
