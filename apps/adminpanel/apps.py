"""Custom IHMS admin panel (control tower)."""

from django.apps import AppConfig


class AdminPanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.adminpanel"
    label = "adminpanel"
    verbose_name = "Admin Panel"
