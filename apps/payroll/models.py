"""Payroll domain models (RULES Phase 14).

Monthly salary processing with Bangladesh income-tax rules. Three layers:

* **Configuration** — :class:`PayrollSetting` (PF %, absence/late policy,
  standard deduction, BEFTN header) and the configurable income-tax grid
  (:class:`TaxSlab` + :class:`TaxBracket`) seeded with current NBR values.
* **Transactions** — :class:`PayrollRun` (one month, locked on approval) and
  the per-employee :class:`Payslip`, which snapshots the salary structure,
  attendance and every earning / deduction so history never drifts.
* **Corrections** — :class:`SalaryAdjustment` for pre-run and post-run
  corrections; post-run corrections post a supplemental GL journal.

Money is always ``DecimalField(14, 2)``. Approved runs and their payslips are
immutable; corrections are additive.
"""

from __future__ import annotations

import calendar
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.hr.models import Staff, TaxCategory
from core.models import SoftDeleteModel, TimeStampedModel

PAYROLL_IDENT = "payroll"


def _dec(value) -> Decimal:
    """Coerce a value to ``Decimal`` (SQLite returns ``str`` for decimals)."""
    return Decimal(str(value or "0"))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class WageBasis(models.TextChoices):
    BASIC = "basic", _("Basic salary")
    GROSS = "gross", _("Gross salary")


class PaymentMethod(models.TextChoices):
    CASH = "cash", _("Cash")
    BANK = "bank", _("Bank transfer (BEFTN)")


class PayrollRunStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    APPROVED = "approved", _("Approved")
    PAID = "paid", _("Paid")
    CANCELLED = "cancelled", _("Cancelled")


class PayslipStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    APPROVED = "approved", _("Approved")
    PAID = "paid", _("Paid")


class AdjustmentKind(models.TextChoices):
    EARNING = "earning", _("Earning")
    DEDUCTION = "deduction", _("Deduction")


class AdjustmentStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    APPLIED = "applied", _("Applied to payslip")
    POSTED = "posted", _("Posted as adjustment journal")
    CANCELLED = "cancelled", _("Cancelled")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class PayrollSetting(TimeStampedModel):
    """Singleton payroll policy: PF, attendance deduction and BEFTN details."""

    provident_fund_rate = models.DecimalField(
        _("employee PF rate (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        help_text=_("Employee's monthly provident-fund contribution as a %."),
    )
    employer_pf_rate = models.DecimalField(
        _("employer PF rate (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        help_text=_("Employer's matching provident-fund contribution as a %."),
    )
    pf_wage_basis = models.CharField(
        _("PF wage basis"),
        max_length=8,
        choices=WageBasis.choices,
        default=WageBasis.BASIC,
    )
    working_days_per_month = models.PositiveSmallIntegerField(
        _("working days per month"),
        default=30,
        help_text=_("Divisor used to derive the daily wage for deductions."),
    )
    absence_wage_basis = models.CharField(
        _("absence wage basis"),
        max_length=8,
        choices=WageBasis.choices,
        default=WageBasis.GROSS,
    )
    late_marks_per_absence = models.PositiveSmallIntegerField(
        _("late marks per absence"),
        default=3,
        help_text=_("Number of late marks that equal one day's deduction."),
    )
    half_day_factor = models.DecimalField(
        _("half-day factor"),
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.50"),
    )
    standard_deduction_ratio = models.DecimalField(
        _("standard deduction ratio"),
        max_digits=6,
        decimal_places=4,
        default=Decimal("0.3333"),
        help_text=_("Fraction of gross salary exempt as standard deduction."),
    )
    standard_deduction_cap = models.DecimalField(
        _("standard deduction cap"),
        max_digits=14,
        decimal_places=2,
        default=Decimal("300000.00"),
    )
    annual_months = models.PositiveSmallIntegerField(
        _("months per tax year"), default=12
    )
    minimum_tax = models.DecimalField(
        _("fallback minimum tax"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("5000.00"),
        help_text=_("Used when the active tax slab does not specify a minimum."),
    )
    house_rent_exemption_enabled = models.BooleanField(
        _("house-rent exemption"), default=False
    )
    bank_routing_default = models.CharField(
        _("default bank routing no."), max_length=20, blank=True
    )
    beftn_company_name = models.CharField(
        _("BEFTN originating company"), max_length=120, blank=True
    )
    beftn_company_account = models.CharField(
        _("BEFTN debit account"), max_length=40, blank=True
    )
    beftn_bank_code = models.CharField(_("BEFTN bank code"), max_length=20, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_settings_updated",
        verbose_name=_("updated by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("payroll setting")
        verbose_name_plural = _("payroll settings")

    def __str__(self) -> str:
        return _("Payroll settings")

    @classmethod
    def load(cls) -> "PayrollSetting":
        """Return the singleton settings row, creating a default if none exists."""
        obj = cls.objects.order_by("pk").first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class TaxSlab(TimeStampedModel):
    """Income-tax grid for one assessment year and taxpayer category."""

    assessment_year = models.CharField(
        _("assessment year"),
        max_length=12,
        help_text=_("e.g. 2025-2026 (AY) / income year 2024-2025."),
    )
    category = models.CharField(
        _("taxpayer category"),
        max_length=20,
        choices=TaxCategory.choices,
        default=TaxCategory.GENERAL,
    )
    tax_free_threshold = models.DecimalField(
        _("tax-free threshold"), max_digits=14, decimal_places=2, default=0
    )
    minimum_tax = models.DecimalField(
        _("minimum tax"), max_digits=12, decimal_places=2, default=0
    )
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    source = models.CharField(
        _("source"), max_length=160, blank=True, help_text=_("NBR circular / Act ref.")
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("tax slab")
        verbose_name_plural = _("tax slabs")
        ordering = ["-assessment_year", "category"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment_year", "category"], name="uniq_taxslab_year_cat"
            )
        ]

    def __str__(self) -> str:
        return f"{self.assessment_year} · {self.get_category_display()}"

    @property
    def label(self) -> str:
        return f"{self.assessment_year} · {self.get_category_display()}"


class TaxBracket(TimeStampedModel):
    """One progressive band of a :class:`TaxSlab`.

    ``band_amount`` is the width of the band (``None`` for the topmost,
    open-ended band). Bands are applied cumulatively from zero income.
    """

    slab = models.ForeignKey(
        TaxSlab,
        on_delete=models.CASCADE,
        related_name="brackets",
        verbose_name=_("tax slab"),
    )
    order = models.PositiveSmallIntegerField(_("order"), default=0)
    band_amount = models.DecimalField(
        _("band width"),
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Leave blank for the topmost, open-ended band."),
    )
    rate = models.DecimalField(_("rate (%)"), max_digits=5, decimal_places=2, default=0)
    label = models.CharField(_("label"), max_length=80, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("tax bracket")
        verbose_name_plural = _("tax brackets")
        ordering = ["slab", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["slab", "order"], name="uniq_taxbracket_slab_order"
            )
        ]

    def __str__(self) -> str:
        width = "∞" if self.band_amount is None else self.band_amount
        return f"{width} @ {self.rate}%"


# ---------------------------------------------------------------------------
# Payroll runs
# ---------------------------------------------------------------------------
class PayrollRun(SoftDeleteModel):
    """One monthly payroll batch, locked once approved."""

    code = models.CharField(_("code"), max_length=30, unique=True)
    year = models.PositiveSmallIntegerField(_("year"), db_index=True)
    month = models.PositiveSmallIntegerField(_("month"), db_index=True)
    period_start = models.DateField(_("period start"))
    period_end = models.DateField(_("period end"))
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=PayrollRunStatus.choices,
        default=PayrollRunStatus.DRAFT,
        db_index=True,
    )
    payment_date = models.DateField(_("payment date"), null=True, blank=True)
    payment_method = models.CharField(
        _("payment method"),
        max_length=8,
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK,
    )
    working_days = models.PositiveSmallIntegerField(_("working days"), default=30)
    employee_count = models.PositiveIntegerField(_("employees"), default=0)

    total_gross = models.DecimalField(
        _("gross salary"), max_digits=16, decimal_places=2, default=0
    )
    total_deductions = models.DecimalField(
        _("total deductions"), max_digits=16, decimal_places=2, default=0
    )
    total_tax = models.DecimalField(
        _("income tax"), max_digits=16, decimal_places=2, default=0
    )
    total_pf_employee = models.DecimalField(
        _("employee PF"), max_digits=16, decimal_places=2, default=0
    )
    total_pf_employer = models.DecimalField(
        _("employer PF"), max_digits=16, decimal_places=2, default=0
    )
    total_net = models.DecimalField(
        _("net payable"), max_digits=16, decimal_places=2, default=0
    )

    is_locked = models.BooleanField(_("locked"), default=False, db_index=True)
    journal = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_runs",
        verbose_name=_("accrual journal"),
    )
    payment_journal = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_payments",
        verbose_name=_("payment journal"),
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_runs_approved",
        verbose_name=_("approved by"),
    )
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_runs_paid",
        verbose_name=_("paid by"),
    )
    paid_at = models.DateTimeField(_("paid at"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_runs_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("payroll run")
        verbose_name_plural = _("payroll runs")
        ordering = ["-year", "-month", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["year", "month"], name="uniq_payrollrun_year_month"
            )
        ]
        permissions = [
            ("run_payroll", _("Can run payroll")),
            ("approve_payrollrun", _("Can approve & lock payroll runs")),
            ("pay_payrollrun", _("Can mark payroll runs as paid")),
            ("export_beftn", _("Can export BEFTN bank files")),
            ("manage_taxslab", _("Can manage income-tax slabs")),
            ("manage_payrollsettings", _("Can manage payroll settings")),
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.get_status_display()}"

    @property
    def period_label(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"

    @property
    def is_editable(self) -> bool:
        return self.status == PayrollRunStatus.DRAFT and not self.is_locked

    @property
    def can_pay(self) -> bool:
        return self.status == PayrollRunStatus.APPROVED

    def clean(self) -> None:
        if self.month and not 1 <= self.month <= 12:
            raise ValidationError(_("Month must be between 1 and 12."))


# ---------------------------------------------------------------------------
# Payslips
# ---------------------------------------------------------------------------
class Payslip(TimeStampedModel):
    """A frozen, per-employee payslip produced by a :class:`PayrollRun`."""

    run = models.ForeignKey(
        PayrollRun,
        on_delete=models.CASCADE,
        related_name="payslips",
        verbose_name=_("payroll run"),
    )
    staff = models.ForeignKey(
        Staff,
        on_delete=models.PROTECT,
        related_name="payslips",
        verbose_name=_("staff"),
    )
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=PayslipStatus.choices,
        default=PayslipStatus.DRAFT,
        db_index=True,
    )

    # Employee snapshots (may change later; history must not).
    employee_code = models.CharField(_("employee code"), max_length=30)
    name = models.CharField(_("name"), max_length=200)
    department = models.CharField(_("department"), max_length=120, blank=True)
    designation = models.CharField(_("designation"), max_length=120, blank=True)
    tax_category = models.CharField(
        _("tax category"),
        max_length=20,
        choices=TaxCategory.choices,
        default=TaxCategory.GENERAL,
    )

    # Salary-structure snapshot.
    basic = models.DecimalField(_("basic"), max_digits=14, decimal_places=2, default=0)
    house_rent = models.DecimalField(
        _("house rent"), max_digits=14, decimal_places=2, default=0
    )
    medical_allowance = models.DecimalField(
        _("medical allowance"), max_digits=14, decimal_places=2, default=0
    )
    transport_allowance = models.DecimalField(
        _("transport allowance"), max_digits=14, decimal_places=2, default=0
    )
    other_allowance = models.DecimalField(
        _("other allowance"), max_digits=14, decimal_places=2, default=0
    )
    structure_gross = models.DecimalField(
        _("structure gross"), max_digits=14, decimal_places=2, default=0
    )

    # Attendance summary.
    working_days = models.PositiveSmallIntegerField(_("working days"), default=30)
    present_days = models.DecimalField(
        _("present days"), max_digits=6, decimal_places=2, default=0
    )
    absent_days = models.DecimalField(
        _("absent days"), max_digits=6, decimal_places=2, default=0
    )
    late_days = models.DecimalField(
        _("late days"), max_digits=6, decimal_places=2, default=0
    )
    half_days = models.DecimalField(
        _("half days"), max_digits=6, decimal_places=2, default=0
    )
    unpaid_leave_days = models.DecimalField(
        _("unpaid leave days"), max_digits=6, decimal_places=2, default=0
    )
    paid_leave_days = models.DecimalField(
        _("paid leave days"), max_digits=6, decimal_places=2, default=0
    )

    # Earnings / deductions.
    adjustment_earning = models.DecimalField(
        _("adjustment earnings"), max_digits=14, decimal_places=2, default=0
    )
    adjustment_deduction = models.DecimalField(
        _("adjustment deductions"), max_digits=14, decimal_places=2, default=0
    )
    absence_deduction = models.DecimalField(
        _("absence deduction"), max_digits=14, decimal_places=2, default=0
    )
    late_deduction = models.DecimalField(
        _("late deduction"), max_digits=14, decimal_places=2, default=0
    )
    unpaid_leave_deduction = models.DecimalField(
        _("unpaid leave deduction"), max_digits=14, decimal_places=2, default=0
    )
    pf_employee = models.DecimalField(
        _("employee PF"), max_digits=14, decimal_places=2, default=0
    )
    pf_employer = models.DecimalField(
        _("employer PF"), max_digits=14, decimal_places=2, default=0
    )
    tax = models.DecimalField(
        _("income tax"), max_digits=14, decimal_places=2, default=0
    )
    gross_salary = models.DecimalField(
        _("earned gross"), max_digits=14, decimal_places=2, default=0
    )
    total_deductions = models.DecimalField(
        _("total deductions"), max_digits=14, decimal_places=2, default=0
    )
    net_pay = models.DecimalField(
        _("net pay"), max_digits=14, decimal_places=2, default=0
    )

    # Bank snapshot for BEFTN export.
    payment_method = models.CharField(
        _("payment method"),
        max_length=8,
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK,
    )
    bank_name = models.CharField(_("bank"), max_length=120, blank=True)
    bank_account_no = models.CharField(_("bank account no."), max_length=40, blank=True)
    bank_routing_no = models.CharField(_("routing no."), max_length=20, blank=True)
    remarks = models.CharField(_("remarks"), max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("payslip")
        verbose_name_plural = _("payslips")
        ordering = ["employee_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "staff"], name="uniq_payslip_run_staff"
            )
        ]

    def __str__(self) -> str:
        return f"{self.run.code} · {self.name}"

    @property
    def gross_earnings(self) -> Decimal:
        """Total earnings = salary structure + adjustment earnings."""
        return _dec(self.gross_salary)

    @property
    def total_deduction_amount(self) -> Decimal:
        return (
            _dec(self.absence_deduction)
            + _dec(self.late_deduction)
            + _dec(self.unpaid_leave_deduction)
            + _dec(self.pf_employee)
            + _dec(self.tax)
            + _dec(self.adjustment_deduction)
        )

    @property
    def attendance_deduction(self) -> Decimal:
        return (
            _dec(self.absence_deduction)
            + _dec(self.late_deduction)
            + _dec(self.unpaid_leave_deduction)
        )

    @property
    def total_earning_amount(self) -> Decimal:
        return self.gross_earnings

    @property
    def is_locked(self) -> bool:
        return self.status != PayslipStatus.DRAFT


# ---------------------------------------------------------------------------
# Salary adjustments
# ---------------------------------------------------------------------------
class SalaryAdjustment(TimeStampedModel):
    """A pre-run or post-run salary correction (arrears, recovery, bonus)."""

    staff = models.ForeignKey(
        Staff,
        on_delete=models.PROTECT,
        related_name="salary_adjustments",
        verbose_name=_("staff"),
    )
    year = models.PositiveSmallIntegerField(_("year"), db_index=True)
    month = models.PositiveSmallIntegerField(_("month"), db_index=True)
    kind = models.CharField(
        _("kind"),
        max_length=10,
        choices=AdjustmentKind.choices,
        default=AdjustmentKind.EARNING,
    )
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    reason = models.CharField(_("reason"), max_length=255)
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=AdjustmentStatus.choices,
        default=AdjustmentStatus.PENDING,
        db_index=True,
    )
    run = models.ForeignKey(
        PayrollRun,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="adjustments",
        verbose_name=_("applied run"),
    )
    payslip = models.ForeignKey(
        Payslip,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="adjustments",
        verbose_name=_("applied payslip"),
    )
    journal = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="salary_adjustments",
        verbose_name=_("journal entry"),
    )
    applied_at = models.DateTimeField(_("applied at"), null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="salary_adjustments_created",
        verbose_name=_("created by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("salary adjustment")
        verbose_name_plural = _("salary adjustments")
        ordering = ["-year", "-month", "-id"]
        indexes = [models.Index(fields=["year", "month", "status"])]

    def __str__(self) -> str:
        sign = "+" if self.kind == AdjustmentKind.EARNING else "-"
        return f"{self.staff} {sign}{self.amount} ({self.get_status_display()})"

    @property
    def signed_amount(self) -> Decimal:
        value = _dec(self.amount)
        return value if self.kind == AdjustmentKind.EARNING else -value

    @property
    def is_pending(self) -> bool:
        return self.status == AdjustmentStatus.PENDING

    def clean(self) -> None:
        if self.amount is not None and _dec(self.amount) <= 0:
            raise ValidationError(_("Adjustment amount must be greater than zero."))
