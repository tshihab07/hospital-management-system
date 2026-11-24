"""Domain models for the Accounting & Financial Reports module (Phase 13).

This module is the hospital's **general ledger**. It holds a professional chart
of accounts, fiscal periods, double-entry journal entries with their balancing
lines, plus thin convenience documents (expenses, vendor payments) that post to
the ledger. Billing, pharmacy and (later) payroll auto-post into it so that
every money movement is reflected in a balanced trial balance.

Money is always ``DecimalField(14, 2)``; journals and expenses are soft-deleted
rather than removed, and posted entries are immutable (reverse, never edit).
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import SoftDeleteModel, TimeStampedModel


def _dec(value) -> Decimal:
    """Coerce a value to ``Decimal`` (SQLite returns ``str`` for decimals)."""
    return Decimal(str(value or "0"))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class AccountType(models.TextChoices):
    ASSET = "asset", _("Asset")
    LIABILITY = "liability", _("Liability")
    EQUITY = "equity", _("Equity")
    INCOME = "income", _("Income")
    EXPENSE = "expense", _("Expense")


class NormalBalance(models.TextChoices):
    DEBIT = "debit", _("Debit")
    CREDIT = "credit", _("Credit")


class SystemAccount(models.TextChoices):
    """Well-known control accounts looked up by key rather than by code."""

    CASH = "cash", _("Cash in hand")
    BANK = "bank", _("Bank")
    MFS = "mfs", _("Mobile financial services")
    CARD = "card", _("Card clearing")
    AR = "ar", _("Accounts receivable – patients")
    AP = "ap", _("Accounts payable – vendors")
    VAT_PAYABLE = "vat_payable", _("Output VAT payable")
    VAT_RECEIVABLE = "vat_receivable", _("Input VAT receivable")
    PATIENT_ADVANCE = "patient_advance", _("Patient advances & deposits")
    DISCOUNT = "discount", _("Discount allowed")
    SALES_RETURN = "sales_return", _("Sales returns & allowances")
    INVENTORY = "inventory", _("Inventory – pharmacy")
    RETAINED_EARNINGS = "retained_earnings", _("Retained earnings")
    OPENING_BALANCE = "opening_balance", _("Opening balance equity")

    SALARY_PAYABLE = "salary_payable", _("Salaries payable – staff")
    PF_PAYABLE = "pf_payable", _("Provident fund payable")
    TAX_PAYABLE = "tax_payable", _("Income tax payable (salaries)")
    DEDUCTIONS_PAYABLE = "deductions_payable", _("Other payroll deductions payable")

    REVENUE_CONSULTATION = "revenue_consultation", _("Consultation revenue")
    REVENUE_PHARMACY = "revenue_pharmacy", _("Pharmacy revenue")
    REVENUE_LAB = "revenue_lab", _("Laboratory revenue")
    REVENUE_RADIOLOGY = "revenue_radiology", _("Radiology revenue")
    REVENUE_BED = "revenue_bed", _("Bed & nursing revenue")
    REVENUE_DOCTOR_VISIT = "revenue_doctor_visit", _("Doctor visit revenue")
    REVENUE_PROCEDURE = "revenue_procedure", _("Procedure revenue")
    REVENUE_OT = "revenue_ot", _("Operation theatre revenue")
    REVENUE_IMPLANT = "revenue_implant", _("Implant & consumables revenue")
    REVENUE_EMERGENCY = "revenue_emergency", _("Emergency revenue")
    REVENUE_PACKAGE = "revenue_package", _("Package revenue")
    REVENUE_OTHER = "revenue_other", _("Other operating revenue")

    EXPENSE_COGS = "expense_cogs", _("Pharmacy cost of goods sold")
    EXPENSE_SALARY = "expense_salary", _("Salaries & wages")
    EXPENSE_STAFF_BENEFITS = "expense_staff_benefits", _("Staff benefits")
    EXPENSE_OTHER = "expense_other", _("Miscellaneous expenses")


class JournalEntryType(models.TextChoices):
    MANUAL = "manual", _("Manual journal")
    AUTO = "auto", _("Automatic posting")
    OPENING = "opening", _("Opening balance")
    ADJUSTMENT = "adjustment", _("Adjustment")
    REVERSAL = "reversal", _("Reversal")
    CLOSING = "closing", _("Year-end closing")


class JournalStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    POSTED = "posted", _("Posted")
    REVERSED = "reversed", _("Reversed")


class PartyType(models.TextChoices):
    PATIENT = "patient", _("Patient")
    VENDOR = "vendor", _("Vendor")
    DOCTOR = "doctor", _("Doctor")
    STAFF = "staff", _("Staff")
    OTHER = "other", _("Other")


# ---------------------------------------------------------------------------
# Chart of accounts
# ---------------------------------------------------------------------------
class Account(SoftDeleteModel):
    """A node in the hospital's chart of accounts.

    Accounts form a tree (``parent``/``children``). A *group* account only
    summarises its children and cannot receive postings; a *ledger* (postable)
    account is where journal lines land. Control accounts carry a
    :class:`SystemAccount` ``system_key`` so the posting engine can find them
    without depending on their numeric code.
    """

    code = models.CharField(_("code"), max_length=20, unique=True)
    name = models.CharField(_("name"), max_length=200)
    name_bn = models.CharField(_("name (Bengali)"), max_length=200, blank=True)
    account_type = models.CharField(
        _("account type"),
        max_length=12,
        choices=AccountType.choices,
        db_index=True,
    )
    normal_balance = models.CharField(
        _("normal balance"),
        max_length=6,
        choices=NormalBalance.choices,
        blank=True,
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name=_("parent account"),
    )
    is_group = models.BooleanField(
        _("group account"),
        default=False,
        help_text=_("Group accounts are headings only and cannot be posted to."),
    )
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    is_system = models.BooleanField(
        _("system account"),
        default=False,
        help_text=_("System control accounts cannot be deleted."),
    )
    system_key = models.CharField(
        _("system key"),
        max_length=40,
        unique=True,
        null=True,
        blank=True,
        choices=SystemAccount.choices,
    )
    opening_balance = models.DecimalField(
        _("opening balance"), max_digits=14, decimal_places=2, default=0
    )
    description = models.TextField(_("description"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accounts_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("account")
        verbose_name_plural = _("accounts")
        ordering = ["code"]
        indexes = [models.Index(fields=["account_type", "is_active"])]

    def __str__(self) -> str:
        return f"{self.code} · {self.name}"

    def save(self, *args, **kwargs):
        from .chart import NORMAL_BY_TYPE

        if not self.normal_balance:
            self.normal_balance = NORMAL_BY_TYPE.get(
                self.account_type, NormalBalance.DEBIT
            )
        if self.system_key:
            self.is_system = True
        super().save(*args, **kwargs)

    def clean(self) -> None:
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError(_("An account cannot be its own parent."))
        if self.is_group and self.system_key:
            raise ValidationError(_("A control account cannot be a group account."))

    @property
    def display_name(self) -> str:
        return f"{self.code} · {self.name}"

    @property
    def is_balance_sheet(self) -> bool:
        return self.account_type in {
            AccountType.ASSET,
            AccountType.LIABILITY,
            AccountType.EQUITY,
        }

    @property
    def is_income_statement(self) -> bool:
        return self.account_type in {AccountType.INCOME, AccountType.EXPENSE}

    def posting_totals(self):
        """Aggregate posted debit/credit for this account."""
        return self.lines.filter(journal__status=JournalStatus.POSTED).aggregate(
            debit=models.Sum("debit"), credit=models.Sum("credit")
        )

    @property
    def balance(self) -> Decimal:
        """Signed balance in the account's normal direction."""
        totals = self.posting_totals()
        debit = _dec(totals.get("debit"))
        credit = _dec(totals.get("credit"))
        if self.normal_balance == NormalBalance.CREDIT:
            return credit - debit
        return debit - credit


