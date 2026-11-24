"""Management-command tests for the Reports & Analytics module."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from ..models import ReportRun
from . import factories

pytestmark = pytest.mark.django_db


def test_command_runs_due_schedules():
    factories.make_schedule(next_run=timezone.now() - timedelta(hours=1))
    call_command("send_scheduled_reports")
    assert ReportRun.objects.count() == 1


def test_command_dry_run_creates_nothing():
    factories.make_schedule(next_run=timezone.now() - timedelta(hours=1))
    call_command("send_scheduled_reports", "--dry-run")
    assert ReportRun.objects.count() == 0


def test_command_now_forces_all(capsys):
    factories.make_schedule(
        name="Future", next_run=timezone.now() + timedelta(days=5)
    )
    call_command("send_scheduled_reports", "--now")
    assert ReportRun.objects.count() == 1
