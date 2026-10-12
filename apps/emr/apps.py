"""App config for the EMR & CPOE (Clinical Core) module (RULES Phase 6)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class EmrConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.emr"
    label = "emr"
    verbose_name = _("EMR & CPOE")
