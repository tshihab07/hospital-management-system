"""Domain models for the Billing & Payments module (RULES Phase 12).

The billing module is the hospital's "money engine": it aggregates the charges
captured throughout the other modules (OPD consultations, IPD daily charges,
laboratory tests, pharmacy dispensing and OT implants/consumables) into a
patient invoice, applies VAT and an approval-tiered discount, records payments
across every accepted channel, prints money receipts, tracks advances/deposits
and processes refunds. Settling an IPD bill clears the patient's *Billing*
discharge clearance.

Money is always ``DecimalField(12, 2)``; financial records are soft-deleted
rather than removed.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.ipd.models import Admission
from apps.patients.models import Patient
from core.models import SoftDeleteModel, TimeStampedModel


def _dec(value) -> Decimal:
    """Coerce a value to ``Decimal`` (SQLite returns ``str`` for decimals)."""
    return Decimal(str(value or "0"))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class SequenceKind(models.TextChoices):
    BILL = "bill", _("Bill")
    RECEIPT = "receipt", _("Money receipt")
    ADVANCE = "advance", _("Advance")
    REFUND = "refund", _("Refund")
    CREDIT = "credit", _("Credit note")
    PACKAGE = "package", _("Package")


class BillType(models.TextChoices):
    OPD = "opd", _("OPD")
    IPD = "ipd", _("IPD")
    PACKAGE = "package", _("Package")


class BillStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ISSUED = "issued", _("Issued")
    PARTIALLY_PAID = "partially_paid", _("Partially paid")
    PAID = "paid", _("Paid")
    CANCELLED = "cancelled", _("Cancelled")


class BillItemType(models.TextChoices):
    CONSULTATION = "consultation", _("Consultation")
    PHARMACY = "pharmacy", _("Pharmacy")
    LAB = "lab", _("Laboratory")
    BED = "bed", _("Bed charge")
    NURSING = "nursing", _("Nursing")
    DOCTOR_VISIT = "doctor_visit", _("Doctor visit")
    PROCEDURE = "procedure", _("Procedure")
    OT = "ot", _("Operation theatre")
    IMPLANT = "implant", _("Implant")
    CONSUMABLE = "consumable", _("Consumable")
    EMERGENCY = "emergency", _("Emergency")
    PACKAGE = "package", _("Package")
    OTHER = "other", _("Other")


class PaymentMode(models.TextChoices):
    CASH = "cash", _("Cash")
    CARD = "card", _("Card")
    BKASH = "bkash", _("bKash")
    NAGAD = "nagad", _("Nagad")
    ROCKET = "rocket", _("Rocket")
    BANK = "bank", _("Bank transfer")


class DiscountStatus(models.TextChoices):
    NONE = "none", _("None")
    PENDING = "pending", _("Pending approval")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")


class RefundStatus(models.TextChoices):
    REQUESTED = "requested", _("Requested")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    PROCESSED = "processed", _("Processed")


class CreditNoteStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ISSUED = "issued", _("Issued")
    VOID = "void", _("Void")


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------
class BillingSequence(TimeStampedModel):
    """Per-year counter per document kind (bill / receipt / advance / refund)."""

    year = models.PositiveSmallIntegerField(_("year"))
    kind = models.CharField(_("kind"), max_length=10, choices=SequenceKind.choices)
    last_number = models.PositiveIntegerField(_("last number"), default=0)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("billing sequence")
        verbose_name_plural = _("billing sequences")
        constraints = [
            models.UniqueConstraint(
                fields=["year", "kind"], name="uniq_billing_sequence_year_kind"
            )
        ]

    def __str__(self) -> str:
        return f"{self.year} {self.kind} → {self.last_number}"


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------
class Bill(SoftDeleteModel):
    """A patient invoice (OPD, IPD or a bundled package)."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="bills",
        verbose_name=_("patient"),
    )
    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bills",
        verbose_name=_("admission"),
    )
    bill_no = models.CharField(_("bill number"), max_length=40, unique=True)
    bill_type = models.CharField(
        _("bill type"),
        max_length=10,
        choices=BillType.choices,
        default=BillType.OPD,
        db_index=True,
    )
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=BillStatus.choices,
        default=BillStatus.DRAFT,
        db_index=True,
    )
    subtotal = models.DecimalField(
        _("subtotal"), max_digits=12, decimal_places=2, default=0
    )
    discount = models.DecimalField(
        _("discount"), max_digits=12, decimal_places=2, default=0
    )
    vat = models.DecimalField(_("VAT"), max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(_("total"), max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(
        _("paid amount"), max_digits=12, decimal_places=2, default=0
    )
    vat_rate = models.DecimalField(
        _("VAT rate (%)"), max_digits=5, decimal_places=2, default=0
    )
    discount_reason = models.CharField(_("discount reason"), max_length=255, blank=True)
    discount_status = models.CharField(
        _("discount status"),
        max_length=10,
        choices=DiscountStatus.choices,
        default=DiscountStatus.NONE,
    )
    discount_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="billing_discounts_approved",
        verbose_name=_("discount approved by"),
    )
    discount_approved_at = models.DateTimeField(
        _("discount approved at"), null=True, blank=True
    )
    notes = models.TextField(_("notes"), blank=True)
    issued_at = models.DateTimeField(_("issued at"), null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="billing_bills_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("bill")
        verbose_name_plural = _("bills")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["bill_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.bill_no} · {self.patient.display_name}"

    @property
    def due_amount(self) -> Decimal:
        return _dec(self.total) - _dec(self.paid_amount)

    @property
    def is_settled(self) -> bool:
        return _dec(self.total) > 0 and _dec(self.paid_amount) >= _dec(self.total)

    @property
    def is_locked(self) -> bool:
        """A bill is locked for editing as soon as any money has moved.

        After payment the only correction path is a credit note (RULES Phase 12
        exit criterion: *"Bill cannot be edited after payment (credit note
        only)"*).
        """
        return _dec(self.paid_amount) > 0

    def recompute(self, save: bool = True) -> "Bill":
        """Recompute subtotal/VAT/total from the bill's line items."""
        items = list(self.items.all())
        self.subtotal = sum((_dec(i.amount) for i in items), Decimal("0"))
        self.vat = sum((_dec(i.vat_amount) for i in items), Decimal("0"))
        self.total = _dec(self.subtotal) - _dec(self.discount) + _dec(self.vat)
        if save:
            self.save(
                update_fields=[
                    "subtotal",
                    "vat",
                    "total",
                    "updated_at",
                ]
            )
        return self


class BillItem(TimeStampedModel):
    """A single charge line on a :class:`Bill`."""

    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("bill"),
    )
    item_type = models.CharField(
        _("item type"),
        max_length=20,
        choices=BillItemType.choices,
        default=BillItemType.OTHER,
        db_index=True,
    )
    description = models.CharField(_("description"), max_length=255)
    quantity = models.DecimalField(
        _("quantity"), max_digits=10, decimal_places=2, default=1
    )
    unit_price = models.DecimalField(
        _("unit price"), max_digits=12, decimal_places=2, default=0
    )
    amount = models.DecimalField(
        _("amount"), max_digits=12, decimal_places=2, default=0
    )
    tax_rate = models.DecimalField(
        _("tax rate (%)"), max_digits=5, decimal_places=2, default=0
    )
    vat_amount = models.DecimalField(
        _("VAT amount"), max_digits=12, decimal_places=2, default=0
    )
    service_date = models.DateField(_("service date"), null=True, blank=True)
    source_type = models.CharField(_("source type"), max_length=60, blank=True)
    source_id = models.CharField(_("source id"), max_length=40, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("bill item")
        verbose_name_plural = _("bill items")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.description} · {self.amount}"


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class Payment(SoftDeleteModel):
    """A payment received against a :class:`Bill`."""

    bill = models.ForeignKey(
        Bill,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name=_("bill"),
    )
    method = models.CharField(
        _("method"),
        max_length=10,
        choices=PaymentMode.choices,
        default=PaymentMode.CASH,
        db_index=True,
    )
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    txn_ref = models.CharField(_("transaction reference"), max_length=120, blank=True)
    gateway_ref = models.CharField(_("gateway reference"), max_length=120, blank=True)
    paid_at = models.DateTimeField(_("paid at"), default=timezone.now, db_index=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="billing_payments_received",
        verbose_name=_("received by"),
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("payment")
        verbose_name_plural = _("payments")
        ordering = ["-paid_at"]

    def __str__(self) -> str:
        return f"{self.get_method_display()} {self.amount} · {self.bill.bill_no}"


class MoneyReceipt(TimeStampedModel):
    """A uniquely numbered, printable receipt for a :class:`Payment`."""

    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="receipt",
        verbose_name=_("payment"),
    )
    receipt_no = models.CharField(_("receipt number"), max_length=40, unique=True)
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    issued_at = models.DateTimeField(_("issued at"), default=timezone.now)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="billing_receipts_issued",
        verbose_name=_("issued by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("money receipt")
        verbose_name_plural = _("money receipts")
        ordering = ["-issued_at"]

    def __str__(self) -> str:
        return self.receipt_no


# ---------------------------------------------------------------------------
# Advances / deposits
# ---------------------------------------------------------------------------
class Advance(SoftDeleteModel):
    """An advance deposit paid by a patient (typically before/at IPD admission)."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="advances",
        verbose_name=_("patient"),
    )
    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="advances",
        verbose_name=_("admission"),
    )
    advance_no = models.CharField(_("advance number"), max_length=40, unique=True)
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    adjusted_amount = models.DecimalField(
        _("adjusted amount"), max_digits=12, decimal_places=2, default=0
    )
    method = models.CharField(
        _("method"),
        max_length=10,
        choices=PaymentMode.choices,
        default=PaymentMode.CASH,
    )
    txn_ref = models.CharField(_("transaction reference"), max_length=120, blank=True)
    paid_at = models.DateTimeField(_("paid at"), default=timezone.now, db_index=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="billing_advances_received",
        verbose_name=_("received by"),
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("advance")
        verbose_name_plural = _("advances")
        ordering = ["-paid_at"]

    def __str__(self) -> str:
        return f"{self.advance_no} · {self.patient.display_name}"

    @property
    def balance(self) -> Decimal:
        return _dec(self.amount) - _dec(self.adjusted_amount)


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
class Refund(SoftDeleteModel):
    """A refund of previously collected money, with an approval workflow."""

    bill = models.ForeignKey(
        Bill,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refunds",
        verbose_name=_("bill"),
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refunds",
        verbose_name=_("payment"),
    )
    refund_no = models.CharField(_("refund number"), max_length=40, unique=True)
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    method = models.CharField(
        _("method"),
        max_length=10,
        choices=PaymentMode.choices,
        default=PaymentMode.CASH,
    )
    reason = models.TextField(_("reason"))
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=RefundStatus.choices,
        default=RefundStatus.REQUESTED,
        db_index=True,
    )
    txn_ref = models.CharField(_("transaction reference"), max_length=120, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="billing_refunds_requested",
        verbose_name=_("requested by"),
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="billing_refunds_approved",
        verbose_name=_("approved by"),
    )
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    refunded_at = models.DateTimeField(_("refunded at"), null=True, blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("refund")
        verbose_name_plural = _("refunds")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.refund_no} · {self.amount}"


# ---------------------------------------------------------------------------
# Service packages (bundled rates for surgeries / maternity)
# ---------------------------------------------------------------------------
class ServicePackage(TimeStampedModel):
    """A bundled rate card, e.g. a caesarean-section package (PRD §4.7.1)."""

    code = models.CharField(_("code"), max_length=40, unique=True)
    name = models.CharField(_("name"), max_length=200)
    name_bn = models.CharField(_("name (Bengali)"), max_length=200, blank=True)
    description = models.TextField(_("description"), blank=True)
    price = models.DecimalField(
        _("package price"), max_digits=12, decimal_places=2, default=0
    )
    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("service package")
        verbose_name_plural = _("service packages")
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.code} · {self.name}"

    @property
    def component_total(self) -> Decimal:
        return sum(
            (_dec(i.amount) for i in self.components.all()), Decimal("0")
        )


class ServicePackageItem(TimeStampedModel):
    """One component line of a :class:`ServicePackage`."""

    package = models.ForeignKey(
        ServicePackage,
        on_delete=models.CASCADE,
        related_name="components",
        verbose_name=_("package"),
    )
    item_type = models.CharField(
        _("item type"),
        max_length=20,
        choices=BillItemType.choices,
        default=BillItemType.OTHER,
    )
    description = models.CharField(_("description"), max_length=255)
    quantity = models.DecimalField(
        _("quantity"), max_digits=10, decimal_places=2, default=1
    )
    unit_price = models.DecimalField(
        _("unit price"), max_digits=12, decimal_places=2, default=0
    )
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2, default=0)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("package component")
        verbose_name_plural = _("package components")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.package.code} · {self.description}"

    def save(self, *args, **kwargs):
        self.amount = _dec(self.quantity) * _dec(self.unit_price)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Credit notes (the only correction path after a payment)
# ---------------------------------------------------------------------------
class CreditNote(SoftDeleteModel):
    """A negative adjustment issued against a locked bill.

    Once money has moved the invoice is frozen (``Bill.is_locked``); the
    correction route is a credit note, which posts negative bill items and
    re-issues the revised total.
    """

    bill = models.ForeignKey(
        Bill,
        on_delete=models.PROTECT,
        related_name="credit_notes",
        verbose_name=_("bill"),
    )
    note_no = models.CharField(_("credit note number"), max_length=40, unique=True)
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    reason = models.TextField(_("reason"))
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=CreditNoteStatus.choices,
        default=CreditNoteStatus.DRAFT,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credit_notes_created",
        verbose_name=_("created by"),
    )
    issued_at = models.DateTimeField(_("issued at"), null=True, blank=True)
    voided_at = models.DateTimeField(_("voided at"), null=True, blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("credit note")
        verbose_name_plural = _("credit notes")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.note_no} · {self.amount}"
