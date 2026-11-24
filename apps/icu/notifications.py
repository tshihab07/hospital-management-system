"""Notification helpers for ICU / Emergency (email; SMS is deferred).

Phase 8 requires critical-value alerts to reach the on-call doctor within a
minute and Code Blue to broadcast to on-duty staff. The project substitutes
email for SMS (PRD/DECISIONS), reusing the same ``send_mail`` pattern as OPD.
All sends are best-effort: failures are logged and never break the caller.
"""

from __future__ import annotations

import logging

from django.core.mail import send_mail
from django.utils import timezone
from django.utils.translation import gettext as _

logger = logging.getLogger("ihms.icu")


def _send(subject: str, message: str, recipients: list[str]) -> int:
    recipients = sorted({r for r in recipients if r})
    if not recipients:
        return 0
    try:
        send_mail(
            subject,
            message,
            from_email=None,
            recipient_list=recipients,
            fail_silently=False,
        )
        return len(recipients)
    except Exception as exc:  # pragma: no cover - depends on SMTP reachability
        logger.warning("icu: email send failed: %s", exc)
        return 0


def _doctor_email(doctor) -> list[str]:
    return [doctor.email] if doctor and doctor.email else []


def on_duty_emails(*, duty_date=None) -> list[str]:
    """Email addresses of staff rostered on duty for the given date."""
    from apps.hr.models import DutyRoster

    duty_date = duty_date or timezone.localdate()
    rows = DutyRoster.objects.filter(
        duty_date=duty_date, is_published=True
    ).select_related("staff")
    emails = [row.staff.email for row in rows if row.staff.email]
    if not emails:  # fall back to any published roster regardless of date
        rows = DutyRoster.objects.filter(is_published=True).select_related("staff")
        emails = [row.staff.email for row in rows if row.staff.email]
    return emails


def critical_recipients(alert) -> list[str]:
    """Recipients for a critical value: on-call doctor plus on-duty staff."""
    return _doctor_email(alert.admission.doctor) + on_duty_emails()


def send_critical_alert(alert) -> int:
    """Notify the on-call (admitting) doctor of a critical value."""
    admission = alert.admission
    recipients = critical_recipients(alert)
    subject = _("Critical value alert — {patient}").format(patient=admission.patient)
    message = _(
        "A critical value was charted in ICU.\n\n"
        "Patient: {patient} ({uhid})\n"
        "Parameter: {parameter}\n"
        "Value: {value}\n"
        "Severity: {severity}\n"
        "Recorded: {recorded}\n\n"
        "Please review the chart immediately.\n— IHMS"
    ).format(
        patient=admission.patient.display_name,
        uhid=admission.patient.uhid,
        parameter=alert.parameter,
        value=alert.value,
        severity=alert.get_severity_display(),
        recorded=timezone.localtime(alert.created_at).strftime("%d %b %Y %H:%M"),
    )
    return _send(subject, message, recipients)


def broadcast_code_blue(alert) -> int:
    """Broadcast a Code Blue to on-duty staff and the attending doctor."""
    recipients = on_duty_emails()
    doctor = None
    if alert.admission_id:
        doctor = alert.admission.doctor
    elif alert.emergency_case_id:
        doctor = alert.emergency_case.attending_doctor
    recipients += _doctor_email(doctor)
    subject = _("CODE BLUE — {location}").format(location=alert.location)
    message = _(
        "A CODE BLUE has been activated.\n\n"
        "Location: {location}\n"
        "Called: {called}\n"
        "Please respond immediately.\n— IHMS"
    ).format(
        location=alert.location,
        called=timezone.localtime(alert.called_at).strftime("%d %b %Y %H:%M"),
    )
    return _send(subject, message, recipients)
