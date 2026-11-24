"""Read-only queries for the Operation Theatre module."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (ACTIVE_SURGERY_STATUSES, Implant, OTRoom, Surgery,
                     SurgeryConsumable, SurgeryStatus)


def surgery_list(
    *,
    q: str = "",
    status: str = "",
    room=None,
    date_from=None,
    date_to=None,
    priority: str = "",
):
    qs = Surgery.objects.select_related("patient", "surgeon", "ot_room").order_by(
        "-scheduled_date", "start_time"
    )
    if q:
        qs = qs.filter(
            Q(surgery_no__icontains=q)
            | Q(procedure_name__icontains=q)
            | Q(patient__full_name__icontains=q)
            | Q(patient__uhid__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    if room:
        qs = qs.filter(ot_room=room)
    if date_from:
        qs = qs.filter(scheduled_date__gte=date_from)
    if date_to:
        qs = qs.filter(scheduled_date__lte=date_to)
    return qs


def todays_surgeries(*, day: date | None = None):
    day = day or timezone.localdate()
    return (
        Surgery.objects.select_related("patient", "surgeon", "ot_room")
        .filter(scheduled_date=day, status__in=ACTIVE_SURGERY_STATUSES)
        .order_by("start_time")
    )


def surgeries_for_room_day(*, room: OTRoom, day: date):
    return (
        Surgery.objects.filter(
            ot_room=room, scheduled_date=day, status__in=ACTIVE_SURGERY_STATUSES
        )
        .select_related("patient", "surgeon")
        .order_by("start_time")
    )


def week_calendar(*, week_start: date | None = None):
    """Return the Mon–Sun week as calendar rows (Gantt data).

    Each row is ``{"room": OTRoom, "cells": [{"day": date, "surgeries": [...]}]}``
    so templates need no dict-key lookups.
    """
    if week_start is None:
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    rooms = list(OTRoom.objects.filter(is_active=True).order_by("name"))
    surgeries = (
        Surgery.objects.filter(
            scheduled_date__range=(week_start, week_end),
            status__in=ACTIVE_SURGERY_STATUSES,
        )
        .select_related("patient", "surgeon", "ot_room")
        .order_by("start_time")
    )
    days = [week_start + timedelta(days=i) for i in range(7)]
    buckets: dict = {(r.id, d): [] for r in rooms for d in days}
    for surgery in surgeries:
        key = (surgery.ot_room_id, surgery.scheduled_date)
        if key in buckets:
            buckets[key].append(surgery)
    rows = [
        {
            "room": room,
            "cells": [
                {"day": day, "surgeries": buckets[(room.id, day)]} for day in days
            ],
        }
        for room in rooms
    ]
    return {
        "week_start": week_start,
        "week_end": week_end,
        "days": days,
        "rooms": rooms,
        "rows": rows,
    }


def _day_bounds(day: date):
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = timezone.make_aware(datetime.combine(day, time.max))
    return start, end


def utilization_report(*, start: date, end: date):
    """OT utilisation per room over ``[start, end]`` (inclusive)."""
    days = (end - start).days + 1
    if days < 1:
        days = 1
    rooms = OTRoom.objects.filter(is_active=True).order_by("name")
    rows = []
    for room in rooms:
        surgeries = Surgery.objects.filter(
            ot_room=room,
            scheduled_date__range=(start, end),
            status__in=ACTIVE_SURGERY_STATUSES,
        )
        used_minutes = sum(s.duration_minutes for s in surgeries)
        available_minutes = days * 12 * 60  # 12-hour working day
        util = (
            (Decimal(used_minutes) / Decimal(available_minutes) * 100)
            if available_minutes
            else Decimal("0")
        )
        rows.append(
            {
                "room": room,
                "surgery_count": surgeries.count(),
                "used_minutes": used_minutes,
                "available_minutes": available_minutes,
                "utilization": round(util, 1),
            }
        )
    total_used = sum(r["used_minutes"] for r in rows)
    overall = (
        Decimal(total_used) / Decimal(days * 12 * 60 * max(len(rows), 1)) * 100
        if total_used
        else Decimal("0")
    )
    top_procedures = (
        Surgery.objects.filter(
            scheduled_date__range=(start, end), status__in=ACTIVE_SURGERY_STATUSES
        )
        .values("procedure_name")
        .annotate(c=Count("id"))
        .order_by("-c")[:10]
    )
    return {
        "rows": rows,
        "start": start,
        "end": end,
        "days": days,
        "overall_utilization": round(overall, 1),
        "total_surgeries": sum(r["surgery_count"] for r in rows),
        "top_procedures": top_procedures,
    }


def implants_for_patient(*, patient):
    return Implant.objects.filter(patient=patient).select_related("surgery")


def consumables_for_surgery(*, surgery: Surgery):
    return SurgeryConsumable.objects.filter(surgery=surgery)


def implant_cost_summary(*, start: date, end: date):
    agg = Implant.objects.filter(consumed_at__date__range=(start, end)).aggregate(
        q=Sum("quantity")
    )
    return agg


def open_surgeries_for_room(*, room: OTRoom, day: date):
    return surgeries_for_room_day(room=room, day=day).filter(
        status=SurgeryStatus.IN_PROGRESS
    )
