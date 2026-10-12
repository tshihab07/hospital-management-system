"""OPD write operations (atomic + audit).

Booking serializes on the availability-slot row so capacity is never
overbooked, and on a row-locked :class:`DoctorDailyToken` counter so tokens
are unique per doctor per day.
"""

from __future__ import annotations

from datetime import date, time

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.audit import AuditAction, AuditLog, log_action, model_to_dict_safe

from . import notifications, selectors
from .models import (Appointment, AppointmentStatus, AppointmentType,
                     AvailabilitySlot, Doctor, DoctorDailyToken)


def _diff(before: dict, after: dict) -> dict:
    changed = {}
    for key, value in after.items():
        if key in {"updated_at", "created_at"}:
            continue
        if before.get(key) != value:
            changed[key] = {"from": before.get(key), "to": value}
    return changed


@transaction.atomic
def _next_token(doctor: Doctor, appt_date: date) -> int:
    counter, _ = DoctorDailyToken.objects.get_or_create(
        doctor=doctor, token_date=appt_date
    )
    counter = DoctorDailyToken.objects.select_for_update().get(pk=counter.pk)
    counter.last_token += 1
    counter.save(update_fields=["last_token"])
    return counter.last_token


def _allocate_slot(doctor: Doctor, appt_date: date, slot: AvailabilitySlot | None):
    """Serialise booking on the slot row and check remaining capacity."""
    if slot is None:
        return None
    slot = AvailabilitySlot.objects.select_for_update().get(pk=slot.pk)
    if slot.doctor_id != doctor.pk or slot.weekday != appt_date.weekday():
        raise ValueError(
            _("This time block does not belong to the selected doctor/day.")
        )
    remaining = selectors._remaining(appt_date, slot)
    if remaining <= 0:
        raise ValueError(_("This time block is already full."))
    return slot


def _fee_for(doctor: Doctor, visit_type: str) -> dict:
    if visit_type == AppointmentType.FOLLOWUP:
        return {"consultation_fee": doctor.followup_fee}
    return {"consultation_fee": doctor.consultation_fee}


def _guard_booking(
    patient, doctor: Doctor, appt_date: date, slot: AvailabilitySlot | None
) -> None:
    now = timezone.localtime()
    today = now.date()
    if appt_date < today:
        raise ValueError(_("Cannot book an appointment in the past."))
    if appt_date == today and slot and slot.end_time is not None:
        if slot.end_time <= now.time():
            raise ValueError(_("This time block has already ended for today."))
    if Appointment.objects.filter(
        patient=patient,
        doctor=doctor,
        appt_date=appt_date,
        status__in=[
            AppointmentStatus.SCHEDULED,
            AppointmentStatus.ARRIVED,
            AppointmentStatus.IN_CONSULTATION,
        ],
    ).exists():
        raise ValueError(
            _("Patient already has an active appointment with this doctor that day.")
        )


@transaction.atomic
def book_appointment(
    *,
    patient,
    doctor: Doctor,
    appt_date: date,
    slot: AvailabilitySlot | None = None,
    visit_type: str = AppointmentType.NEW,
    notes: str = "",
    actor=None,
    request=None,
) -> Appointment:
    """Book an appointment, assign a token, confirm by email, audit."""
    doctor = Doctor.objects.select_related().get(pk=doctor.pk)
    if not doctor.is_active:
        raise ValueError(_("This doctor is not active."))
    _guard_booking(patient, doctor, appt_date, slot)
    slot = _allocate_slot(doctor, appt_date, slot)

    appointment = Appointment.objects.create(
        doctor=doctor,
        patient=patient,
        slot=slot,
        appt_date=appt_date,
        slot_time=slot.start_time if slot else None,
        token_no=_next_token(doctor, appt_date),
        visit_type=visit_type,
        notes=notes,
        created_by=actor,
        **_fee_for(doctor, visit_type),
    )
    log_action(
        AuditAction.CREATE,
        instance=appointment,
        changes=model_to_dict_safe(appointment),
        user=actor,
        request=request,
    )
    notifications.send_confirmation_email(appointment)
    return appointment


@transaction.atomic
def cancel_appointment(
    *, instance: Appointment, reason: str = "", actor=None, request=None
) -> Appointment:
    """Cancel an appointment (it keeps its token, so it stays auditable)."""
    if not instance.is_active:
        raise ValueError(_("This appointment is no longer active."))
    instance.status = AppointmentStatus.CANCELLED
    instance.cancelled_at = timezone.now()
    instance.cancelled_by = actor
    instance.cancel_reason = reason
    instance.save(
        update_fields=["status", "cancelled_at", "cancelled_by", "cancel_reason"]
    )
    log_action(
        AuditAction.UPDATE,
        instance=instance,
        changes={"status": {"to": AppointmentStatus.CANCELLED}, "reason": reason},
        user=actor,
        request=request,
    )
    return instance


