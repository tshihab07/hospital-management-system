"""Selector tests for the Reports & Analytics module."""

from __future__ import annotations

import pytest

from .. import selectors
from ..models import ReportType

pytestmark = pytest.mark.django_db

REPORT_TYPES = [
    ReportType.DAILY_CENSUS,
    ReportType.MONTHLY_REVENUE,
    ReportType.DOCTOR_PERFORMANCE,
    ReportType.DEPARTMENT_PROFITABILITY,
    ReportType.INVENTORY_CONSUMPTION,
    ReportType.BED_OCCUPANCY,
    ReportType.ER_WAIT_TIMES,
    ReportType.VAT,
    ReportType.COLLECTION,
    ReportType.PAYROLL,
    ReportType.PNL,
]

REQUIRED_KEYS = {
    "key",
    "title",
    "description",
    "start",
    "end",
    "columns",
    "rows",
    "align",
    "formats",
    "totals",
    "summary",
    "chart",
    "meta",
}


@pytest.mark.parametrize("report_type", REPORT_TYPES)
def test_build_report_shape(report_type):
    report = selectors.build_report(report_type)
    assert REQUIRED_KEYS.issubset(report.keys())
    assert report["key"] == str(report_type)
    assert isinstance(report["columns"], list)
    assert len(report["align"]) == len(report["columns"])
    assert len(report["formats"]) == len(report["columns"])


def test_build_report_unknown_falls_back_to_census():
    report = selectors.build_report("does-not-exist")
    assert report["key"] == str(ReportType.DAILY_CENSUS)


def test_dashboard_kpis_keys():
    kpis = selectors.dashboard_kpis()
    for section in (
        "patients",
        "opd",
        "ipd",
        "er",
        "lab",
        "pharmacy",
        "billing",
        "accounting",
        "payroll",
    ):
        assert section in kpis


def test_dashboard_alerts_is_a_list():
    alerts = selectors.dashboard_alerts()
    assert isinstance(alerts, list)
    for alert in alerts:
        assert alert["level"] in ("danger", "warning", "info")
        assert "title" in alert
        assert "count" in alert
        assert "url_name" in alert


def test_default_range_respects_parameters():
    from datetime import date

    start, end = selectors.default_range(
        parameters={"start": "2026-01-01", "end": "2026-01-31"}
    )
    assert start == date(2026, 1, 1)
    assert end == date(2026, 1, 31)


def test_build_report_respects_explicit_range():
    from datetime import date

    start = date(2026, 1, 1)
    end = date(2026, 1, 10)
    report = selectors.build_report(ReportType.DAILY_CENSUS, start=start, end=end)
    assert report["start"] == start
    assert report["end"] == end
    assert len(report["rows"]) == 10
