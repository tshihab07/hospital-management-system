"""Write operations for the Payroll module (atomic + audited).

The lifecycle is: **generate** a draft run for a month → **approve** (locks the
run and posts the accrual journal to the general ledger) → **pay** (posts the
disbursement journal; BEFTN/cash). Corrections before approval flow through
pending :class:`SalaryAdjustment` rows picked up on the next generation;
corrections after approval post a standalone adjustment journal.
"""

from __future__ import annotations

import calendar
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting import integration as accounting
from apps.hr.models import (
    Attendance,
    AttendanceStatus,
    LeaveRequest,
    LeaveStatus,
    Staff,
    StaffStatus,
)
from core.audit import AuditAction, log_action, model_to_dict_safe

from . import selectors, tax
from .models import (
    AdjustmentKind,
    AdjustmentStatus,
    PayrollRun,
    PayrollRunStatus,
    PayrollSetting,
    Payslip,
    PayslipStatus,
    SalaryAdjustment,
    WageBasis,
    _dec,
)

PAYABLE_STAFF_STATUSES = {StaffStatus.ACTIVE, StaffStatus.ON_LEAVE}
ZERO = Decimal("0.00")


def _money(value) -> Decimal:
    return _dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_settings() -> PayrollSetting:
    return PayrollSetting.load()


def period_bounds(year: int, month: int) -> tuple:
    """Return the ``(first_day, last_day)`` of a payroll month."""
    if not 1 <= int(month) <= 12:
        raise ValueError(_("Month must be between 1 and 12."))
    last_day = calendar.monthrange(int(year), int(month))[1]
    from datetime import date

    return date(int(year), int(month), 1), date(int(year), int(month), last_day)


def run_code(year: int, month: int) -> str:
    return f"RUN-{int(year):04d}-{int(month):02d}"


# ---------------------------------------------------------------------------
# Attendance summary
# ---------------------------------------------------------------------------
def attendance_summary(staff: Staff, start, end) -> dict:
    """Count attendance plus approved unpaid-leave days within a period."""
    qs = Attendance.objects.filter(staff=staff, att_date__range=(start, end))
    counts = {
        row["status"]: row["n"] for row in qs.values("status").annotate(n=Count("id"))
    }
    present = counts.get(AttendanceStatus.PRESENT, 0) + counts.get(
        AttendanceStatus.LATE, 0
    )
    absent = counts.get(AttendanceStatus.ABSENT, 0)
    late = counts.get(AttendanceStatus.LATE, 0)
    half = counts.get(AttendanceStatus.HALF_DAY, 0)
    leave_marks = counts.get(AttendanceStatus.LEAVE, 0)

    unpaid_leave = 0
    for request in LeaveRequest.objects.filter(
        staff=staff,
        status=LeaveStatus.APPROVED,
        leave_type__is_paid=False,
        start_date__lte=end,
        end_date__gte=start,
    ):
        overlap_start = max(start, request.start_date)
        overlap_end = min(end, request.end_date)
        if overlap_end >= overlap_start:
            unpaid_leave += (overlap_end - overlap_start).days + 1
    paid_leave = max(0, leave_marks - unpaid_leave)
    return {
        "present": Decimal(present),
        "absent": Decimal(absent),
        "late": Decimal(late),
        "half": Decimal(half),
        "unpaid_leave": Decimal(unpaid_leave),
        "paid_leave": Decimal(paid_leave),
    }


# ---------------------------------------------------------------------------
# Payslip computation
# ---------------------------------------------------------------------------
def _pf_basis(
    staff: Staff, settings: PayrollSetting, structure_gross: Decimal
) -> Decimal:
    if settings.pf_wage_basis == WageBasis.BASIC:
        return _dec(staff.basic_salary)
    return structure_gross


def _daily_rate(
    staff: Staff, settings: PayrollSetting, structure_gross: Decimal
) -> Decimal:
    days = int(settings.working_days_per_month or 30) or 30
    basis = (
        _dec(staff.basic_salary)
        if settings.absence_wage_basis == WageBasis.BASIC
        else structure_gross
    )
    return basis / Decimal(days)


def _brackets_for(slab) -> list[tuple]:
    if slab is None:
        return [(band, rate) for band, rate, _label in tax.BD_SLABS["general"]]
    return [(b.band_amount, b.rate) for b in slab.brackets.all()]


