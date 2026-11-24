"""Provision payroll settings and the current Bangladesh income-tax grid.

Usage::

    python manage.py seed_payroll

Idempotent: existing settings and slabs are left untouched, missing bracket
grids are filled in. Safe to run on every deploy.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.payroll.seed import seed_payroll_defaults

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create default payroll settings and income-tax slabs (idempotent)."

    def handle(self, *args, **options) -> None:
        result = seed_payroll_defaults()
        self.stdout.write(
            self.style.SUCCESS(
                "Payroll seeded: "
                f"{result['created']} tax slabs created, "
                f"{result['existing']} already present "
                f"(settings #{result['setting_id']})."
            )
        )
        logger.info("seed_payroll: %s", result)
