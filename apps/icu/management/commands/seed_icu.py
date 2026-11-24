"""Ensure the ICU/CCU/HDU wards and beds exist (idempotent).

Critical-care charting is linked to an IPD admission; this command guarantees
the critical-care wards and beds from the IPD seed are present without touching
the general/cabin wards.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from apps.ipd.management.commands.seed_ipd import WARDS
from apps.ipd.models import Bed, Ward, WardType

CRITICAL_WARD_TYPES = {WardType.ICU, WardType.CCU, WardType.HDU}


class Command(BaseCommand):
    help = _("Create the ICU / CCU / HDU wards and beds used by critical care.")

    def handle(self, *args, **options):
        wards = beds = 0
        for name, ward_type, floor, bed_count, daily_rate in WARDS:
            if ward_type not in CRITICAL_WARD_TYPES:
                continue
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
                f"ICU seed complete: {wards} ward(s) created, {beds} bed(s) created."
            )
        )
