"""App config for the IPD — Admission & Bed Management module (RULES Phase 7)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IpdConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ipd"
    label = "ipd"
    verbose_name = _("IPD — Admission & Bed Management")
