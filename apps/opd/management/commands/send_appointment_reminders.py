"""Send appointment reminder emails (24h and 1h before a booking)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.opd import services


class Command(BaseCommand):
    help = "Email 24-hour and 1-hour appointment reminders (via configured backend)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending emails.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        stats = services.send_reminders(dry_run=dry_run)
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Reminders → 24h: {stats['24h_sent']}, "
                f"1h: {stats['1h_sent']}, skipped: {stats['skipped']}"
            )
        )
