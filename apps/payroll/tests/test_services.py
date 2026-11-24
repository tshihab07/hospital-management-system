"""Service-level tests for the Payroll module (RULES Phase 14)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.accounting import services as accounting
from apps.accounting.models import JournalStatus, SystemAccount
from apps.hr.models import AttendanceStatus, LeaveRequest, LeaveStatus, LeaveType

from .. import services
from ..models import (
    AdjustmentKind,
    AdjustmentStatus,
    PayrollRunStatus,
    Payslip,
    PayslipStatus,
    SalaryAdjustment,
)
from . import factories

pytestmark = pytest.mark.django_db


@pytest.fixture
def chart():
    return accounting.seed_chart_of_accounts()


@pytest.fixture
def settings_obj():
    factories.seed_payroll()
    return services.get_settings()


def test_seed_payroll_is_idempotent():
    first = factories.seed_payroll()
    assert first["created"] == 4
    second = factories.seed_payroll()
    assert second["created"] == 0
    assert second["existing"] == 4


def test_generate_run_creates_payslips_for_active_staff(settings_obj):
    staff = factories.make_staff("EMP-001")
    run = services.generate_run(year=2026, month=1)
    assert run.status == PayrollRunStatus.DRAFT
    assert run.employee_count == 1
    slip = Payslip.objects.get(run=run, staff=staff)
    assert slip.employee_code == "EMP-001"
    assert slip.net_pay == slip.gross_salary - slip.total_deductions
    assert slip.net_pay > 0


def test_generate_run_uses_gross_and_computes_pf(settings_obj):
    staff = factories.make_staff("EMP-002", basic_salary="30000.00")
    run = services.generate_run(year=2026, month=2)
    slip = Payslip.objects.get(run=run, staff=staff)
    assert slip.structure_gross == Decimal("48000.00")
    # PF is 10% of basic by default.
    assert slip.pf_employee == Decimal("3000.00")
    assert slip.pf_employer == Decimal("3000.00")


def test_absence_reduces_net(settings_obj):
    staff = factories.make_staff("EMP-003")
    factories.add_attendance(staff, AttendanceStatus.ABSENT, date(2026, 3, 5))
    run = services.generate_run(year=2026, month=3)
    slip = Payslip.objects.get(run=run, staff=staff)
    assert slip.absent_days == Decimal("1")
    assert slip.absence_deduction > 0
    assert slip.net_pay < slip.gross_salary


def test_unpaid_leave_deducted(settings_obj):
    staff = factories.make_staff("EMP-004")
    leave_type = LeaveType.objects.create(name="Unpaid", code="UPL", is_paid=False)
    LeaveRequest.objects.create(
        staff=staff,
        leave_type=leave_type,
        start_date=date(2026, 4, 6),
        end_date=date(2026, 4, 7),
        status=LeaveStatus.APPROVED,
    )
    run = services.generate_run(year=2026, month=4)
    slip = Payslip.objects.get(run=run, staff=staff)
    assert slip.unpaid_leave_days == Decimal("2")
    assert slip.unpaid_leave_deduction > 0


def test_approve_locks_and_posts_accrual(settings_obj, chart):
    factories.make_staff("EMP-010")
    run = services.generate_run(year=2026, month=5)
    services.approve_run(run)
    run.refresh_from_db()
    assert run.status == PayrollRunStatus.APPROVED
    assert run.is_locked is True
    assert run.journal is not None
    assert run.journal.status == JournalStatus.POSTED
    assert run.payslips.first().status == PayslipStatus.APPROVED


def test_approve_empty_run_raises(settings_obj):
    run = services.generate_run(year=2026, month=6)
    Payslip.objects.filter(run=run).delete()
    with pytest.raises(ValueError):
        services.approve_run(run)


def test_accrual_journal_is_balanced(settings_obj, chart):
    factories.make_staff("EMP-011")
    run = services.generate_run(year=2026, month=7)
    services.approve_run(run)
    entry = run.journal
    assert entry.total_debit == entry.total_credit
    # Net salaries payable credited.
    payable = accounting.get_system_account(SystemAccount.SALARY_PAYABLE)
    credited = sum(
        Decimal(str(line.credit)) for line in entry.lines.filter(account=payable)
    )
    assert credited == run.total_net


def test_pay_posts_payment_journal(settings_obj, chart):
    factories.make_staff("EMP-012")
    run = services.generate_run(year=2026, month=8, payment_method="bank")
    services.approve_run(run)
    services.mark_run_paid(run)
    run.refresh_from_db()
    assert run.status == PayrollRunStatus.PAID
    assert run.payment_journal is not None
    bank = accounting.get_system_account(SystemAccount.BANK)
    credited = sum(
        Decimal(str(line.credit))
        for line in run.payment_journal.lines.filter(account=bank)
    )
    assert credited == run.total_net


def test_cannot_approve_twice(settings_obj, chart):
    factories.make_staff("EMP-013")
    run = services.generate_run(year=2026, month=9)
    services.approve_run(run)
    with pytest.raises(ValueError):
        services.approve_run(run)


def test_cannot_pay_draft(settings_obj, chart):
    factories.make_staff("EMP-014")
    run = services.generate_run(year=2026, month=10)
    with pytest.raises(ValueError):
        services.mark_run_paid(run)


def test_cancel_draft_run(settings_obj):
    factories.make_staff("EMP-015")
    run = services.generate_run(year=2026, month=11)
    services.cancel_run(run)
    run.refresh_from_db()
    assert run.status == PayrollRunStatus.CANCELLED


def test_locked_run_cannot_be_regenerated(settings_obj, chart):
    factories.make_staff("EMP-016")
    run = services.generate_run(year=2026, month=12)
    services.approve_run(run)
    with pytest.raises(ValueError):
        services.generate_run(year=2026, month=12)


def test_pending_adjustment_flows_into_run(settings_obj):
    staff = factories.make_staff("EMP-020")
    services.create_adjustment(
        staff=staff,
        year=2026,
        month=1,
        kind=AdjustmentKind.EARNING,
        amount="5000.00",
        reason="Arrears",
    )
    run = services.generate_run(year=2026, month=1)
    slip = Payslip.objects.get(run=run, staff=staff)
    assert slip.adjustment_earning == Decimal("5000.00")
    adjustment = SalaryAdjustment.objects.get(staff=staff)
    assert adjustment.status == AdjustmentStatus.APPLIED
    assert adjustment.run_id == run.pk


def test_deduction_adjustment_reduces_net(settings_obj):
    staff = factories.make_staff("EMP-021")
    base_run = services.generate_run(year=2026, month=5)
    base_net = Payslip.objects.get(run=base_run, staff=staff).net_pay

    services.create_adjustment(
        staff=staff,
        year=2026,
        month=6,
        kind=AdjustmentKind.DEDUCTION,
        amount="1000.00",
        reason="Recovery",
    )
    run = services.generate_run(year=2026, month=6)
    slip = Payslip.objects.get(run=run, staff=staff)
    assert slip.adjustment_deduction == Decimal("1000.00")
    assert slip.net_pay == base_net - Decimal("1000.00")


def test_create_adjustment_rejects_non_positive():
    staff = factories.make_staff("EMP-022")
    with pytest.raises(ValueError):
        services.create_adjustment(
            staff=staff,
            year=2026,
            month=1,
            kind=AdjustmentKind.EARNING,
            amount=0,
            reason="x",
        )


def test_post_adjustment_against_locked_run(settings_obj, chart):
    staff = factories.make_staff("EMP-023")
    run = services.generate_run(year=2026, month=2)
    services.approve_run(run)
    adjustment = SalaryAdjustment.objects.create(
        staff=staff,
        year=2026,
        month=2,
        kind=AdjustmentKind.EARNING,
        amount=Decimal("2000.00"),
        reason="Post-run bonus",
        run=run,
    )
    services.post_adjustment(adjustment)
    adjustment.refresh_from_db()
    assert adjustment.status == AdjustmentStatus.POSTED
    assert adjustment.journal is not None


def test_regeneration_keeps_adjustments(settings_obj):
    """Regenerating a draft run must not orphan previously-applied adjustments."""
    staff = factories.make_staff("EMP-026")
    services.create_adjustment(
        staff=staff,
        year=2026,
        month=3,
        kind=AdjustmentKind.EARNING,
        amount="1500.00",
        reason="Arrears",
    )
    run = services.generate_run(year=2026, month=3)
    assert Payslip.objects.get(run=run, staff=staff).adjustment_earning == Decimal(
        "1500.00"
    )
    # Regenerate the same draft run.
    run = services.generate_run(year=2026, month=3)
    slip = Payslip.objects.get(run=run, staff=staff)
    assert slip.adjustment_earning == Decimal("1500.00")
    adjustment = SalaryAdjustment.objects.get(staff=staff)
    assert adjustment.status == AdjustmentStatus.APPLIED
    assert adjustment.payslip_id == slip.pk


def test_post_run_adjustment_finds_locked_run(settings_obj, chart):
    """A pending adjustment for an already-locked month can be posted directly."""
    staff = factories.make_staff("EMP-027")
    run = services.generate_run(year=2026, month=4)
    services.approve_run(run)
    adjustment = services.create_adjustment(
        staff=staff,
        year=2026,
        month=4,
        kind=AdjustmentKind.EARNING,
        amount="3000.00",
        reason="Late bonus",
    )
    services.post_adjustment(adjustment)
    adjustment.refresh_from_db()
    assert adjustment.status == AdjustmentStatus.POSTED
    assert adjustment.run_id == run.pk
    assert adjustment.journal is not None


def test_applied_adjustment_cannot_be_posted(settings_obj, chart):
    """An adjustment already folded into a run must not be double-posted."""
    staff = factories.make_staff("EMP-028")
    services.create_adjustment(
        staff=staff,
        year=2026,
        month=5,
        kind=AdjustmentKind.EARNING,
        amount="1000.00",
        reason="x",
    )
    run = services.generate_run(year=2026, month=5)
    services.approve_run(run)
    adjustment = SalaryAdjustment.objects.get(staff=staff)
    assert adjustment.status == AdjustmentStatus.APPLIED
    with pytest.raises(ValueError):
        services.post_adjustment(adjustment)


def test_beftn_validation_flags_missing_bank_details(settings_obj):
    from .. import exports

    factories.make_staff(
        "EMP-029",
        salary_payment_mode="bank",
        bank_account_no="1234567890",
        bank_routing_no="090261234",
    )
    factories.make_staff("EMP-030", salary_payment_mode="bank")
    run = services.generate_run(year=2026, month=6, payment_method="bank")
    result = exports.validate_beftn(run)
    codes = {row[0] for row in result["issues"]}
    assert "EMP-030" in codes
    assert "EMP-029" not in codes
    assert result["valid"] == 1


def test_cancel_pending_adjustment(settings_obj):
    staff = factories.make_staff("EMP-024")
    adjustment = services.create_adjustment(
        staff=staff,
        year=2026,
        month=1,
        kind=AdjustmentKind.EARNING,
        amount=1000,
        reason="x",
    )
    services.cancel_adjustment(adjustment)
    adjustment.refresh_from_db()
    assert adjustment.status == AdjustmentStatus.CANCELLED


def test_attendance_summary_counts_statuses(settings_obj):
    staff = factories.make_staff("EMP-025")
    for day in (1, 2):
        factories.add_attendance(staff, AttendanceStatus.PRESENT, date(2026, 1, day))
    factories.add_attendance(staff, AttendanceStatus.LATE, date(2026, 1, 4))
    factories.add_attendance(staff, AttendanceStatus.ABSENT, date(2026, 1, 6))
    summary = services.attendance_summary(staff, date(2026, 1, 1), date(2026, 1, 31))
    assert summary["present"] == Decimal("3")
    assert summary["absent"] == Decimal("1")
    assert summary["late"] == Decimal("1")


def test_tax_never_makes_net_negative(settings_obj):
    factories.make_staff(
        "EMP-030",
        basic_salary="5000",
        house_rent="0",
        medical_allowance="0",
        transport_allowance="0",
        other_allowance="0",
    )
    run = services.generate_run(year=2026, month=1)
    slip = run.payslips.first()
    assert slip.net_pay >= 0
    assert slip.tax >= 0
