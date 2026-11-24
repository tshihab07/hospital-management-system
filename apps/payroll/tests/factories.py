"""Shared test factories for the Payroll module."""

from __future__ import annotations

import itertools
from datetime import date

from apps.accounts.models import Role, User
from apps.hr.models import Staff

from .. import seed, services

_counter = itertools.count(1)


def make_user(*permission_specs: str, username: str = "payroll-user") -> User:
    """Create a user whose role holds the given ``app.codename`` permissions."""
    from django.contrib.auth.models import Permission

    role, _ = Role.objects.get_or_create(name="PAY-" + "-".join(permission_specs))
    role.permissions.clear()
    for spec in permission_specs:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(role)
    return user


def make_superuser(username: str = "payroll-admin") -> User:
    return User.objects.create_superuser(username=username, password="x", email="")


def make_staff(code: str | None = None, **overrides) -> Staff:
    code = code or f"EMP-{next(_counter):03d}"
    data = {
        "employee_code": code,
        "name_en": f"Payroll Staff {code}",
        "basic_salary": "30000.00",
        "house_rent": "12000.00",
        "medical_allowance": "3000.00",
        "transport_allowance": "2000.00",
        "other_allowance": "1000.00",
        "pf_eligible": True,
    }
    data.update(overrides)
    return Staff.objects.create(**data)


def seed_payroll() -> dict:
    return seed.seed_payroll_defaults()


def make_run(*, year=2026, month=1, **overrides) -> "services.PayrollRun":  # noqa: F821
    return services.generate_run(year=year, month=month, **overrides)


def add_attendance(staff, status, on_day: date):
    from apps.hr.models import Attendance

    return Attendance.objects.create(staff=staff, att_date=on_day, status=status)
