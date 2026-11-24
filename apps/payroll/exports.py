"""Export helpers for the Payroll module (RULES Phase 14).

Two exports live here:

* the **payroll register** (CSV / Excel) — reuses the accounting exporter; and
* the **BEFTN salary file** — a bank-upload CSV with the beneficiary account,
  routing number and net amount, plus a header and trailer control record.
"""

from __future__ import annotations

import csv
import io

from django.utils import timezone

from apps.accounting.exports import export_response

from . import selectors
from .models import PaymentMethod

# BEFTN credit transaction code for inter-bank salary credit (ICT-22).
BEFTN_CREDIT_CODE = "22"


def register_response(request, run):
    """Return a CSV/XLSX payroll-register response, or ``None``."""
    return export_response(
        request,
        filename=f"payroll-register-{run.code}",
        title=f"Payroll register · {run.code}",
        headers=selectors.REGISTER_HEADERS,
        rows=selectors.register_rows(run),
    )


def _beneficiaries(run):
    """Yield bank-paid payslips that have enough data for a BEFTN credit."""
    qs = run.payslips.select_related("staff").order_by("employee_code")
    for slip in qs:
        if slip.payment_method != PaymentMethod.BANK:
            continue
        if not slip.bank_account_no or not slip.net_pay:
            continue
        yield slip


def build_beftn_file(run, *, settings_obj=None) -> str:
    """Return the BEFTN salary CSV as a string.

    Layout (one CSV per batch)::

        # BEFTN SALARY FILE,<company>,<run code>,<value date>,<currency>
        Beneficiary Name,Bank Account No,Routing No,Amount,Transaction Code,
        Employee Code,Bank Name,Remarks
        ...
        # TRAILER,<record count>,<total amount>
    """
    from .services import get_settings

    config = settings_obj or get_settings()
    company = config.beftn_company_name or "IHMS"
    value_date = (run.payment_date or run.period_end).strftime("%Y%m%d")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "# BEFTN SALARY FILE",
            company,
            run.code,
            value_date,
            "BDT",
            config.beftn_company_account,
            config.beftn_bank_code,
        ]
    )
    writer.writerow(
        [
            "Beneficiary Name",
            "Bank Account No",
            "Routing No",
            "Amount",
            "Transaction Code",
            "Employee Code",
            "Bank Name",
            "Remarks",
        ]
    )
    count = 0
    total = 0
    for slip in _beneficiaries(run):
        amount = slip.net_pay
        acc = (slip.bank_account_no or "").strip()
        rout = (slip.bank_routing_no or "").strip()
        if not acc:
            continue
        if rout and (not rout.isdigit() or len(rout) != 9):
            continue
        writer.writerow(
            [
                slip.name,
                acc,
                rout,
                f"{amount:.2f}",
                BEFTN_CREDIT_CODE,
                slip.employee_code,
                slip.bank_name,
                f"Salary {run.code}",
            ]
        )
        count += 1
        total += amount
    writer.writerow(["# TRAILER", count, f"{total:.2f}"])
    return buffer.getvalue()


def validate_beftn(run) -> dict:
    """Return validation issues and readiness for a BEFTN export."""
    from .models import PaymentMethod

    issues = []
    valid_count = 0
    qs = run.payslips.select_related("staff").order_by("employee_code")
    for slip in qs:
        if slip.payment_method != PaymentMethod.BANK:
            continue
        if not slip.bank_account_no or not slip.net_pay:
            issues.append((slip.employee_code, slip.name, "Missing bank account or net pay"))
            continue
        acc = slip.bank_account_no.strip()
        rout = slip.bank_routing_no.strip() if slip.bank_routing_no else ""
        if not acc:
            issues.append((slip.employee_code, slip.name, "Invalid bank account number"))
            continue
        if rout and not rout.isdigit():
            issues.append((slip.employee_code, slip.name, "Invalid routing number"))
            continue
        if rout and len(rout) != 9:
            issues.append((slip.employee_code, slip.name, "Routing number must be 9 digits"))
            continue
        valid_count += 1
    return {"valid": valid_count, "issues": issues, "total": qs.count()}


def beftn_response(run):
    """Return a downloadable BEFTN CSV response."""
    from django.core.exceptions import ValidationError
    from django.http import HttpResponse
    from django.utils.translation import gettext as _

    from .models import PayrollRunStatus

    if run.status not in (PayrollRunStatus.APPROVED, PayrollRunStatus.PAID):
        raise ValidationError(
            _("BEFTN export is only available for approved or paid runs.")
        )
    content = build_beftn_file(run)
    stamp = timezone.localdate().strftime("%Y%m%d")
    filename = f"beftn-{run.code}-{stamp}.csv"
    response = HttpResponse(content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def beftn_summary(run) -> dict:
    """Quick stats for the UI: number and value of bank credits."""
    count = 0
    total = 0
    for slip in _beneficiaries(run):
        count += 1
        total += slip.net_pay
    return {"count": count, "total": total}


def salary_structure_rows(staff_qs):
    """Flatten staff salary structures for report/export."""
    rows = []
    for member in staff_qs:
        rows.append(
            [
                member.employee_code,
                member.display_name,
                str(member.department or ""),
                str(member.designation or ""),
                member.get_tax_category_display(),
                "Yes" if member.pf_eligible else "No",
                member.basic_salary,
                member.house_rent,
                member.medical_allowance,
                member.transport_allowance,
                member.other_allowance,
                member.gross_salary,
            ]
        )
    return rows


SALARY_STRUCTURE_HEADERS = [
    "Employee code",
    "Name",
    "Department",
    "Designation",
    "Tax category",
    "PF eligible",
    "Basic",
    "House rent",
    "Medical",
    "Transport",
    "Other",
    "Gross",
]
