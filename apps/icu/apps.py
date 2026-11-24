"""App config for the ICU / CCU & Emergency module (RULES Phase 8)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IcuConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.icu"
    label = "icu"
    verbose_name = _("ICU / CCU & Emergency")
