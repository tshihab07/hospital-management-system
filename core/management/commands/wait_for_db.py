"""Wait until the configured database is reachable.

Useful for container start-up ordering::

    python manage.py wait_for_db --timeout 60
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    """Poll the default database connection until it responds."""

    help = "Block until the default database accepts connections."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--timeout", type=int, default=30, help="Seconds to wait.")
        parser.add_argument(
            "--interval", type=float, default=1.0, help="Poll interval."
        )

    def handle(self, *args, **options) -> None:
        timeout = options["timeout"]
        interval = options["interval"]
        deadline = time.monotonic() + timeout

        self.stdout.write("Waiting for database...")
        while True:
            try:
                connections["default"].ensure_connection()
                self.stdout.write(self.style.SUCCESS("Database available."))
                return
            except OperationalError as exc:
                if time.monotonic() >= deadline:
                    self.stderr.write(self.style.ERROR(f"Database unavailable: {exc}"))
                    return
                time.sleep(interval)
