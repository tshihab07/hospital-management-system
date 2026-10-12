"""Model-level tests for the HR module."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.hr.models import Attendance, LeaveRequest, LeaveType, Staff

pytestmark = pytest.mark.django_db


def _staff(**overrides) -> Staff:
    data = {
        "employee_code": "EMP-T1",
        "name_en": "Test Staff",
        "basic_salary": "20000.00",
        "house_rent": "8000.00",
        "medical_allowance": "1500.00",
        "transport_allowance": "1000.00",
        "other_allowance": "500.00",
    }
    data.update(overrides)
    return Staff.objects.create(**data)


def test_gross_salary_sums_components():
    member = _staff()
    assert member.gross_salary == member.basic_salary + member.house_rent + (
        member.medical_allowance + member.transport_allowance + member.other_allowance
    )


def test_display_name_prefers_english():
    member = _staff(name_bn="বাংলা")
    assert member.display_name == "Test Staff"


def test_worked_hours_same_day():
    member = _staff()
    att = Attendance.objects.create(
        staff=member,
        att_date=dt.date(2026, 5, 1),
        check_in=dt.time(9, 0),
        check_out=dt.time(17, 30),
    )
    assert att.worked_hours == pytest.approx(8.5, abs=0.01)


def test_worked_hours_overnight():
    member = _staff()
    att = Attendance.objects.create(
        staff=member,
        att_date=dt.date(2026, 5, 1),
        check_in=dt.time(22, 0),
        check_out=dt.time(6, 0),
    )
    assert att.worked_hours == pytest.approx(8.0, abs=0.01)


def test_worked_hours_none_without_times():
    member = _staff()
    att = Attendance.objects.create(staff=member, att_date=dt.date(2026, 5, 1))
    assert att.worked_hours is None


def test_leave_request_computes_days():
    member = _staff()
    leave_type = LeaveType.objects.create(
        name="Casual", code="CL", max_days_per_year=10
    )
    leave = LeaveRequest.objects.create(
        staff=member,
        leave_type=leave_type,
        start_date=dt.date(2026, 5, 1),
        end_date=dt.date(2026, 5, 3),
    )
    assert leave.days == 3


def test_remaining_days_never_negative():
    from apps.hr.models import LeaveBalance

    member = _staff()
    leave_type = LeaveType.objects.create(name="Sick", code="SL", max_days_per_year=5)
    balance = LeaveBalance.objects.create(
        staff=member, leave_type=leave_type, year=2026, entitled_days=5, used_days=8
    )
    assert balance.remaining_days == 0
