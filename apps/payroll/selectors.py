"""Read helpers for the Payroll module (RULES Phase 14)."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.hr.models import Staff

from .models import PayrollRun, PayrollRunStatus, SalaryAdjustment, TaxSlab


def run_list(*, status: str = "", year: int | None = None):
    qs = PayrollRun.objects.select_related("approved_by", "paid_by").annotate(
        payslip_count=Count("payslips")
    )
    if status:
        qs = qs.filter(status=status)
    if year:
        qs = qs.filter(year=year)
    return qs


def latest_runs(limit: int = 6):
    return PayrollRun.objects.exclude(status=PayrollRunStatus.CANCELLED).order_by(
        "-year", "-month", "-id"
    )[:limit]


def run_payslips(run):
    return run.payslips.select_related("staff").order_by("employee_code")


def payslip_lines(payslip):
    """Return ``(earnings, deductions)`` label/amount pairs for display."""
    earnings = [
        ("Basic", payslip.basic),
        ("House rent", payslip.house_rent),
        ("Medical allowance", payslip.medical_allowance),
        ("Transport allowance", payslip.transport_allowance),
        ("Other allowance", payslip.other_allowance),
    ]
    if payslip.adjustment_earning and payslip.adjustment_earning != 0:
        earnings.append(("Adjustments (+) ", payslip.adjustment_earning))
    deductions = [
        ("Absence", payslip.absence_deduction),
        ("Late attendance", payslip.late_deduction),
        ("Unpaid leave", payslip.unpaid_leave_deduction),
        ("Provident fund", payslip.pf_employee),
        ("Income tax", payslip.tax),
    ]
    if payslip.adjustment_deduction and payslip.adjustment_deduction != 0:
        deductions.append(("Adjustments (−)", payslip.adjustment_deduction))
    return earnings, deductions


def active_tax_slab(
    category: str, assessment_year: str | None = None
) -> TaxSlab | None:
    """Return the newest active slab grid for ``category``."""
    qs = TaxSlab.objects.filter(category=category, is_active=True)
    if assessment_year:
        qs = qs.filter(assessment_year=assessment_year)
    return qs.prefetch_related("brackets").order_by("-assessment_year").first()


def tax_slabs():
    return TaxSlab.objects.prefetch_related("brackets").order_by(
        "-assessment_year", "category"
    )


def adjustment_list(*, status: str = "", staff_id: int | None = None):
    qs = SalaryAdjustment.objects.select_related("staff", "run", "payslip")
    if status:
        qs = qs.filter(status=status)
    if staff_id:
        qs = qs.filter(staff_id=staff_id)
    return qs


def dashboard_kpis(*, year: int | None = None) -> dict:
    year = year or timezone.localdate().year
    runs = PayrollRun.objects.filter(year=year).exclude(
        status=PayrollRunStatus.CANCELLED
    )
    totals = runs.aggregate(
        gross=Sum("total_gross"),
        net=Sum("total_net"),
        tax=Sum("total_tax"),
        pf=Sum("total_pf_employee"),
    )

    def _v(value):
        return value or Decimal("0")

    return {
        "year": year,
        "runs": runs.count(),
        "gross": _v(totals["gross"]),
        "net": _v(totals["net"]),
        "tax": _v(totals["tax"]),
        "pf_employee": _v(totals["pf"]),
        "active_staff": Staff.objects.filter(is_active=True).count(),
        "last_run": runs.order_by("-year", "-month", "-id").first(),
        "pending_adjustments": SalaryAdjustment.objects.filter(
            Q(status="pending")
        ).count(),
    }


def register_rows(run):
    """Flat rows used by the payroll register report / export."""
    rows = []
    for slip in run_payslips(run):
        rows.append(
            [
                slip.employee_code,
                slip.name,
                slip.designation,
                slip.structure_gross,
                slip.adjustment_earning,
                slip.absence_deduction,
                slip.late_deduction,
                slip.unpaid_leave_deduction,
                slip.pf_employee,
                slip.tax,
                slip.adjustment_deduction,
                slip.gross_salary,
                slip.total_deductions,
                slip.net_pay,
            ]
        )
    return rows


REGISTER_HEADERS = [
    "Employee code",
    "Name",
    "Designation",
    "Structure gross",
    "Adjustments (+)",
    "Absence",
    "Late",
    "Unpaid leave",
    "PF (employee)",
    "Income tax",
    "Adjustments (−)",
    "Gross earnings",
    "Total deductions",
    "Net pay",
]
