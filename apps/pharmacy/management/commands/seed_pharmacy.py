"""Seed default pharmacy stores (idempotent)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.pharmacy.models import PharmacyStore, StoreType

DEFAULT_STORES = [
    ("Central Store", "CS", StoreType.CENTRAL, "Pharmacy department"),
    ("OPD Pharmacy", "OPD-P", StoreType.SUB_STORE, "OPD dispensing counter"),
    ("Ward Pharmacy", "WARD-P", StoreType.SUB_STORE, "Inpatient ward store"),
]


class Command(BaseCommand):
    help = "Create the default central and sub-store pharmacy locations."

    def handle(self, *args, **options) -> None:
        created = 0
        for name, code, store_type, location in DEFAULT_STORES:
            _, was_created = PharmacyStore.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "store_type": store_type,
                    "location": location,
                },
            )
            created += int(was_created)
        self.stdout.write(
            self.style.SUCCESS(
                f"Pharmacy stores seeded: {created} created, "
                f"{len(DEFAULT_STORES) - created} already present."
            )
        )
