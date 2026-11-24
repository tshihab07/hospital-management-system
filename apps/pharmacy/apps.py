"""App config for the Pharmacy & Inventory module (RULES Phase 11)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PharmacyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pharmacy"
    label = "pharmacy"
    verbose_name = _("Pharmacy & Inventory")
