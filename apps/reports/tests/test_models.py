"""Model tests for the Reports & Analytics module."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ..models import FREQUENCY_DELTAS, ReportFormat, ReportFrequency, ReportRun
from . import factories

pytestmark = pytest.mark.django_db


def test_recipient_list_normalises_commas_and_newlines():
    schedule = factories.make_schedule(recipients="a@x.test, b@x.test\nc@x.test")
    assert schedule.recipient_list == ["a@x.test", "b@x.test", "c@x.test"]


def test_is_due_true_when_past():
    schedule = factories.make_schedule(next_run=timezone.now() - timedelta(hours=1))
    assert schedule.is_due is True


def test_is_due_false_when_future():
    schedule = factories.make_schedule(next_run=timezone.now() + timedelta(hours=1))
    assert schedule.is_due is False


def test_is_due_false_when_inactive():
    schedule = factories.make_schedule(
        next_run=timezone.now() - timedelta(hours=1), is_active=False
    )
    assert schedule.is_due is False


@pytest.mark.parametrize("frequency", list(ReportFrequency.values))
def test_compute_next_run_advances(frequency):
    base = timezone.now()
    schedule = factories.make_schedule(frequency=frequency)
    nxt = schedule.compute_next_run(reference=base)
    assert nxt > base
    if frequency in (ReportFrequency.DAILY, ReportFrequency.WEEKLY):
        assert nxt == base + FREQUENCY_DELTAS[frequency]


def test_report_run_filename_and_duration():
    started = timezone.now()
    run = ReportRun.objects.create(
        report_type="daily_census",
        report_format=ReportFormat.CSV,
        started_at=started,
        finished_at=started + timedelta(seconds=3),
    )
    assert run.filename == ""
    assert run.duration_seconds == 3.0


def test_str_methods():
    schedule = factories.make_schedule(name="Weekly P&L")
    assert "Weekly P&L" in str(schedule)
    run = ReportRun.objects.create(report_type="pnl", report_format=ReportFormat.CSV)
    assert "Profit" in str(run)
