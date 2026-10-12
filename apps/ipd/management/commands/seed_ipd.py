"""Seed wards and beds for the IPD module (idempotent)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from apps.ipd.models import Bed, Ward, WardType

WARDS = [
    # name, type, floor, bed_count, daily_rate
    ("General Ward", WardType.GENERAL, "2", 10, "500"),
    ("Cabin Wing", WardType.CABIN, "3", 6, "1500"),
    ("ICU", WardType.ICU, "4", 4, "8000"),
    ("CCU", WardType.CCU, "4", 3, "6000"),
    ("HDU", WardType.HDU, "4", 3, "4000"),
]


class Command(BaseCommand):
    help = _("Create the default wards and beds used by IPD.")

    def handle(self, *args, **options):
        wards = beds = 0
        for name, ward_type, floor, bed_count, daily_rate in WARDS:
            ward, created = Ward.objects.get_or_create(
                name=name, defaults={"ward_type": ward_type, "floor": floor}
            )
            wards += int(created)
            for idx in range(1, bed_count + 1):
                _, bed_created = Bed.objects.update_or_create(
                    ward=ward,
                    bed_no=f"{idx:02d}",
                    defaults={"bed_type": ward_type, "daily_rate": daily_rate},
                )
                beds += int(bed_created)
        self.stdout.write(
            self.style.SUCCESS(
                f"IPD seed complete: {wards} ward(s) created, {beds} bed(s) created."
            )
        )
