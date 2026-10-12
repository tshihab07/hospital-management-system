"""Appointment email helpers (Phase 4 uses email instead of SMS)."""

from __future__ import annotations

import logging

from django.core.mail import send_mail
from django.utils import timezone
from django.utils.translation import gettext as _

logger = logging.getLogger("ihms.opd")


def _appointment_email(appointment) -> tuple[str, str] | None:
    """Return ``(subject, message)`` for an appointment email."""
    patient = appointment.patient
    if not patient.email:
        return None
    doctor = appointment.doctor
    block = (
        appointment.slot.label
        if appointment.slot and appointment.slot.start_time
        else ""
    )
    message = _(
        "{patient},\n\n"
        "Your appointment at {hospital} is confirmed.\n\n"
        "Doctor: {doctor}\n"
        "Date: {date}\n"
        "Time block: {block}\n"
        "Token: #{token}\n"
        "Visit type: {visit_type}\n"
        "Consultation fee: {fee}\n\n"
        "Please arrive 15 minutes early and bring any previous reports.\n"
        "— IHMS"
    ).format(
        patient=patient.full_name_en,
        hospital="IHMS",
        doctor=doctor.display_name,
        date=appointment.appt_date.strftime("%d/%m/%Y"),
        block=block or "—",
        token=appointment.token_no,
        visit_type=appointment.get_visit_type_display(),
        fee=appointment.consultation_fee,
    )
    subject = _("Appointment confirmed – {doctor} on {date}").format(
        doctor=doctor.name_en, date=appointment.appt_date.strftime("%d/%m/%Y")
    )
    return subject, message


def send_confirmation_email(appointment) -> bool:
    """Email the patient a booking confirmation. Returns False if not sent."""
    payload = _appointment_email(appointment)
    if not payload:
        logger.info("opd: no email on patient %s – skipped", appointment.patient.uhid)
        return False
    subject, message = payload
    _try_send(subject, message, appointment.patient.email)
    logger.info("opd: confirmation email -> %s", appointment.patient.email)
    return True


def send_reminder_email(appointment, *, kind: str) -> bool:
    """Email a 24h or 1h reminder."""
    patient = appointment.patient
    if not patient.email:
        return False
    doctor = appointment.doctor
    block = (
        appointment.slot.label
        if appointment.slot and appointment.slot.start_time
        else ""
    )
    label = _("24 hour") if kind == "24h" else _("1 hour")
    subject = _("Reminder: appointment with {doctor} in {label}").format(
        doctor=doctor.name_en, label=label
    )
    message = _(
        "{patient},\n\n"
        "A friendly reminder about your appointment with {doctor} "
        "on {date} at {block} (token #{token}).\n\n"
        "— IHMS"
    ).format(
        patient=patient.full_name_en,
        doctor=doctor.display_name,
        date=appointment.appt_date.strftime("%d/%m/%Y"),
        block=block or "—",
        token=appointment.token_no,
    )
    _try_send(subject, message, patient.email)
    logger.info("opd: %s reminder email -> %s", label, patient.email)
    return True


def _try_send(subject: str, message: str, recipient: str) -> None:
    try:
        send_mail(
            subject,
            message,
            recipient_list=[recipient],
            from_email=None,
            fail_silently=False,
        )
    except Exception as exc:  # pragma: no cover - depends on SMTP reachability
        logger.warning("opd: email send failed: %s", exc)
