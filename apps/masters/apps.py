"""App config for the Master Data & Configuration module (RULES Phase 2)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class MastersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.masters"
    label = "masters"
    verbose_name = _("Master Data")