def compute_payslip(
    run: PayrollRun,
    staff: Staff,
    settings: PayrollSetting,
    adjustments: list[SalaryAdjustment] | None = None,
) -> Payslip:
    """Build (unsaved) :class:`Payslip` for one employee for the run's month."""
    adjustments = adjustments or []
    start, end = run.period_start, run.period_end
    summary = attendance_summary(staff, start, end)

    structure_gross = _dec(staff.gross_salary)
    daily_rate = _daily_rate(staff, settings, structure_gross)

    absent = summary["absent"]
    half = summary["half"]
    unpaid = summary["unpaid_leave"]
    late = summary["late"]
    half_factor = _dec(settings.half_day_factor)

    absence_deduction = _money((absent + half * half_factor) * daily_rate)
    unpaid_deduction = _money(unpaid * daily_rate)
    late_units = Decimal("0")
    if settings.late_marks_per_absence:
        late_units = (
            late / Decimal(settings.late_marks_per_absence)
        ).to_integral_value(rounding="ROUND_FLOOR")
    late_deduction = _money(late_units * daily_rate)

    adj_earning = sum(
        (_dec(a.amount) for a in adjustments if a.kind == AdjustmentKind.EARNING), ZERO
    )
    adj_deduction = sum(
        (_dec(a.amount) for a in adjustments if a.kind == AdjustmentKind.DEDUCTION),
        ZERO,
    )

    # Total earnings (structure + extra earning adjustments).
    gross_salary = _money(structure_gross + adj_earning)

    # Provident fund.
    pf_basis = _pf_basis(staff, settings, structure_gross)
    if staff.pf_eligible:
        pf_employee = _money(
            pf_basis * _dec(settings.provident_fund_rate) / Decimal(100)
        )
        pf_employer = _money(pf_basis * _dec(settings.employer_pf_rate) / Decimal(100))
    else:
        pf_employee = ZERO
        pf_employer = ZERO

    # Income tax on annualised taxable income.
    slab = selectors.active_tax_slab(staff.tax_category)
    months = int(settings.annual_months or 12) or 12
    annual_gross = gross_salary * months
    annual_pf = pf_employee * months
    std_deduction = tax.standard_deduction(
        annual_gross,
        ratio=settings.standard_deduction_ratio,
        cap=settings.standard_deduction_cap,
    )
    taxable = tax.taxable_income(
        annual_gross, annual_pf=annual_pf, standard_deduction=std_deduction
    )
    if slab is not None:
        threshold = slab.tax_free_threshold
        minimum_tax = slab.minimum_tax or settings.minimum_tax
    else:
        threshold = tax.BD_CATEGORY.get(staff.tax_category, {}).get(
            "threshold", Decimal("350000")
        )
        minimum_tax = settings.minimum_tax
    annual_tax = tax.compute_tax(
        taxable,
        _brackets_for(slab),
        tax_free_threshold=threshold,
        minimum_tax=minimum_tax,
    )
    monthly_tax = tax.monthly_tax(annual_tax, months)

    # Never let deductions exceed earnings.
    attendance_ded = absence_deduction + late_deduction + unpaid_deduction
    headroom = gross_salary - attendance_ded - adj_deduction - pf_employee
    if headroom < 0:
        headroom = ZERO
    if monthly_tax > headroom:
        monthly_tax = _money(headroom)

    total_deductions = _money(
        attendance_ded + pf_employee + monthly_tax + adj_deduction
    )
    net_pay = _money(gross_salary - total_deductions)

    return Payslip(
        run=run,
        staff=staff,
        status=PayslipStatus.DRAFT,
        employee_code=staff.employee_code,
        name=staff.display_name,
        department=str(staff.department) if staff.department_id else "",
        designation=str(staff.designation) if staff.designation_id else "",
        tax_category=staff.tax_category,
        basic=_dec(staff.basic_salary),
        house_rent=_dec(staff.house_rent),
        medical_allowance=_dec(staff.medical_allowance),
        transport_allowance=_dec(staff.transport_allowance),
        other_allowance=_dec(staff.other_allowance),
        structure_gross=_money(structure_gross),
        working_days=int(settings.working_days_per_month or 30),
        present_days=summary["present"],
        absent_days=summary["absent"],
        late_days=summary["late"],
        half_days=summary["half"],
        unpaid_leave_days=summary["unpaid_leave"],
        paid_leave_days=summary["paid_leave"],
        adjustment_earning=_money(adj_earning),
        adjustment_deduction=_money(adj_deduction),
        absence_deduction=absence_deduction,
        late_deduction=late_deduction,
        unpaid_leave_deduction=unpaid_deduction,
        pf_employee=pf_employee,
        pf_employer=pf_employer,
        tax=monthly_tax,
        gross_salary=gross_salary,
        total_deductions=total_deductions,
        net_pay=net_pay,
        payment_method=staff.salary_payment_mode,
        bank_name=staff.bank_name,
        bank_account_no=staff.bank_account_no,
        bank_routing_no=staff.bank_routing_no
        or getattr(settings, "bank_routing_default", ""),
    )