# ---------------------------------------------------------------------------
# Fiscal periods
# ---------------------------------------------------------------------------
class AccountingPeriod(SoftDeleteModel):
    """A fiscal period (typically a month) that can be closed to lock postings."""

    name = models.CharField(_("name"), max_length=100, unique=True)
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    is_closed = models.BooleanField(_("closed"), default=False, db_index=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="periods_closed",
        verbose_name=_("closed by"),
    )
    closed_at = models.DateTimeField(_("closed at"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("accounting period")
        verbose_name_plural = _("accounting periods")
        ordering = ["-start_date"]

    def __str__(self) -> str:
        return self.name

    def contains(self, day) -> bool:
        return self.start_date <= day <= self.end_date

    @property
    def is_locked(self) -> bool:
        return self.is_closed


class AccountingSequence(TimeStampedModel):
    """Per-year counter for journal entry numbers."""

    year = models.PositiveSmallIntegerField(_("year"), unique=True)
    last_number = models.PositiveIntegerField(_("last number"), default=0)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("accounting sequence")
        verbose_name_plural = _("accounting sequences")

    def __str__(self) -> str:
        return f"{self.year} → {self.last_number}"


# ---------------------------------------------------------------------------
# Journals
# ---------------------------------------------------------------------------
class JournalEntry(SoftDeleteModel):
    """A balanced, double-entry journal entry (header)."""

    entry_no = models.CharField(_("entry number"), max_length=40, unique=True)
    date = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    entry_type = models.CharField(
        _("entry type"),
        max_length=12,
        choices=JournalEntryType.choices,
        default=JournalEntryType.MANUAL,
        db_index=True,
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=JournalStatus.choices,
        default=JournalStatus.DRAFT,
        db_index=True,
    )
    memo = models.CharField(_("memo"), max_length=255, blank=True)
    reference = models.CharField(_("reference"), max_length=120, blank=True)
    period = models.ForeignKey(
        AccountingPeriod,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journals",
        verbose_name=_("period"),
    )
    source_type = models.CharField(
        _("source type"), max_length=60, blank=True, db_index=True
    )
    source_id = models.CharField(
        _("source id"), max_length=40, blank=True, db_index=True
    )
    total_debit = models.DecimalField(
        _("total debit"), max_digits=14, decimal_places=2, default=0
    )
    total_credit = models.DecimalField(
        _("total credit"), max_digits=14, decimal_places=2, default=0
    )
    reversal_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reversals",
        verbose_name=_("reversal of"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journals_created",
        verbose_name=_("created by"),
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journals_posted",
        verbose_name=_("posted by"),
    )
    posted_at = models.DateTimeField(_("posted at"), null=True, blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("journal entry")
        verbose_name_plural = _("journal entries")
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["source_type", "source_id"]),
            models.Index(fields=["status", "date"]),
        ]
        permissions = [
            ("post_journalentry", _("Can post journal entries")),
            ("reverse_journalentry", _("Can reverse journal entries")),
            ("close_accountingperiod", _("Can close accounting periods")),
            ("view_accountingreports", _("Can view accounting reports")),
        ]

    def __str__(self) -> str:
        return f"{self.entry_no} · {self.memo or self.get_entry_type_display()}"

    @property
    def is_balanced(self) -> bool:
        return (
            _dec(self.total_debit) == _dec(self.total_credit)
            and _dec(self.total_debit) > 0
        )

    @property
    def is_editable(self) -> bool:
        return self.status == JournalStatus.DRAFT

    def recompute(self, save: bool = True) -> "JournalEntry":
        totals = self.lines.aggregate(
            debit=models.Sum("debit"), credit=models.Sum("credit")
        )
        self.total_debit = _dec(totals.get("debit"))
        self.total_credit = _dec(totals.get("credit"))
        if save:
            self.save(update_fields=["total_debit", "total_credit", "updated_at"])
        return self


class JournalLine(TimeStampedModel):
    """A single debit or credit line of a :class:`JournalEntry`."""

    journal = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("journal entry"),
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="lines",
        verbose_name=_("account"),
    )
    description = models.CharField(_("description"), max_length=255, blank=True)
    debit = models.DecimalField(_("debit"), max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(
        _("credit"), max_digits=14, decimal_places=2, default=0
    )
    party_type = models.CharField(
        _("party type"),
        max_length=10,
        choices=PartyType.choices,
        blank=True,
        db_index=True,
    )
    party_id = models.CharField(_("party id"), max_length=40, blank=True, db_index=True)
    department = models.ForeignKey(
        "masters.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journal_lines",
        verbose_name=_("department"),
    )
    doctor = models.ForeignKey(
        "opd.Doctor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journal_lines",
        verbose_name=_("doctor"),
    )
    bill = models.ForeignKey(
        "billing.Bill",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journal_lines",
        verbose_name=_("bill"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("journal line")
        verbose_name_plural = _("journal lines")
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                check=~(models.Q(debit=0) & models.Q(credit=0)),
                name="journal_line_nonzero",
            )
        ]

    def __str__(self) -> str:
        return f"{self.account.code} {'Dr' if self.is_debit else 'Cr'} {self.amount}"

    @property
    def amount(self) -> Decimal:
        return _dec(self.debit) if _dec(self.debit) else _dec(self.credit)

    @property
    def is_debit(self) -> bool:
        return _dec(self.debit) > 0


# ---------------------------------------------------------------------------
# Convenience documents
# ---------------------------------------------------------------------------
class Expense(SoftDeleteModel):
    """A hospital operating expense that posts to the general ledger.

    Debit the chosen expense ``category`` account, credit the ``paid_from``
    account (cash / bank / accounts payable).
    """

    date = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    category = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="expenses",
        verbose_name=_("expense account"),
    )
    paid_from = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="expenses_paid",
        verbose_name=_("paid from account"),
    )
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    description = models.CharField(_("description"), max_length=255)
    vendor = models.ForeignKey(
        "pharmacy.Vendor",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="expenses",
        verbose_name=_("vendor"),
    )
    reference = models.CharField(_("reference"), max_length=120, blank=True)
    journal = models.ForeignKey(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="expenses",
        verbose_name=_("journal entry"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="expenses_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("expense")
        verbose_name_plural = _("expenses")
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"{self.description} · {self.amount}"


class VendorPayment(SoftDeleteModel):
    """A payment made to a vendor against accounts payable.

    Debit Accounts Payable, credit the cash / bank account implied by the
    payment method.
    """

    date = models.DateField(_("date"), default=timezone.localdate, db_index=True)
    vendor = models.ForeignKey(
        "pharmacy.Vendor",
        on_delete=models.PROTECT,
        related_name="accounting_payments",
        verbose_name=_("vendor"),
    )
    amount = models.DecimalField(_("amount"), max_digits=14, decimal_places=2)
    method = models.CharField(
        _("method"),
        max_length=10,
        help_text=_("Billing payment mode, e.g. cash / bank / bkash."),
    )
    grn = models.ForeignKey(
        "pharmacy.GoodsReceiptNote",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendor_payments",
        verbose_name=_("goods receipt note"),
    )
    reference = models.CharField(_("reference"), max_length=120, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    journal = models.ForeignKey(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendor_payments",
        verbose_name=_("journal entry"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendor_payments_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("vendor payment")
        verbose_name_plural = _("vendor payments")
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"{self.vendor} · {self.amount}"
