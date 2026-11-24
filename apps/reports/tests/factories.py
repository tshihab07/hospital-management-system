"""Shared test factories for the Reports & Analytics module."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import Permission
from django.utils import timezone

from apps.accounts.models import Role, User

from ..models import ReportFormat, ReportFrequency, ReportSchedule, ReportType


def make_user(*permission_specs: str, username: str = "reports-user") -> User:
    """Create a user whose role holds the given ``app.codename`` permissions."""
    role, _ = Role.objects.get_or_create(name="RPT-" + "-".join(permission_specs))
    role.permissions.clear()
    for spec in permission_specs:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(role)
    return user


def make_schedule(
    *,
    name: str = "Nightly census",
    report_type: str = ReportType.DAILY_CENSUS,
    frequency: str = ReportFrequency.DAILY,
    report_format: str = ReportFormat.CSV,
    recipients: str = "finance@hospital.test",
    next_run=None,
    is_active: bool = True,
    created_by=None,
) -> ReportSchedule:
    if next_run is None:
        next_run = timezone.now() - timedelta(minutes=5)
    return ReportSchedule.objects.create(
        name=name,
        report_type=report_type,
        frequency=frequency,
        report_format=report_format,
        recipients=recipients,
        next_run=next_run,
        is_active=is_active,
        created_by=created_by,
    )
