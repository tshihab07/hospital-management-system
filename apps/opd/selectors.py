"""Read-side helpers for OPD doctors and appointments."""

from __future__ import annotations

from datetime import date, time

from django.db.models import Count, Q
from django.utils import timezone

from .models import Appointment, AppointmentStatus, AvailabilitySlot, Doctor


def doctor_list(*, search: str = "", active_only: bool = True):
    qs = Doctor.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    if search:
        qs = qs.filter(
            Q(name_en__icontains=search)
            | Q(name_bn__icontains=search)
            | Q(bmdc_no__icontains=search)
            | Q(specialization__icontains=search)
        )
    return qs


def doctor_slots(doctor: Doctor, *, weekday: str = ""):
    qs = AvailabilitySlot.objects.filter(doctor=doctor)
    if weekday not in (None, ""):
        qs = qs.filter(weekday=int(weekday))
    return qs.order_by("weekday", "start_time")


def appointment_list(
    *,
    appt_date: date | None = None,
    doctor: Doctor | None = None,
    status: str = "",
    search: str = "",
):
    qs = Appointment.objects.select_related("doctor", "patient")
    if appt_date:
        qs = qs.filter(appt_date=appt_date)
    if doctor:
        qs = qs.filter(doctor=doctor)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(patient__full_name_en__icontains=search)
            | Q(patient__uhid__icontains=search)
            | Q(patient__phone__icontains=search)
            | Q(doctor__name_en__icontains=search)
        )
    return qs


def _remaining(appt_date: date, slot: AvailabilitySlot) -> int:
    used = Appointment.objects.filter(
        doctor=slot.doctor,
        appt_date=appt_date,
        slot=slot,
        status__in=[
            AppointmentStatus.SCHEDULED,
            AppointmentStatus.ARRIVED,
            AppointmentStatus.IN_CONSULTATION,
        ],
    ).count()
    return max(0, slot.max_patients - used)


def available_blocks(doctor: Doctor, appt_date: date):
    """Return active blocks for ``appt_date`` as ``(slot, remaining)``."""
    slots = AvailabilitySlot.objects.filter(
        doctor=doctor, weekday=appt_date.weekday(), is_active=True
    ).order_by("start_time")
    blocks = []
    for slot in slots:
        if (
            appt_date == timezone.localdate()
            and slot.end_time <= timezone.localtime().time()
        ):
            continue
        blocks.append((slot, _remaining(appt_date, slot)))
    return blocks


def queue_for(doctor: Doctor | None, *, appt_date: date | None = None):
    day = appt_date or timezone.localdate()
    qs = (
        Appointment.objects.select_related("doctor", "patient", "slot")
        .filter(
            appt_date=day,
            status__in=[
                AppointmentStatus.SCHEDULED,
                AppointmentStatus.ARRIVED,
                AppointmentStatus.IN_CONSULTATION,
                AppointmentStatus.COMPLETED,
                AppointmentStatus.NO_SHOW,
            ],
        )
        .order_by("doctor_id", "token_no")
    )
    if doctor:
        qs = qs.filter(doctor=doctor)
    return qs


def today_summary(*, appt_date: date | None = None):
    """Per-doctor counts for the queue board header."""
    day = appt_date or timezone.localdate()
    return list(
        Appointment.objects.filter(appt_date=day)
        .values("doctor__id", "doctor__name_en")
        .annotate(
            total=Count("id"),
            waiting=Count(
                "id",
                filter=Q(status=AppointmentStatus.SCHEDULED)
                | Q(status=AppointmentStatus.ARRIVED),
            ),
            completed=Count("id", filter=Q(status=AppointmentStatus.COMPLETED)),
        )
        .order_by("doctor__name_en")
    )
