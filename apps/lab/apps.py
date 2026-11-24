"""App config for the Laboratory & Radiology (LIS/RIS) module (RULES Phase 10)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class LabConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.lab"
    label = "lab"
    verbose_name = _("Laboratory & Radiology")
