"""View-level tests for the Reports & Analytics module."""

from __future__ import annotations

import pytest
from django.urls import reverse

from ..models import ReportFormat, ReportRun, ReportSchedule, ReportType
from . import factories

pytestmark = pytest.mark.django_db

PERMS = [
    "reports.view_hospitalreports",
    "reports.export_hospitalreports",
    "reports.view_reportschedule",
    "reports.add_reportschedule",
    "reports.change_reportschedule",
    "reports.delete_reportschedule",
    "reports.run_reportschedule",
    "reports.view_reportrun",
]

REPORT_PAGES = [
    "reports:daily_census",
    "reports:monthly_revenue",
    "reports:doctor_performance",
    "reports:department_profitability",
    "reports:inventory_consumption",
    "reports:bed_occupancy",
    "reports:er_wait_times",
    "reports:vat",
    "reports:collection",
    "reports:payroll",
    "reports:pnl",
]


@pytest.fixture
def client_logged(client):
    client.force_login(factories.make_user(*PERMS))
    return client


def test_dashboard_renders(client_logged):
    assert client_logged.get(reverse("reports:dashboard")).status_code == 200


@pytest.mark.parametrize("url_name", REPORT_PAGES)
def test_report_pages_render(client_logged, url_name):
    resp = client_logged.get(reverse(url_name))
    assert resp.status_code == 200


@pytest.mark.parametrize("url_name", REPORT_PAGES)
def test_report_pages_render_with_range(client_logged, url_name):
    resp = client_logged.get(
        reverse(url_name), {"start": "2026-01-01", "end": "2026-01-15"}
    )
    assert resp.status_code == 200


def test_report_export_csv(client_logged):
    resp = client_logged.get(reverse("reports:daily_census"), {"export": "csv"})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert "attachment" in resp["Content-Disposition"]


def test_report_export_xlsx(client_logged):
    resp = client_logged.get(reverse("reports:vat"), {"export": "xlsx"})
    assert resp.status_code == 200
    assert "spreadsheetml" in resp["Content-Type"]


def test_report_export_pdf(client_logged):
    resp = client_logged.get(reverse("reports:pnl"), {"export": "pdf"})
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


def test_export_requires_export_permission(client):
    client.force_login(
        factories.make_user("reports.view_hospitalreports")
    )
    resp = client.get(reverse("reports:pnl"), {"export": "csv"})
    assert resp.status_code == 403


def test_schedule_list_renders(client_logged):
    factories.make_schedule()
    assert client_logged.get(reverse("reports:schedule_list")).status_code == 200


def test_schedule_create_get(client_logged):
    assert client_logged.get(reverse("reports:schedule_create")).status_code == 200


def test_schedule_create_post(client_logged):
    resp = client_logged.post(
        reverse("reports:schedule_create"),
        {
            "name": "Monthly P&L",
            "report_type": ReportType.PNL,
            "frequency": "monthly",
            "report_format": ReportFormat.PDF,
            "recipients": "boss@hospital.test",
            "is_active": "on",
            "next_run": "2026-11-01T09:00",
        },
    )
    assert resp.status_code == 302
    schedule = ReportSchedule.objects.get(name="Monthly P&L")
    assert schedule.recipients == "boss@hospital.test"
    assert schedule.next_run is not None


def test_schedule_create_rejects_bad_email(client_logged):
    resp = client_logged.post(
        reverse("reports:schedule_create"),
        {
            "name": "Bad",
            "report_type": ReportType.PNL,
            "frequency": "monthly",
            "report_format": ReportFormat.PDF,
            "recipients": "not-an-email",
            "is_active": "on",
        },
    )
    assert resp.status_code == 200
    assert not ReportSchedule.objects.filter(name="Bad").exists()


def test_schedule_update(client_logged):
    schedule = factories.make_schedule()
    resp = client_logged.post(
        reverse("reports:schedule_update", args=[schedule.pk]),
        {
            "name": "Renamed",
            "report_type": schedule.report_type,
            "frequency": schedule.frequency,
            "report_format": schedule.report_format,
            "recipients": "new@hospital.test",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    schedule.refresh_from_db()
    assert schedule.name == "Renamed"


def test_schedule_delete_soft_removes(client_logged):
    schedule = factories.make_schedule()
    resp = client_logged.post(reverse("reports:schedule_delete", args=[schedule.pk]))
    assert resp.status_code == 302
    assert not ReportSchedule.objects.filter(pk=schedule.pk).exists()


def test_schedule_run_now(client_logged):
    schedule = factories.make_schedule(report_format=ReportFormat.CSV)
    resp = client_logged.post(reverse("reports:schedule_run", args=[schedule.pk]))
    assert resp.status_code == 302
    assert ReportRun.objects.filter(schedule=schedule).exists()


def test_run_list_and_detail(client_logged):
    schedule = factories.make_schedule(report_format=ReportFormat.CSV)
    from .. import services

    run = services.run_schedule(schedule, send_email=False)
    assert client_logged.get(reverse("reports:run_list")).status_code == 200
    detail = client_logged.get(reverse("reports:run_detail", args=[run.pk]))
    assert detail.status_code == 200


def test_run_download(client_logged):
    from .. import services

    run = services.generate_report(ReportType.PNL, report_format="csv")
    resp = client_logged.get(reverse("reports:run_download", args=[run.pk]))
    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]


def test_requires_permission(client):
    client.force_login(factories.make_user())  # no reports perms
    resp = client.get(reverse("reports:dashboard"))
    assert resp.status_code in (302, 403)
