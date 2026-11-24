"""CSV / XLSX / PDF export helpers for hospital reports (RULES Phase 16).

Every report is exported from the same normalised dictionary produced by
:mod:`apps.reports.selectors`, so a new report automatically gains all three
formats. PDF rendering uses WeasyPrint; Excel uses :mod:`openpyxl` and degrades
gracefully to CSV when it is unavailable.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.functional import Promise


def _plain(value):
    """Coerce a cell value to something openpyxl / CSV can serialise."""
    if isinstance(value, Promise):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return value


def _csv_bytes(report: dict) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([report["title"]])
    if report.get("start"):
        writer.writerow([f"{report['start']} to {report['end']}"])
    writer.writerow(report["columns"])
    for row in report["rows"]:
        writer.writerow([_plain(cell) for cell in row])
    if report.get("totals"):
        writer.writerow([_plain(cell) for cell in report["totals"]])
    return buffer.getvalue().encode("utf-8-sig")


def _xlsx_bytes(report: dict, *, title: str = "") -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:  # pragma: no cover - openpyxl is a declared dependency
        return _csv_bytes(report)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = (title or report["title"])[:31]
    sheet.append([str(report["title"])])
    sheet["A1"].font = Font(bold=True, size=13)
    if report.get("start"):
        sheet.append([f"{report['start']} to {report['end']}"])
    sheet.append([])
    header_row = sheet.max_row + 1
    sheet.append([_plain(c) for c in report["columns"]])
    for cell in sheet[header_row]:
        cell.font = Font(bold=True)
    for row in report["rows"]:
        sheet.append([_plain(cell) for cell in row])
    if report.get("totals"):
        sheet.append([_plain(cell) for cell in report["totals"]])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _pdf_bytes(report: dict, *, request=None, hospital=None) -> bytes:
    from weasyprint import HTML

    if hospital is None:
        from apps.masters.models import HospitalProfile

        hospital = HospitalProfile.load()
    html = render_to_string(
        "reports/report_pdf.html",
        {"report": report, "hospital": hospital},
        request=request,
    )
    base_url = request.build_absolute_uri("/") if request else None
    return HTML(string=html, base_url=base_url).write_pdf()


CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}

EXTENSIONS = {"csv": "csv", "xlsx": "xlsx", "pdf": "pdf"}


def render_report(report: dict, fmt: str, *, request=None, hospital=None) -> bytes:
    """Render ``report`` in ``fmt`` (``csv`` / ``xlsx`` / ``pdf``) as bytes."""
    fmt = (fmt or "csv").lower()
    if fmt == "pdf":
        return _pdf_bytes(report, request=request, hospital=hospital)
    if fmt == "xlsx":
        return _xlsx_bytes(report)
    return _csv_bytes(report)


def report_filename(report: dict, fmt: str) -> str:
    stamp = timezone.localdate().isoformat()
    return f"{report['key']}-{stamp}.{EXTENSIONS.get(fmt, 'csv')}"


def export_response(request, report: dict, *, filename: str | None = None):
    """Return an export response for ``?export=csv|xlsx|pdf``, else ``None``."""
    fmt = (request.GET.get("export") or "").lower()
    if fmt not in CONTENT_TYPES:
        return None
    payload = render_report(report, fmt, request=request)
    name = filename or report_filename(report, fmt)
    response = HttpResponse(payload, content_type=CONTENT_TYPES[fmt])
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response
