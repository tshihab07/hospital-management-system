"""Generate and email due scheduled reports (RULES Phase 16).

Intended to run from cron / Celery beat, e.g. every 15 minutes::

    python manage.py send_scheduled_reports
    python manage.py send_scheduled_reports --now      # ignore next_run
    python manage.py send_scheduled_reports --id 4
    python manage.py send_scheduled_reports --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.reports import services


class Command(BaseCommand):
    help = "Render and email all report schedules that are due."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--now",
            action="store_true",
            help="Run every active schedule regardless of its next_run time.",
        )
        parser.add_argument(
            "--id",
            type=int,
            default=None,
            help="Run a single schedule by primary key.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report which schedules are due without generating them.",
        )

    def handle(self, *args, **options) -> None:
        from django.utils import timezone

        from apps.reports.models import ReportSchedule

        if options["now"]:
            schedules = ReportSchedule.objects.filter(is_active=True)
            if options["id"]:
                schedules = schedules.filter(pk=options["id"])
            stats = {"due": schedules.count(), "sent": 0, "failed": 0, "runs": []}
            if not options["dry_run"]:
                for schedule in schedules:
                    run = services.run_schedule(schedule, send_email=True)
                    stats["runs"].append(run)
                    if run.status == "success":
                        stats["sent"] += 1
                    else:
                        stats["failed"] += 1
        else:
            stats = services.send_scheduled_reports(
                now=timezone.now(),
                dry_run=options["dry_run"],
                schedule_id=options["id"],
            )

        prefix = "[dry-run] " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Scheduled reports → due: {stats['due']}, "
                f"sent: {stats['sent']}, failed: {stats['failed']}"
            )
        )
