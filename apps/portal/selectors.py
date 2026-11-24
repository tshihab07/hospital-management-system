"""Read-side helpers for the Patient Portal (RULES Phase 15).

Every helper here is **scoped to a single patient** so a portal user can never
read another patient's records. Views must always call these with the patient
resolved from ``request.user`` (never from a URL parameter).
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.billing.models import Bill, BillStatus
from apps.ipd.models import DischargeSummary
from apps.lab.models import LabReport, RadiologyRecord
from apps.opd.models import Appointment, AppointmentStatus, Doctor

from .models import MedicalRecordRequest, NotificationPreference

_ACTIVE_APPOINTMENT_STATUSES = [
    AppointmentStatus.SCHEDULED,
    AppointmentStatus.ARRIVED,
    AppointmentStatus.IN_CONSULTATION,
]


def patient_for(user):
    """Return the :class:`Patient` linked to ``user`` (or ``None``)."""
    if not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "patient_profile", None)


def upcoming_appointments(patient):
    """Active appointments from today onward (soonest first)."""
    return (
        Appointment.objects.select_related("doctor", "slot", "patient")
        .filter(
            patient=patient,
            appt_date__gte=timezone.localdate(),
            status__in=_ACTIVE_APPOINTMENT_STATUSES,
        )
        .order_by("appt_date", "slot_time", "token_no")
    )


def past_appointments(patient, *, limit: int = 20):
    """Recent appointments for history (newest first)."""
    return (
        Appointment.objects.select_related("doctor")
        .filter(patient=patient)
        .exclude(status__in=_ACTIVE_APPOINTMENT_STATUSES)
        .order_by("-appt_date", "-token_no")[:limit]
    )


def available_doctors():
    return Doctor.objects.filter(is_active=True).order_by("name_en")


def released_lab_reports(patient):
    """Only reports the lab has explicitly released to the patient."""
    return (
        LabReport.objects.select_related("order")
        .filter(order__patient=patient, is_released=True)
        .order_by("-created_at")
    )


def released_radiology(patient):
    return (
        RadiologyRecord.objects.select_related("order")
        .filter(order__patient=patient, is_released=True)
        .order_by("-created_at")
    )


def discharge_summaries(patient):
    return (
        DischargeSummary.objects.select_related("admission")
        .filter(admission__patient=patient)
        .order_by("-discharged_at")
    )


def patient_bills(patient):
    """Bills a patient is allowed to see (cancelled drafts are hidden)."""
    return (
        Bill.objects.filter(patient=patient)
        .exclude(status=BillStatus.CANCELLED)
        .order_by("-created_at")
    )


def outstanding_bills(patient):
    qs = patient_bills(patient).filter(
        status__in=[BillStatus.ISSUED, BillStatus.PARTIALLY_PAID]
    )
    return [bill for bill in qs if bill.due_amount > 0]


def outstanding_total(patient) -> Decimal:
    return sum(
        (bill.due_amount for bill in outstanding_bills(patient)), Decimal("0.00")
    )


def record_requests(patient):
    return MedicalRecordRequest.objects.filter(patient=patient).order_by("-created_at")


def notification_preference(patient) -> NotificationPreference:
    """Return the patient's preference row, creating a sensible default."""
    preference, _ = NotificationPreference.objects.get_or_create(patient=patient)
    return preference


def dashboard_summary(patient) -> dict:
    """Compact metrics for the portal landing page."""
    next_appt = upcoming_appointments(patient).first()
    return {
        "next_appointment": next_appt,
        "upcoming_count": upcoming_appointments(patient).count(),
        "outstanding_total": outstanding_total(patient),
        "outstanding_count": len(outstanding_bills(patient)),
        "lab_report_count": released_lab_reports(patient).count(),
        "record_request_count": record_requests(patient).filter(
            status__in=["pending", "processing"]
        ).count(),
    }


def paid_total(patient) -> Decimal:
    total = patient_bills(patient).aggregate(total=Sum("paid_amount"))["total"]
    return total or Decimal("0.00")
