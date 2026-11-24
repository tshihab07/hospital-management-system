"""Provision the default hospital chart of accounts.

Usage::

    python manage.py seed_chart_of_accounts

The command is idempotent: existing accounts (matched by code) are left
untouched, so it is safe to run on every deploy and after upgrades that add new
control accounts.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.accounting.services import seed_chart_of_accounts

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create the default IHMS chart of accounts (idempotent)."

    def handle(self, *args, **options) -> None:
        result = seed_chart_of_accounts()
        self.stdout.write(
            self.style.SUCCESS(
                "Chart of accounts seeded: "
                f"{result['created']} created, {result['existing']} already present."
            )
        )
        logger.info("seed_chart_of_accounts: %s", result)