def _pending_adjustments(year: int, month: int) -> dict[int, list[SalaryAdjustment]]:
    grouped: dict[int, list[SalaryAdjustment]] = {}
    qs = SalaryAdjustment.objects.filter(
        year=year, month=month, status=AdjustmentStatus.PENDING
    )
    for adjustment in qs:
        grouped.setdefault(adjustment.staff_id, []).append(adjustment)
    return grouped


def _recompute_totals(run: PayrollRun) -> PayrollRun:
    slips = run.payslips.all()
    totals = {
        "total_gross": ZERO,
        "total_deductions": ZERO,
        "total_tax": ZERO,
        "total_pf_employee": ZERO,
        "total_pf_employer": ZERO,
        "total_net": ZERO,
    }
    count = 0
    for slip in slips:
        count += 1
        totals["total_gross"] += _dec(slip.gross_salary)
        totals["total_deductions"] += _dec(slip.total_deductions)
        totals["total_tax"] += _dec(slip.tax)
        totals["total_pf_employee"] += _dec(slip.pf_employee)
        totals["total_pf_employer"] += _dec(slip.pf_employer)
        totals["total_net"] += _dec(slip.net_pay)
    run.employee_count = count
    for key, value in totals.items():
        setattr(run, key, _money(value))
    run.save(
        update_fields=[
            "employee_count",
            *totals.keys(),
            "updated_at",
        ]
    )
    return run


@transaction.atomic
def generate_run(
    *,
    year: int,
    month: int,
    payment_date=None,
    payment_method: str = "bank",
    staff_qs=None,
    notes: str = "",
    actor=None,
    request=None,
) -> PayrollRun:
    """Create (or regenerate) a draft payroll run for a month."""
    start, end = period_bounds(year, month)
    settings = get_settings()
    run, created = PayrollRun.objects.select_for_update().get_or_create(
        year=year,
        month=month,
        defaults={
            "code": run_code(year, month),
            "period_start": start,
            "period_end": end,
            "payment_method": payment_method,
            "payment_date": payment_date,
            "notes": notes or "",
            "created_by": actor if getattr(actor, "pk", None) else None,
        },
    )
    if not created and not run.is_editable:
        raise ValueError(_("This payroll run is already approved and locked."))
    run.period_start = start
    run.period_end = end
    run.payment_method = payment_method
    run.payment_date = payment_date
    if notes:
        run.notes = notes
    run.working_days = int(settings.working_days_per_month or 30)
    run.save(
        update_fields=[
            "period_start",
            "period_end",
            "payment_method",
            "payment_date",
            "working_days",
            "notes",
            "updated_at",
        ]
    )

    # Regeneration starts clean.
    run.payslips.all().delete()
    # Reset adjustments previously linked to this run back to pending
    run.adjustments.all().update(
        status=AdjustmentStatus.PENDING,
        run=None,
        payslip=None,
        applied_at=None,
        updated_at=timezone.now(),
    )

    if staff_qs is None:
        staff_qs = Staff.objects.filter(
            is_active=True, status__in=PAYABLE_STAFF_STATUSES
        )
    staff_qs = staff_qs.select_related("department", "designation").order_by(
        "employee_code"
    )

    pending = _pending_adjustments(year, month)
    applied: list[SalaryAdjustment] = []
    for staff in staff_qs:
        rows = pending.get(staff.pk, [])
        slip = compute_payslip(run, staff, settings, rows)
        slip.save()
        for adjustment in rows:
            adjustment.status = AdjustmentStatus.APPLIED
            adjustment.run = run
            adjustment.payslip = slip
            adjustment.applied_at = timezone.now()
            adjustment.save(
                update_fields=["status", "run", "payslip", "applied_at", "updated_at"]
            )
            applied.append(adjustment)

    _recompute_totals(run)
    log_action(
        AuditAction.CREATE if created else AuditAction.UPDATE,
        instance=run,
        changes={
            "employees": run.employee_count,
            "total_net": str(run.total_net),
            "adjustments_applied": len(applied),
        },
        user=actor,
        request=request,
    )
    return run


@transaction.atomic
def approve_run(run: PayrollRun, *, actor=None, request=None) -> PayrollRun:
    """Approve and lock a draft run; post the accrual journal."""
    if run.status != PayrollRunStatus.DRAFT:
        raise ValueError(_("Only draft payroll runs can be approved."))
    if not run.payslips.exists():
        raise ValueError(_("Cannot approve an empty payroll run."))

    run.status = PayrollRunStatus.APPROVED
    run.is_locked = True
    run.approved_by = actor if getattr(actor, "pk", None) else None
    run.approved_at = timezone.now()
    run.save(
        update_fields=[
            "status",
            "is_locked",
            "approved_by",
            "approved_at",
            "updated_at",
        ]
    )
    run.payslips.update(status=PayslipStatus.APPROVED)
    accounting.on_payroll_approved(run, actor=actor, request=request)
    log_action(
        AuditAction.APPROVE,
        instance=run,
        changes={"status": PayrollRunStatus.APPROVED, "net": str(run.total_net)},
        user=actor,
        request=request,
    )
    return run


