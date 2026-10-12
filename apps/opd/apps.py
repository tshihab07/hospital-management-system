"""App config for the OPD & Appointments module (RULES Phase 4)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class OpdConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.opd"
    label = "opd"
    verbose_name = _("OPD & Appointments")
