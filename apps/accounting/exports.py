"""CSV / Excel export helpers for accounting reports (RULES Phase 13).

Reports render an ``?export=csv`` or ``?export=xlsx`` response. Excel output
uses :mod:`openpyxl` when available and gracefully degrades to CSV otherwise.
"""

from __future__ import annotations

import csv

from django.http import HttpResponse
from django.utils import timezone
from django.utils.functional import Promise


def _xlsx_value(value):
    """Coerce lazy translation proxies to ``str`` for openpyxl."""
    return str(value) if isinstance(value, Promise) else value


def export_response(
    request, *, filename: str, headers: list[str], rows: list[list], title: str = ""
):
    """Return an export response for the requested format, else ``None``."""
    fmt = (request.GET.get("export") or "").lower()
    if fmt not in {"csv", "xlsx"}:
        return None
    stamp = timezone.localdate().isoformat()
    if fmt == "csv":
        return _csv_response(f"{filename}-{stamp}.csv", headers, rows)
    return _xlsx_response(f"{filename}-{stamp}.xlsx", headers, rows, title or filename)


def _csv_response(name: str, headers: list[str], rows: list[list]) -> HttpResponse:
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response


def _xlsx_response(
    name: str, headers: list[str], rows: list[list], title: str
) -> HttpResponse:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:  # pragma: no cover - openpyxl is a declared dependency
        return _csv_response(name.replace(".xlsx", ".csv"), headers, rows)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Report"
    sheet.append([_xlsx_value(title)])
    sheet["A1"].font = Font(bold=True, size=13)
    sheet.append([])
    sheet.append([_xlsx_value(h) for h in headers])
    for cell in sheet[3]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([_xlsx_value(value) for value in row])
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    workbook.save(response)
    return response
