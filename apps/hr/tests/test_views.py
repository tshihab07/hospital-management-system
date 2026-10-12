"""View / access-control tests for the HR module."""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.hr import services
from apps.hr.models import (Attendance, DutyRoster, LeaveRequest, LeaveType,
                            Shift, Staff)

pytestmark = pytest.mark.django_db


def _role_with(*codenames: str) -> Role:
    name = "HR-" + "-".join(codenames)
    role, _ = Role.objects.get_or_create(name=name)
    role.permissions.clear()
    for spec in codenames:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return role


def _hr_manager():
    role = _role_with(
        "hr.view_staff",
        "hr.add_staff",
        "hr.change_staff",
        "hr.view_shift",
        "hr.add_shift",
        "hr.view_dutyroster",
        "hr.change_dutyroster",
        "hr.view_attendance",
        "hr.add_attendance",
        "hr.change_attendance",
        "hr.view_leavetype",
        "hr.add_leavetype",
        "hr.view_leaverequest",
        "hr.add_leaverequest",
        "hr.change_leaverequest",
        "opd.view_doctor",
    )
    user = User.objects.create_user(username="hr-manager", password="x")
    user.roles.add(role)
    return user


@pytest.fixture
def admin(client):
    user = User.objects.create_superuser(username="root-hr", password="x", email="")
    client.force_login(user)
    return client


def _staff(code="EMP-V1", **overrides) -> Staff:
    data = {"employee_code": code, "name_en": "View Staff"}
    data.update(overrides)
    return Staff.objects.create(**data)


def _shift() -> Shift:
    return Shift.objects.create(
        name="Morning", code="MORN", start_time=dt.time(8, 0), end_time=dt.time(14, 0)
    )


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("hr:staff_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_without_permission_is_403(client):
    user = User.objects.create_user(username="nobody-hr", password="x")
    client.force_login(user)
    assert client.get(reverse("hr:staff_list")).status_code == 403


def test_hr_manager_can_list_staff(client):
    client.force_login(_hr_manager())
    assert client.get(reverse("hr:staff_list")).status_code == 200


def test_staff_create_and_detail(client):
    client.force_login(_hr_manager())
    response = client.post(
        reverse("hr:staff_create"),
        {
            "employee_code": "EMP-9001",
            "name_en": "New Hire",
            "employment_type": "permanent",
            "status": "active",
            "basic_salary": "15000",
            "house_rent": "0",
            "medical_allowance": "0",
            "transport_allowance": "0",
            "other_allowance": "0",
        },
    )
    assert response.status_code == 302
    member = Staff.objects.get(employee_code="EMP-9001")
    assert client.get(reverse("hr:staff_detail", args=[member.pk])).status_code == 200


def test_shift_list_renders(client):
    _shift()
    client.force_login(_hr_manager())
    response = client.get(reverse("hr:shift_list"))
    assert response.status_code == 200


def test_roster_view_and_generate(client):
    member = _staff()
    shift = _shift()
    user = _hr_manager()
    client.force_login(user)
    assert client.get(reverse("hr:roster")).status_code == 200

    week_start = dt.date(2026, 5, 4)
    response = client.post(
        reverse("hr:roster_generate"),
        {
            "staff": member.pk,
            "shift": shift.pk,
            "week_start": week_start.isoformat(),
            "weekdays": ["0", "1"],
            "notes": "",
        },
    )
    assert response.status_code == 302
    assert DutyRoster.objects.filter(staff=member).count() == 2


def test_attendance_mark_creates_record(client):
    member = _staff()
    client.force_login(_hr_manager())
    response = client.post(
        reverse("hr:attendance_mark"),
        {
            "staff": member.pk,
            "att_date": "2026-05-01",
            "status": "present",
            "source": "manual",
            "check_in": "09:00",
            "check_out": "17:00",
            "device_id": "",
            "remarks": "",
        },
    )
    assert response.status_code == 302
    assert Attendance.objects.filter(staff=member).count() == 1


def test_attendance_list_renders(client):
    member = _staff()
    services.upsert_attendance(staff=member, att_date=dt.date(2026, 5, 1))
    client.force_login(_hr_manager())
    response = client.get(reverse("hr:attendance_list"))
    assert response.status_code == 200


def test_leave_apply_and_approve(client):
    member = _staff()
    leave_type = LeaveType.objects.create(
        name="Casual", code="CL", max_days_per_year=10
    )
    user = _hr_manager()
    client.force_login(user)
    response = client.post(
        reverse("hr:leave_apply"),
        {
            "staff": member.pk,
            "leave_type": leave_type.pk,
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
            "reason": "test",
        },
    )
    assert response.status_code == 302
    leave = LeaveRequest.objects.get()
    assert client.get(reverse("hr:leave_detail", args=[leave.pk])).status_code == 200

    response = client.post(
        reverse("hr:leave_decide", args=[leave.pk]),
        {"action": "approve", "note": "ok"},
    )
    assert response.status_code == 302
    leave.refresh_from_db()
    assert leave.status == "approved"


def test_doctor_performance_renders(admin):
    response = admin.get(reverse("hr:doctor_performance"))
    assert response.status_code == 200
