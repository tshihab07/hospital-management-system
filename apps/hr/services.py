"""Write operations for HR (atomic + audit).

Covers attendance upserts/imports, weekly roster generation/publication and the
leave apply/approve/reject/cancel workflow with balance updates.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.audit import AuditAction, log_action, model_to_dict_safe

from .models import (Attendance, AttendanceSource, AttendanceStatus,
                     DutyRoster, LeaveBalance, LeaveRequest, LeaveStatus,
                     Staff)


def _diff(before: dict, after: dict) -> dict:
    changed = {}
    for key, value in after.items():
        if key in {"updated_at", "created_at"}:
            continue
        if before.get(key) != value:
            changed[key] = {"from": before.get(key), "to": value}
    return changed


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
@transaction.atomic
def upsert_attendance(
    *,
    staff: Staff,
    att_date: dt.date,
    status: str = AttendanceStatus.PRESENT,
    check_in=None,
    check_out=None,
    source: str = AttendanceSource.MANUAL,
    device_id: str = "",
    remarks: str = "",
    actor=None,
    request=None,
) -> tuple[Attendance, bool]:
    """Create or update one attendance row; returns ``(record, created)``."""
    attendance, created = Attendance.objects.update_or_create(
        staff=staff,
        att_date=att_date,
        defaults={
            "status": status,
            "check_in": check_in,
            "check_out": check_out,
            "source": source,
            "device_id": device_id,
            "remarks": remarks,
        },
    )
    if created:
        log_action(
            AuditAction.CREATE,
            instance=attendance,
            changes=model_to_dict_safe(attendance),
            user=actor,
            request=request,
        )
    else:
        log_action(
            AuditAction.UPDATE,
            instance=attendance,
            changes={"status": {"to": status}, "source": source},
            user=actor,
            request=request,
        )
    return attendance, created


def _parse_date(value) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value).strip())


def _parse_time(value):
    if value in (None, "", "None"):
        return None
    if isinstance(value, dt.time):
        return value
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p"):
        try:
            return dt.datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(_("Unrecognised time value: %(value)s") % {"value": value})


@transaction.atomic
def import_attendance_rows(
    *, rows, device_id: str = "", actor=None, request=None
) -> dict:
    """Upsert biometric attendance ``rows`` keyed by employee code.

    Each row is a mapping with ``employee_code``, ``date`` and optional
    ``check_in`` / ``check_out`` / ``status``. Returns a summary dict.
    """
    summary = {"created": 0, "updated": 0, "errors": []}
    by_code = {s.employee_code: s for s in Staff.objects.all()}

    for index, row in enumerate(rows):
        try:
            code = str(row.get("employee_code", "")).strip()
            staff = by_code.get(code)
            if staff is None:
                raise ValueError(_("Unknown employee code: %(code)s") % {"code": code})
            att_date = _parse_date(row.get("date"))
            status_value = (
                str(row.get("status") or AttendanceStatus.PRESENT).strip().lower()
            )
            valid_status = {c for c, _ in AttendanceStatus.choices}
            if status_value not in valid_status:
                status_value = AttendanceStatus.PRESENT
            _record, created = upsert_attendance(
                staff=staff,
                att_date=att_date,
                status=status_value,
                check_in=_parse_time(row.get("check_in")),
                check_out=_parse_time(row.get("check_out")),
                source=AttendanceSource.BIOMETRIC,
                device_id=device_id,
                actor=actor,
                request=request,
            )
            summary["created" if created else "updated"] += 1
        except (ValueError, KeyError) as exc:
            summary["errors"].append({"row": index + 1, "error": str(exc)})
    return summary


# ---------------------------------------------------------------------------
# Duty roster
# ---------------------------------------------------------------------------
@transaction.atomic
def assign_roster(
    *, staff: Staff, shift, dates, notes: str = "", actor=None, request=None
) -> list[DutyRoster]:
    """Assign ``shift`` to ``staff`` for each date in ``dates`` (idempotent)."""
    entries = []
    for duty_date in dates:
        entry, _created = DutyRoster.objects.get_or_create(
            staff=staff,
            duty_date=duty_date,
            defaults={"shift": shift, "notes": notes},
        )
        entries.append(entry)
    log_action(
        AuditAction.UPDATE,
        model_name="hr.dutyroster",
        object_repr=f"{staff} x{len(entries)}",
        changes={"dates": [d.isoformat() for d in dates], "shift": str(shift)},
        user=actor,
        request=request,
    )
    return entries


@transaction.atomic
def publish_roster(*, week_start: dt.date, actor=None, request=None) -> int:
    """Publish every roster entry in the week beginning ``week_start``."""
    week_end = week_start + dt.timedelta(days=6)
    count = DutyRoster.objects.filter(
        duty_date__range=(week_start, week_end), is_published=False
    ).update(
        is_published=True,
        published_at=timezone.now(),
        published_by=actor,
    )
    log_action(
        AuditAction.UPDATE,
        model_name="hr.dutyroster",
        object_repr=f"week {week_start}",
        changes={"published": count},
        user=actor,
        request=request,
    )
    return count


# ---------------------------------------------------------------------------
# Leave workflow
# ---------------------------------------------------------------------------
def compute_leave_days(start_date: dt.date, end_date: dt.date) -> int:
    return (end_date - start_date).days + 1


@transaction.atomic
def apply_leave(
    *,
    staff: Staff,
    leave_type,
    start_date: dt.date,
    end_date: dt.date,
    reason: str = "",
    actor=None,
    request=None,
) -> LeaveRequest:
    """Submit a leave request; rejects overlaps with active leaves."""
    if end_date < start_date:
        raise ValueError(_("End date cannot be before the start date."))
    overlap = LeaveRequest.objects.filter(
        staff=staff,
        status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED],
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).exists()
    if overlap:
        raise ValueError(_("This leave overlaps an existing pending/approved leave."))

    leave = LeaveRequest(
        staff=staff,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        applied_by=actor,
    )
    leave.save()
    log_action(
        AuditAction.CREATE,
        instance=leave,
        changes=model_to_dict_safe(leave),
        user=actor,
        request=request,
    )
    return leave


def _balance_for(staff: Staff, leave_type, year: int) -> LeaveBalance:
    balance, _created = LeaveBalance.objects.get_or_create(
        staff=staff,
        leave_type=leave_type,
        year=year,
        defaults={"entitled_days": leave_type.max_days_per_year},
    )
    return balance


@transaction.atomic
def approve_leave(
    *, leave: LeaveRequest, note: str = "", actor=None, request=None
) -> LeaveRequest:
    """Approve a pending leave and consume the matching balance."""
    if not leave.is_pending:
        raise ValueError(_("Only pending leave requests can be approved."))
    leave.status = LeaveStatus.APPROVED
    leave.decided_by = actor
    leave.decided_at = timezone.now()
    leave.decision_note = note
    leave.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])

    balance = _balance_for(leave.staff, leave.leave_type, leave.start_date.year)
    balance.used_days += leave.days
    balance.save(update_fields=["used_days", "updated_at"])

    log_action(
        AuditAction.APPROVE,
        instance=leave,
        changes={"status": {"to": LeaveStatus.APPROVED}, "days": leave.days},
        user=actor,
        request=request,
    )
    return leave


@transaction.atomic
def reject_leave(
    *, leave: LeaveRequest, note: str = "", actor=None, request=None
) -> LeaveRequest:
    """Reject a pending leave request."""
    if not leave.is_pending:
        raise ValueError(_("Only pending leave requests can be rejected."))
    leave.status = LeaveStatus.REJECTED
    leave.decided_by = actor
    leave.decided_at = timezone.now()
    leave.decision_note = note
    leave.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
    log_action(
        AuditAction.UPDATE,
        instance=leave,
        changes={"status": {"to": LeaveStatus.REJECTED}},
        user=actor,
        request=request,
    )
    return leave


@transaction.atomic
def cancel_leave(*, leave: LeaveRequest, actor=None, request=None) -> LeaveRequest:
    """Cancel a leave; restores balance when it had been approved."""
    if leave.status in (LeaveStatus.CANCELLED, LeaveStatus.REJECTED):
        raise ValueError(_("This leave request can no longer be cancelled."))
    if leave.status == LeaveStatus.APPROVED:
        balance = _balance_for(leave.staff, leave.leave_type, leave.start_date.year)
        balance.used_days = max(0, balance.used_days - leave.days)
        balance.save(update_fields=["used_days", "updated_at"])
    leave.status = LeaveStatus.CANCELLED
    leave.decided_at = timezone.now()
    leave.save(update_fields=["status", "decided_at"])
    log_action(
        AuditAction.UPDATE,
        instance=leave,
        changes={"status": {"to": LeaveStatus.CANCELLED}},
        user=actor,
        request=request,
    )
    return leave