@transaction.atomic
def mark_run_paid(
    run: PayrollRun, *, payment_date=None, actor=None, request=None
) -> PayrollRun:
    """Mark an approved run as disbursed; post the payment journal."""
    if run.status != PayrollRunStatus.APPROVED:
        raise ValueError(_("Only approved payroll runs can be paid."))
    run.status = PayrollRunStatus.PAID
    run.paid_by = actor if getattr(actor, "pk", None) else None
    run.paid_at = timezone.now()
    if payment_date:
        run.payment_date = payment_date
    run.save(
        update_fields=["status", "paid_by", "paid_at", "payment_date", "updated_at"]
    )
    run.payslips.update(status=PayslipStatus.PAID)
    accounting.on_payroll_paid(run, actor=actor, request=request)
    log_action(
        AuditAction.PAYMENT,
        instance=run,
        changes={"status": PayrollRunStatus.PAID, "net": str(run.total_net)},
        user=actor,
        request=request,
    )
    return run


@transaction.atomic
def cancel_run(run: PayrollRun, *, actor=None, request=None) -> PayrollRun:
    """Cancel a draft run; approved runs must be corrected, never deleted."""
    if run.status != PayrollRunStatus.DRAFT:
        raise ValueError(_("Only draft payroll runs can be cancelled."))
    run.status = PayrollRunStatus.CANCELLED
    run.is_locked = True
    run.save(update_fields=["status", "is_locked", "updated_at"])
    run.payslips.update(status=PayslipStatus.DRAFT)
    log_action(
        AuditAction.UPDATE,
        instance=run,
        changes={"status": PayrollRunStatus.CANCELLED},
        user=actor,
        request=request,
    )
    return run


# ---------------------------------------------------------------------------
# Salary adjustments
# ---------------------------------------------------------------------------
@transaction.atomic
def create_adjustment(
    *,
    staff: Staff,
    year: int,
    month: int,
    kind: str,
    amount,
    reason: str,
    actor=None,
    request=None,
) -> SalaryAdjustment:
    """Record a pending salary correction for a future payroll run."""
    value = _money(amount)
    if value <= 0:
        raise ValueError(_("Adjustment amount must be greater than zero."))
    adjustment = SalaryAdjustment.objects.create(
        staff=staff,
        year=year,
        month=month,
        kind=kind,
        amount=value,
        reason=reason,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    log_action(
        AuditAction.CREATE,
        instance=adjustment,
        changes=model_to_dict_safe(adjustment),
        user=actor,
        request=request,
    )
    return adjustment


@transaction.atomic
def post_adjustment(
    adjustment: SalaryAdjustment, *, actor=None, request=None
) -> SalaryAdjustment:
    """Post a correction against an already-approved run as its own journal."""
    if adjustment.status == AdjustmentStatus.POSTED:
        return adjustment
    if adjustment.status == AdjustmentStatus.CANCELLED:
        raise ValueError(_("A cancelled adjustment cannot be posted."))
    if adjustment.status != AdjustmentStatus.PENDING:
        raise ValueError(
            _("This adjustment is already applied to a payroll run.")
        )
    run = adjustment.run
    if run is None:
        from .models import PayrollRunStatus

        run = PayrollRun.objects.filter(
            year=adjustment.year,
            month=adjustment.month,
            status=PayrollRunStatus.APPROVED,
        ).first()
        if run:
            adjustment.run = run
    if run is None or not run.is_locked:
        raise ValueError(
            _("This adjustment is picked up automatically by the next payroll run.")
        )
    adjustment.applied_at = adjustment.applied_at or timezone.now()
    accounting.on_salary_adjustment(adjustment, actor=actor, request=request)
    adjustment.status = AdjustmentStatus.POSTED
    adjustment.save(
        update_fields=["status", "run", "applied_at", "journal", "updated_at"]
    )
    log_action(
        AuditAction.APPROVE,
        instance=adjustment,
        changes={"status": AdjustmentStatus.POSTED},
        user=actor,
        request=request,
    )
    return adjustment


@transaction.atomic
def cancel_adjustment(
    adjustment: SalaryAdjustment, *, actor=None, request=None
) -> SalaryAdjustment:
    if adjustment.status != AdjustmentStatus.PENDING:
        raise ValueError(_("Only pending adjustments can be cancelled."))
    adjustment.status = AdjustmentStatus.CANCELLED
    adjustment.save(update_fields=["status", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=adjustment,
        changes={"status": AdjustmentStatus.CANCELLED},
        user=actor,
        request=request,
    )
    return adjustment