@transaction.atomic
def reschedule_appointment(
    *,
    instance: Appointment,
    appt_date: date,
    slot: AvailabilitySlot | None = None,
    actor=None,
    request=None,
) -> Appointment:
    """Cancel the old booking and create a new one linked via ``rescheduled_from``."""
    if not instance.is_active:
        raise ValueError(_("Cannot reschedule a non-active appointment."))
    if instance.visit_type == AppointmentType.FOLLOWUP:
        visit_type = AppointmentType.FOLLOWUP
    else:
        visit_type = AppointmentType.NEW
    created = book_appointment(
        patient=instance.patient,
        doctor=instance.doctor,
        appt_date=appt_date,
        slot=slot,
        visit_type=visit_type,
        notes=_("Rescheduled from token #%(token)s") % {"token": instance.token_no},
        actor=actor,
        request=request,
    )
    if created.pk == instance.pk:
        created.delete()
        raise ValueError(_("No changes requested."))
    created.rescheduled_from = instance
    created.save(update_fields=["rescheduled_from"])
    cancel_appointment(
        instance=instance, reason=_("Rescheduled"), actor=actor, request=request
    )
    return created


_RECORDED_AT = {
    AppointmentStatus.ARRIVED: "arrived_at",
    AppointmentStatus.IN_CONSULTATION: "started_at",
    AppointmentStatus.COMPLETED: "completed_at",
}
_ALLOWED_TRANSITIONS = {
    AppointmentStatus.SCHEDULED: {"arrived", "no_show", "cancelled"},
    AppointmentStatus.ARRIVED: {"in_consultation", "no_show", "cancelled"},
    AppointmentStatus.IN_CONSULTATION: {"completed"},
    AppointmentStatus.COMPLETED: set(),
    AppointmentStatus.CANCELLED: set(),
    AppointmentStatus.NO_SHOW: {"arrived"},
}


@transaction.atomic
def set_status(
    *, instance: Appointment, status: str, actor=None, request=None
) -> Appointment:
    """Advance an appointment through the queue lifecycle."""
    allowed = _ALLOWED_TRANSITIONS.get(instance.status, set())
    if status not in allowed:
        raise ValueError(
            _("Cannot change status from %(from)s to %(to)s.")
            % {
                "from": instance.get_status_display(),
                "to": dict(AppointmentStatus.choices)[status],
            }
        )
    if status == AppointmentStatus.CANCELLED:
        return cancel_appointment(
            instance=instance,
            reason=_("Cancelled from queue"),
            actor=actor,
            request=request,
        )
    instance.status = status
    ts_field = _RECORDED_AT.get(status)
    if ts_field:
        setattr(instance, ts_field, timezone.now())
    instance.save(update_fields=["status", ts_field] if ts_field else ["status"])
    log_action(
        AuditAction.UPDATE,
        instance=instance,
        changes={"status": {"to": status}},
        user=actor,
        request=request,
    )
    return instance


@transaction.atomic
def send_reminders(*, dry_run: bool = False) -> dict:
    """Send 24h + 1h reminders; return ``{24h_sent, 1h_sent, skipped}``."""
    today = timezone.localdate()
    tomorrow = today + timezone.timedelta(1)
    stats = {"24h_sent": 0, "1h_sent": 0, "skipped": 0}

    for appointment in (
        Appointment.objects.filter(
            appt_date=tomorrow,
            status=AppointmentStatus.SCHEDULED,
            reminder_24h_sent=False,
            patient__email__isnull=False,
        )
        .exclude(patient__email="")
        .select_related("doctor", "patient", "slot", "slot__doctor")
    ):
        if not dry_run:
            sent = notifications.send_reminder_email(appointment, kind="24h")
            if sent:
                Appointment.objects.filter(pk=appointment.pk).update(
                    reminder_24h_sent=True
                )
                stats["24h_sent"] += 1
            else:
                stats["skipped"] += 1
        else:
            stats["24h_sent"] += 1

    now = timezone.localtime()
    for appointment in (
        Appointment.objects.filter(
            appt_date=today,
            status__in=[AppointmentStatus.SCHEDULED, AppointmentStatus.ARRIVED],
            reminder_1h_sent=False,
            patient__email__isnull=False,
        )
        .exclude(patient__email="")
        .select_related("doctor", "patient", "slot", "slot__doctor")
    ):
        block_start = (
            appointment.slot.start_time if appointment.slot else appointment.slot_time
        )
        if block_start is None:
            continue
        window_start = timezone.make_aware(
            timezone.datetime.combine(today, block_start) - timezone.timedelta(hours=1),
            timezone.get_current_timezone(),
        )
        if (
            window_start
            <= now
            < timezone.make_aware(
                timezone.datetime.combine(today, block_start),
                timezone.get_current_timezone(),
            )
        ):
            if dry_run:
                stats["1h_sent"] += 1
                continue
            sent = notifications.send_reminder_email(appointment, kind="1h")
            if sent:
                Appointment.objects.filter(pk=appointment.pk).update(
                    reminder_1h_sent=True
                )
                stats["1h_sent"] += 1
            else:
                stats["skipped"] += 1
    return stats
