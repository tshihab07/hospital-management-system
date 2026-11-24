"""Service tests for the Reports & Analytics module."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from .. import services
from ..models import ReportFormat, ReportRun, ReportRunStatus, ReportType
from . import factories

pytestmark = pytest.mark.django_db


def test_generate_report_csv_creates_run():
    run = services.generate_report(ReportType.DAILY_CENSUS, report_format="csv")
    assert run.status == ReportRunStatus.SUCCESS
    assert run.pk is not None
    assert run.file
    assert run.started_at and run.finished_at


def test_generate_report_xlsx_creates_run():
    run = services.generate_report(ReportType.VAT, report_format=ReportFormat.XLSX)
    assert run.status == ReportRunStatus.SUCCESS
    assert run.file.name.endswith(".xlsx")


def test_generate_report_failure_is_captured(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(services.selectors, "build_report", boom)
    run = services.generate_report(ReportType.PNL, report_format="csv")
    assert run.status == ReportRunStatus.FAILED
    assert "nope" in run.error


def test_run_schedule_emails_recipients():
    schedule = factories.make_schedule(report_format=ReportFormat.CSV)
    run = services.run_schedule(schedule, send_email=True)
    assert run.status == ReportRunStatus.SUCCESS
    assert len(mail.outbox) == 1
    assert "finance@hospital.test" in mail.outbox[0].to


def test_run_schedule_advances_next_run():
    schedule = factories.make_schedule()
    before = schedule.next_run
    services.run_schedule(schedule, send_email=False)
    schedule.refresh_from_db()
    assert schedule.last_run is not None
    assert schedule.next_run > before


def test_advance_next_run_does_not_require_delivery():
    schedule = factories.make_schedule()
    services.advance_next_run(schedule, reference=timezone.now())
    schedule.refresh_from_db()
    assert schedule.next_run is not None


def test_send_scheduled_reports_picks_up_due():
    factories.make_schedule(name="Due now", next_run=timezone.now() - timedelta(hours=1))
    factories.make_schedule(
        name="Future", next_run=timezone.now() + timedelta(days=1)
    )
    stats = services.send_scheduled_reports()
    assert stats["due"] == 1
    assert stats["sent"] == 1
    assert ReportRun.objects.count() == 1


def test_send_scheduled_reports_dry_run_does_not_create():
    factories.make_schedule(next_run=timezone.now() - timedelta(hours=1))
    stats = services.send_scheduled_reports(dry_run=True)
    assert stats["due"] == 1
    assert stats["sent"] == 0
    assert ReportRun.objects.count() == 0
