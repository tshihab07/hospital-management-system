"""Seed a small set of operation theatres (idempotent)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.ot.models import OTRoom, OTRoomStatus, RoomType

ROOMS = [
    (
        "OT-1",
        "OT-101",
        RoomType.MAJOR,
        "Equipment: anaesthesia workstation, "
        "electrocautery, OT table, laminar flow, C-arm",
    ),
    (
        "OT-2",
        "OT-102",
        RoomType.MAJOR,
        "Equipment: anaesthesia workstation, "
        "electrocautery, OT table, laparoscopy tower",
    ),
    (
        "OT-3",
        "OT-103",
        RoomType.MINOR,
        "Equipment: OT table, electrocautery, " "basic anaesthesia set",
    ),
    (
        "Cardiac OT",
        "OT-201",
        RoomType.CARDIAC,
        "Equipment: heart-lung machine, " "cardiac monitors, IABP",
    ),
    (
        "Ortho OT",
        "OT-202",
        RoomType.ORTHO,
        "Equipment: orthopaedic table, " "image intensifier, power tools",
    ),
    (
        "Day-care OT",
        "OT-301",
        RoomType.DAYCARE,
        "Equipment: OT table, " "recovery bay, day-care trolleys",
    ),
]


class Command(BaseCommand):
    help = "Seed operating theatres (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for name, room_no, room_type, equipment in ROOMS:
            _obj, was_created = OTRoom.objects.get_or_create(
                name=name,
                defaults={
                    "room_no": room_no,
                    "room_type": room_type,
                    "equipment": equipment,
                    "status": OTRoomStatus.AVAILABLE,
                    "is_active": True,
                },
            )
            created += int(was_created)
        self.stdout.write(
            self.style.SUCCESS(f"seed_ot: {created} created, {len(ROOMS)} total.")
        )
