"""Service-layer tests for HR (attendance, roster, leave workflow)."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.hr import services
from apps.hr.models import (Attendance, AttendanceSource, AttendanceStatus,
                            DutyRoster, LeaveBalance, LeaveRequest,
                            LeaveStatus, LeaveType, Shift, Staff)

pytestmark = pytest.mark.django_db


def _staff(code="EMP-S1", **overrides) -> Staff:
    data = {"employee_code": code, "name_en": "Service Staff"}
    data.update(overrides)
    return Staff.objects.create(**data)


def _shift() -> Shift:
    return Shift.objects.create(
        name="Morning", code="MORN", start_time=dt.time(8, 0), end_time=dt.time(14, 0)
    )


def _leave_type(**overrides) -> LeaveType:
    data = {"name": "Casual", "code": "CL", "max_days_per_year": 10}
    data.update(overrides)
    return LeaveType.objects.create(**data)


def test_upsert_attendance_creates_then_updates():
    member = _staff()
    att, created = services.upsert_attendance(
        staff=member, att_date=dt.date(2026, 5, 1), status=AttendanceStatus.PRESENT
    )
    assert created is True
    again, created2 = services.upsert_attendance(
        staff=member, att_date=dt.date(2026, 5, 1), status=AttendanceStatus.LATE
    )
    assert created2 is False
    assert again.pk == att.pk
    assert again.status == AttendanceStatus.LATE
    assert Attendance.objects.count() == 1


def test_import_attendance_rows_creates_and_reports_errors():
    member = _staff(code="EMP-X")
    rows = [
        {
            "employee_code": "EMP-X",
            "date": "2026-05-01",
            "check_in": "09:00",
            "check_out": "17:00",
        },
        {"employee_code": "EMP-MISSING", "date": "2026-05-01"},
    ]
    summary = services.import_attendance_rows(rows=rows, device_id="BIO-1")
    assert summary["created"] == 1
    assert len(summary["errors"]) == 1
    record = Attendance.objects.get(staff=member)
    assert record.source == AttendanceSource.BIOMETRIC
    assert record.device_id == "BIO-1"


def test_import_attendance_rows_updates_existing():
    member = _staff(code="EMP-U")
    services.upsert_attendance(staff=member, att_date=dt.date(2026, 5, 2))
    summary = services.import_attendance_rows(
        rows=[{"employee_code": "EMP-U", "date": "2026-05-02", "status": "late"}]
    )
    assert summary["updated"] == 1
    assert Attendance.objects.get(staff=member).status == AttendanceStatus.LATE


def test_assign_roster_is_idempotent():
    member = _staff()
    shift = _shift()
    dates = [dt.date(2026, 5, 4), dt.date(2026, 5, 5)]
    services.assign_roster(staff=member, shift=shift, dates=dates)
    services.assign_roster(staff=member, shift=shift, dates=dates)
    assert DutyRoster.objects.filter(staff=member).count() == 2


def test_publish_roster_marks_week_published():
    member = _staff()
    shift = _shift()
    week_start = dt.date(2026, 5, 4)
    services.assign_roster(
        staff=member, shift=shift, dates=[week_start, week_start + dt.timedelta(days=1)]
    )
    count = services.publish_roster(week_start=week_start)
    assert count == 2
    assert not DutyRoster.objects.filter(is_published=False).exists()


def test_apply_leave_rejects_overlap():
    member = _staff()
    leave_type = _leave_type()
    services.apply_leave(
        staff=member,
        leave_type=leave_type,
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 3),
    )
    with pytest.raises(ValueError):
        services.apply_leave(
            staff=member,
            leave_type=leave_type,
            start_date=dt.date(2026, 6, 3),
            end_date=dt.date(2026, 6, 5),
        )


def test_apply_leave_rejects_reversed_dates():
    member = _staff()
    leave_type = _leave_type()
    with pytest.raises(ValueError):
        services.apply_leave(
            staff=member,
            leave_type=leave_type,
            start_date=dt.date(2026, 6, 5),
            end_date=dt.date(2026, 6, 1),
        )


def test_approve_leave_consumes_balance():
    member = _staff()
    leave_type = _leave_type(max_days_per_year=12)
    leave = services.apply_leave(
        staff=member,
        leave_type=leave_type,
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 2),
    )
    services.approve_leave(leave=leave)
    leave.refresh_from_db()
    assert leave.status == LeaveStatus.APPROVED
    balance = LeaveBalance.objects.get(staff=member, leave_type=leave_type, year=2026)
    assert balance.used_days == 2
    assert balance.entitled_days == 12


def test_reject_leave_keeps_balance_untouched():
    member = _staff()
    leave_type = _leave_type()
    leave = services.apply_leave(
        staff=member,
        leave_type=leave_type,
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 1),
    )
    services.reject_leave(leave=leave, note="busy")
    leave.refresh_from_db()
    assert leave.status == LeaveStatus.REJECTED
    assert not LeaveBalance.objects.exists()


def test_cancel_approved_leave_restores_balance():
    member = _staff()
    leave_type = _leave_type()
    leave = services.apply_leave(
        staff=member,
        leave_type=leave_type,
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 3),
    )
    services.approve_leave(leave=leave)
    services.cancel_leave(leave=leave)
    balance = LeaveBalance.objects.get(staff=member, leave_type=leave_type, year=2026)
    assert balance.used_days == 0


def test_approve_requires_pending_status():
    member = _staff()
    leave_type = _leave_type()
    leave = services.apply_leave(
        staff=member,
        leave_type=leave_type,
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 1),
    )
    services.reject_leave(leave=leave)
    with pytest.raises(ValueError):
        services.approve_leave(leave=leave)
