"""App config for the Patient Core module (RULES Phase 3)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PatientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.patients"
    label = "patients"
    verbose_name = _("Patients")
