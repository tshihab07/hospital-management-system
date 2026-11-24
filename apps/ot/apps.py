"""App config for the Operation Theatre (OT) module (RULES Phase 9)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class OtConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ot"
    label = "ot"
    verbose_name = _("Operation Theatre")
