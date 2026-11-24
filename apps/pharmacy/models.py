"""Domain models for the Pharmacy & Inventory module (RULES Phase 11).

Covers central/sub-store setup, drug stock batches with expiry tracking, an
append-only stock-movement ledger, vendor master and the PR → PO → GRN purchase
flow, stock transfer/return/adjustment, and FIFO prescription dispensing.
Pharmacy charges are captured (``is_billed``) for posting to the patient ledger
in Phase 12.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.emr.models import Prescription, PrescriptionItem
from apps.masters.models import Drug
from apps.patients.models import Patient
from core.models import SoftDeleteModel, TimeStampedModel


def _dec(value) -> Decimal:
    """Coerce a value to Decimal (SQLite returns str for DecimalField on create)."""
    if value is None:
        return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class SequenceKind(models.TextChoices):
    REQUISITION = "requisition", _("Purchase requisition")
    PURCHASE_ORDER = "purchase_order", _("Purchase order")
    GRN = "grn", _("Goods receipt note")


class StoreType(models.TextChoices):
    CENTRAL = "central", _("Central store")
    SUB_STORE = "sub_store", _("Sub-store")


class MovementType(models.TextChoices):
    RECEIPT = "receipt", _("Receipt")
    DISPENSE = "dispense", _("Dispense")
    TRANSFER_IN = "transfer_in", _("Transfer in")
    TRANSFER_OUT = "transfer_out", _("Transfer out")
    ADJUSTMENT = "adjustment", _("Adjustment")
    RETURN = "return", _("Return to vendor")


class RequisitionStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SUBMITTED = "submitted", _("Submitted")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    CONVERTED = "converted", _("Converted to PO")
    CANCELLED = "cancelled", _("Cancelled")


class POStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    PARTIAL = "partial", _("Partially received")
    RECEIVED = "received", _("Received")
    CANCELLED = "cancelled", _("Cancelled")


class DispenseStatus(models.TextChoices):
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------
class PharmacySequence(TimeStampedModel):
    """Per-year counter per document kind (PR / PO / GRN)."""

    year = models.PositiveSmallIntegerField(_("year"))
    kind = models.CharField(_("kind"), max_length=20, choices=SequenceKind.choices)
    last_number = models.PositiveIntegerField(_("last number"), default=0)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("pharmacy sequence")
        verbose_name_plural = _("pharmacy sequences")
        constraints = [
            models.UniqueConstraint(
                fields=["year", "kind"], name="uniq_pharmacy_sequence_year_kind"
            )
        ]

    def __str__(self) -> str:
        return f"{self.year} {self.kind} → {self.last_number}"


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
class PharmacyStore(TimeStampedModel):
    """A central store or a ward/sub-store."""

    name = models.CharField(_("name"), max_length=150, unique=True)
    code = models.CharField(_("code"), max_length=30, unique=True)
    store_type = models.CharField(
        _("type"),
        max_length=12,
        choices=StoreType.choices,
        default=StoreType.SUB_STORE,
    )
    location = models.CharField(_("location"), max_length=150, blank=True)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("pharmacy store")
        verbose_name_plural = _("pharmacy stores")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Vendor master
# ---------------------------------------------------------------------------
class Vendor(TimeStampedModel):
    name = models.CharField(_("name"), max_length=200, unique=True)
    contact_person = models.CharField(_("contact person"), max_length=150, blank=True)
    phone = models.CharField(_("phone"), max_length=20, blank=True)
    email = models.EmailField(_("email"), blank=True)
    address = models.TextField(_("address"), blank=True)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("vendor")
        verbose_name_plural = _("vendors")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------
class StockBatch(TimeStampedModel):
    """A quantity of one drug in one store, identified by batch + expiry."""

    store = models.ForeignKey(
        PharmacyStore,
        on_delete=models.PROTECT,
        related_name="batches",
        verbose_name=_("store"),
    )
    drug = models.ForeignKey(
        Drug,
        on_delete=models.PROTECT,
        related_name="stock_batches",
        verbose_name=_("drug"),
    )
    batch_no = models.CharField(_("batch no."), max_length=60)
    expiry_date = models.DateField(
        _("expiry date"), null=True, blank=True, db_index=True
    )
    quantity = models.PositiveIntegerField(_("quantity"), default=0)
    purchase_price = models.DecimalField(
        _("purchase price"), max_digits=12, decimal_places=2, default=0
    )
    mrp = models.DecimalField(_("MRP"), max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("stock batch")
        verbose_name_plural = _("stock batches")
        ordering = ["drug__generic_name", "expiry_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "drug", "batch_no"], name="uniq_stock_batch_store_drug"
            )
        ]
        indexes = [models.Index(fields=["store", "drug", "expiry_date"])]

    def __str__(self) -> str:
        return f"{self.drug} · {self.batch_no}"

    @property
    def is_expired(self) -> bool:
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def stock_value(self) -> Decimal:
        return _dec(self.purchase_price) * self.quantity


class StockMovement(TimeStampedModel):
    """Append-only ledger of every stock change (audit trail)."""

    batch = models.ForeignKey(
        StockBatch,
        on_delete=models.PROTECT,
        related_name="movements",
        verbose_name=_("batch"),
    )
    movement_type = models.CharField(
        _("type"), max_length=15, choices=MovementType.choices, db_index=True
    )
    quantity = models.IntegerField(_("quantity"))  # positive in, negative out
    balance_after = models.IntegerField(_("balance after"), default=0)
    reference = models.CharField(_("reference"), max_length=120, blank=True)
    moved_at = models.DateTimeField(_("moved at"), default=timezone.now, db_index=True)
    moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
        verbose_name=_("moved by"),
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")
        ordering = ["-moved_at", "-id"]

    def __str__(self) -> str:
        return f"{self.get_movement_type_display()} {self.quantity} · {self.batch_id}"


# ---------------------------------------------------------------------------
# Purchase requisition
# ---------------------------------------------------------------------------
class PurchaseRequisition(SoftDeleteModel):
    pr_number = models.CharField(_("PR number"), max_length=30, unique=True)
    store = models.ForeignKey(
        PharmacyStore,
        on_delete=models.PROTECT,
        related_name="requisitions",
        verbose_name=_("store"),
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_requisitions",
        verbose_name=_("requested by"),
    )
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=RequisitionStatus.choices,
        default=RequisitionStatus.DRAFT,
        db_index=True,
    )
    needed_by = models.DateField(_("needed by"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("purchase requisition")
        verbose_name_plural = _("purchase requisitions")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.pr_number


class PurchaseRequisitionItem(TimeStampedModel):
    requisition = models.ForeignKey(
        PurchaseRequisition,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("requisition"),
    )
    drug = models.ForeignKey(
        Drug,
        on_delete=models.PROTECT,
        related_name="requisition_items",
        verbose_name=_("drug"),
    )
    quantity = models.PositiveIntegerField(_("quantity"), default=1)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("requisition item")
        verbose_name_plural = _("requisition items")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.drug} × {self.quantity}"


# ---------------------------------------------------------------------------
# Purchase order
# ---------------------------------------------------------------------------
class PurchaseOrder(SoftDeleteModel):
    po_number = models.CharField(_("PO number"), max_length=30, unique=True)
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name=_("vendor"),
    )
    store = models.ForeignKey(
        PharmacyStore,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name=_("store"),
    )
    requisition = models.ForeignKey(
        PurchaseRequisition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders",
        verbose_name=_("requisition"),
    )
    order_date = models.DateField(_("order date"), default=timezone.localdate)
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=POStatus.choices,
        default=POStatus.DRAFT,
        db_index=True,
    )
    total_amount = models.DecimalField(
        _("total amount"), max_digits=12, decimal_places=2, default=0
    )
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("purchase order")
        verbose_name_plural = _("purchase orders")
        ordering = ["-order_date", "-id"]

    def __str__(self) -> str:
        return self.po_number

    def recompute_total(self, save: bool = True) -> Decimal:
        total = sum((item.line_total for item in self.items.all()), Decimal("0"))
        self.total_amount = total
        if save:
            self.save(update_fields=["total_amount", "updated_at"])
        return total


class PurchaseOrderItem(TimeStampedModel):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("purchase order"),
    )
    drug = models.ForeignKey(
        Drug,
        on_delete=models.PROTECT,
        related_name="purchase_order_items",
        verbose_name=_("drug"),
    )
    quantity_ordered = models.PositiveIntegerField(_("quantity ordered"), default=1)
    quantity_received = models.PositiveIntegerField(_("quantity received"), default=0)
    unit_price = models.DecimalField(
        _("unit price"), max_digits=12, decimal_places=2, default=0
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("purchase order item")
        verbose_name_plural = _("purchase order items")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.drug} × {self.quantity_ordered}"

    @property
    def line_total(self) -> Decimal:
        return _dec(self.unit_price) * self.quantity_ordered

    @property
    def is_fully_received(self) -> bool:
        return self.quantity_received >= self.quantity_ordered


# ---------------------------------------------------------------------------
# Goods receipt note
# ---------------------------------------------------------------------------
class GoodsReceiptNote(TimeStampedModel):
    grn_number = models.CharField(_("GRN number"), max_length=30, unique=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grns",
        verbose_name=_("purchase order"),
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="grns",
        verbose_name=_("vendor"),
    )
    store = models.ForeignKey(
        PharmacyStore,
        on_delete=models.PROTECT,
        related_name="grns",
        verbose_name=_("store"),
    )
    received_date = models.DateField(_("received date"), default=timezone.localdate)
    total_amount = models.DecimalField(
        _("total amount"), max_digits=12, decimal_places=2, default=0
    )
    notes = models.TextField(_("notes"), blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grns_received",
        verbose_name=_("received by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("goods receipt note")
        verbose_name_plural = _("goods receipt notes")
        ordering = ["-received_date", "-id"]

    def __str__(self) -> str:
        return self.grn_number


class GRNItem(TimeStampedModel):
    grn = models.ForeignKey(
        GoodsReceiptNote,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("GRN"),
    )
    drug = models.ForeignKey(
        Drug, on_delete=models.PROTECT, related_name="grn_items", verbose_name=_("drug")
    )
    po_item = models.ForeignKey(
        PurchaseOrderItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grn_items",
        verbose_name=_("PO item"),
    )
    batch_no = models.CharField(_("batch no."), max_length=60)
    expiry_date = models.DateField(_("expiry date"), null=True, blank=True)
    quantity = models.PositiveIntegerField(_("quantity"), default=0)
    purchase_price = models.DecimalField(
        _("purchase price"), max_digits=12, decimal_places=2, default=0
    )
    mrp = models.DecimalField(_("MRP"), max_digits=12, decimal_places=2, default=0)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("GRN item")
        verbose_name_plural = _("GRN items")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.drug} · {self.batch_no}"

    @property
    def line_total(self) -> Decimal:
        return _dec(self.purchase_price) * self.quantity


# ---------------------------------------------------------------------------
# Dispensing
# ---------------------------------------------------------------------------
class DispenseRecord(SoftDeleteModel):
    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.PROTECT,
        related_name="dispense_records",
        verbose_name=_("prescription"),
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="dispense_records",
        verbose_name=_("patient"),
    )
    store = models.ForeignKey(
        PharmacyStore,
        on_delete=models.PROTECT,
        related_name="dispense_records",
        verbose_name=_("store"),
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=DispenseStatus.choices,
        default=DispenseStatus.COMPLETED,
        db_index=True,
    )
    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dispense_records",
        verbose_name=_("dispensed by"),
    )
    dispensed_at = models.DateTimeField(
        _("dispensed at"), default=timezone.now, db_index=True
    )
    total_amount = models.DecimalField(
        _("total amount"), max_digits=12, decimal_places=2, default=0
    )
    is_billed = models.BooleanField(_("billed"), default=False, db_index=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("dispense record")
        verbose_name_plural = _("dispense records")
        ordering = ["-dispensed_at", "-id"]

    def __str__(self) -> str:
        return f"Dispense #{self.pk} · {self.patient}"


class DispenseItem(TimeStampedModel):
    dispense = models.ForeignKey(
        DispenseRecord,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("dispense"),
    )
    prescription_item = models.ForeignKey(
        PrescriptionItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dispense_items",
        verbose_name=_("prescription item"),
    )
    drug = models.ForeignKey(
        Drug,
        on_delete=models.PROTECT,
        related_name="dispense_items",
        verbose_name=_("drug"),
    )
    batch = models.ForeignKey(
        StockBatch,
        on_delete=models.PROTECT,
        related_name="dispense_items",
        verbose_name=_("batch"),
    )
    quantity = models.PositiveIntegerField(_("quantity"), default=1)
    unit_price = models.DecimalField(
        _("unit price"), max_digits=12, decimal_places=2, default=0
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("dispense item")
        verbose_name_plural = _("dispense items")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.drug} × {self.quantity}"

    @property
    def total(self) -> Decimal:
        return _dec(self.unit_price) * self.quantity
