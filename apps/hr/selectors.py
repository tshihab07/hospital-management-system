"""Read-side helpers for the HR module."""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

from django.db.models import Q, Sum

from .models import Attendance, DutyRoster, LeaveRequest, LeaveStatus, Staff


def staff_list(
    *, search: str = "", department=None, status: str = "", designation=None
):
    qs = Staff.objects.select_related("department", "designation", "shift")
    if search:
        qs = qs.filter(
            Q(name_en__icontains=search)
            | Q(name_bn__icontains=search)
            | Q(employee_code__icontains=search)
            | Q(phone__icontains=search)
        )
    if department:
        qs = qs.filter(department=department)
    if designation:
        qs = qs.filter(designation=designation)
    if status:
        qs = qs.filter(status=status)
    return qs


def attendance_list(
    *,
    staff: Staff | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    source: str = "",
):
    qs = Attendance.objects.select_related("staff")
    if staff:
        qs = qs.filter(staff=staff)
    if date_from:
        qs = qs.filter(att_date__gte=date_from)
    if date_to:
        qs = qs.filter(att_date__lte=date_to)
    if source:
        qs = qs.filter(source=source)
    return qs


def attendance_summary(*, date_from: dt.date, date_to: dt.date) -> dict:
    rows = attendance_list(date_from=date_from, date_to=date_to)
    summary = {"total": rows.count()}
    for value, _label in Attendance._meta.get_field("status").choices:
        summary[value] = rows.filter(status=value).count()
    return summary


def leave_list(*, status: str = "", staff: Staff | None = None):
    qs = LeaveRequest.objects.select_related("staff", "leave_type", "decided_by")
    if status:
        qs = qs.filter(status=status)
    if staff:
        qs = qs.filter(staff=staff)
    return qs


def pending_leave_count() -> int:
    return LeaveRequest.objects.filter(status=LeaveStatus.PENDING).count()


def roster_week(*, week_start: dt.date, department=None):
    week_end = week_start + dt.timedelta(days=6)
    qs = (
        DutyRoster.objects.select_related("staff", "staff__department", "shift")
        .filter(duty_date__range=(week_start, week_end))
        .order_by("staff__name_en", "duty_date")
    )
    if department:
        qs = qs.filter(staff__department=department)
    return qs


def _month_range(year: int, month: int) -> tuple[dt.date, dt.date]:
    last_day = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last_day)


def doctor_performance(*, year: int, month: int) -> list[dict]:
    """Patients seen and revenue generated per doctor for a month."""
    from apps.opd.models import Appointment, AppointmentStatus, Doctor

    start, end = _month_range(year, month)
    rows = []
    for doctor in Doctor.objects.all().order_by("name_en"):
        completed = Appointment.objects.filter(
            doctor=doctor,
            status=AppointmentStatus.COMPLETED,
            appt_date__range=(start, end),
        )
        seen = completed.count()
        revenue = completed.aggregate(total=Sum("consultation_fee"))[
            "total"
        ] or Decimal("0")
        share = (revenue * doctor.revenue_share_pct / Decimal("100")).quantize(
            Decimal("0.01")
        )
        rows.append(
            {
                "doctor": doctor,
                "patients_seen": seen,
                "revenue": revenue,
                "revenue_share": share,
            }
        )
    return rows
