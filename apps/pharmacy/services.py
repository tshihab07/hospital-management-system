"""Write operations for the Pharmacy & Inventory module (atomic + audit).

FIFO dispensing, expiry blocking, stock ledger movements, PR → PO → GRN and
stock transfer/return/adjustment all live here.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting import integration as accounting_hooks
from apps.masters.models import Drug
from core.audit import AuditAction, log_action, model_to_dict_safe

from .models import (DispenseItem, DispenseRecord, DispenseStatus,
                     GoodsReceiptNote, GRNItem, MovementType, PharmacySequence,
                     PharmacyStore, POStatus, PurchaseOrder, PurchaseOrderItem,
                     PurchaseRequisition, PurchaseRequisitionItem,
                     RequisitionStatus, SequenceKind, StockBatch,
                     StockMovement)


# ---------------------------------------------------------------------------
# Sequence helper
# ---------------------------------------------------------------------------
def _next_number(kind: SequenceKind) -> str:
    now = timezone.localtime()
    seq, _ = PharmacySequence.objects.select_for_update().get_or_create(
        year=now.year, kind=kind
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    width = int(settings.IHMS.get("PHARMACY_NUMBER_WIDTH", 5))
    prefix = {
        SequenceKind.REQUISITION: settings.IHMS.get("PHARMACY_PR_PREFIX", "PR"),
        SequenceKind.PURCHASE_ORDER: settings.IHMS.get("PHARMACY_PO_PREFIX", "PO"),
        SequenceKind.GRN: settings.IHMS.get("PHARMACY_GRN_PREFIX", "GRN"),
    }[kind]
    return f"{prefix}-{now.year}-{seq.last_number:0{width}d}"


def _actor_id(actor):
    return actor if getattr(actor, "pk", None) else None


# ---------------------------------------------------------------------------
# Stock ledger
# ---------------------------------------------------------------------------
def _apply_movement(
    *,
    batch: StockBatch,
    delta: int,
    movement_type: str,
    reference: str = "",
    actor=None,
    request=None,
    notes: str = "",
) -> StockMovement:
    """Lock the batch, apply ``delta`` and append a :class:`StockMovement`."""
    locked = StockBatch.objects.select_for_update().get(pk=batch.pk)
    new_qty = locked.quantity + delta
    if new_qty < 0:
        raise ValueError(
            _("Insufficient stock in batch %(b)s.") % {"b": locked.batch_no}
        )
    locked.quantity = new_qty
    locked.save(update_fields=["quantity", "updated_at"])
    movement = StockMovement.objects.create(
        batch=locked,
        movement_type=movement_type,
        quantity=delta,
        balance_after=new_qty,
        reference=reference,
        moved_by=_actor_id(actor),
        notes=notes,
    )
    log_action(
        AuditAction.CREATE,
        instance=movement,
        changes=model_to_dict_safe(movement),
        user=actor,
        request=request,
    )
    return movement


@transaction.atomic
def add_stock_batch(
    *,
    store: PharmacyStore,
    drug: Drug,
    batch_no: str,
    quantity: int,
    expiry_date=None,
    purchase_price="0",
    mrp="0",
    actor=None,
    request=None,
    reference: str = "",
) -> StockBatch:
    """Create or increment a stock batch (a receipt movement is recorded)."""
    batch, created = StockBatch.objects.select_for_update().get_or_create(
        store=store,
        drug=drug,
        batch_no=batch_no,
        defaults={
            "expiry_date": expiry_date,
            "quantity": 0,
            "purchase_price": purchase_price,
            "mrp": mrp,
        },
    )
    if not created and purchase_price:
        batch.purchase_price = purchase_price
        batch.mrp = mrp or batch.mrp
        if expiry_date:
            batch.expiry_date = expiry_date
        batch.save(update_fields=["purchase_price", "mrp", "expiry_date", "updated_at"])
    if quantity:
        _apply_movement(
            batch=batch,
            delta=quantity,
            movement_type=MovementType.RECEIPT,
            reference=reference or f"RECEIPT {batch_no}",
            actor=actor,
            request=request,
        )
    return batch


@transaction.atomic
def adjust_stock(
    *, batch: StockBatch, new_quantity: int, reason: str, actor=None, request=None
) -> StockMovement:
    """Set the batch to ``new_quantity`` and record an adjustment movement."""
    if not reason:
        raise ValueError(_("A reason is required for a stock adjustment."))
    delta = int(new_quantity) - batch.quantity
    return _apply_movement(
        batch=batch,
        delta=delta,
        movement_type=MovementType.ADJUSTMENT,
        reference="ADJUSTMENT",
        actor=actor,
        request=request,
        notes=reason,
    )


@transaction.atomic
def return_to_vendor(
    *, batch: StockBatch, quantity: int, actor=None, request=None, notes: str = ""
) -> StockMovement:
    if quantity <= 0:
        raise ValueError(_("Return quantity must be positive."))
    return _apply_movement(
        batch=batch,
        delta=-int(quantity),
        movement_type=MovementType.RETURN,
        reference="RETURN-TO-VENDOR",
        actor=actor,
        request=request,
        notes=notes,
    )


def _fifo_batches(store: PharmacyStore, drug: Drug, *, exclude_expired: bool = True):
    """Available batches for ``drug`` in ``store`` ordered oldest-expiry first."""
    qs = StockBatch.objects.select_for_update().filter(
        store=store, drug=drug, quantity__gt=0, is_active=True
    )
    if exclude_expired:
        qs = qs.filter(
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=timezone.localdate())
        )
    return qs.order_by(F("expiry_date").asc(nulls_last=True), "id")


@transaction.atomic
def transfer_stock(
    *,
    from_store: PharmacyStore,
    to_store: PharmacyStore,
    drug: Drug,
    quantity: int,
    actor=None,
    request=None,
    notes: str = "",
) -> list[StockBatch]:
    """Move ``quantity`` of ``drug`` from one store to another using FIFO."""
    if quantity <= 0:
        raise ValueError(_("Transfer quantity must be positive."))
    if from_store.pk == to_store.pk:
        raise ValueError(_("Source and destination stores must differ."))
    remaining = int(quantity)
    received: list[StockBatch] = []
    for batch in _fifo_batches(from_store, drug):
        if remaining <= 0:
            break
        take = min(batch.quantity, remaining)
        _apply_movement(
            batch=batch,
            delta=-take,
            movement_type=MovementType.TRANSFER_OUT,
            reference=f"TRANSFER→{to_store.code}",
            actor=actor,
            request=request,
        )
        dest_batch = add_stock_batch(
            store=to_store,
            drug=drug,
            batch_no=batch.batch_no,
            quantity=take,
            expiry_date=batch.expiry_date,
            purchase_price=batch.purchase_price,
            mrp=batch.mrp,
            actor=actor,
            request=request,
            reference=f"TRANSFER←{from_store.code}",
        )
        # Reclassify destination movement as transfer_in.
        last = dest_batch.movements.order_by("-id").first()
        if last is not None:
            last.movement_type = MovementType.TRANSFER_IN
            last.save(update_fields=["movement_type", "updated_at"])
        received.append(dest_batch)
        remaining -= take
    if remaining > 0:
        raise ValueError(
            _("Insufficient stock: %(n)s unit(s) short.") % {"n": remaining}
        )
    return received


# ---------------------------------------------------------------------------
# Dispensing (FIFO)
# ---------------------------------------------------------------------------
@transaction.atomic
def dispense_prescription(
    *,
    prescription,
    store: PharmacyStore,
    quantities: dict | None = None,
    actor=None,
    request=None,
    notes: str = "",
) -> DispenseRecord:
    """Dispense a prescription from ``store`` using FIFO across batches.

    ``quantities`` optionally maps ``prescription_item.pk`` → quantity to
    dispense (defaults to 1 per line). Expired batches are never selected.
    """
    items = list(prescription.items.select_related("drug"))
    if not items:
        raise ValueError(_("This prescription has no drugs to dispense."))
    quantities = quantities or {}

    record = DispenseRecord.objects.create(
        prescription=prescription,
        patient=prescription.patient,
        store=store,
        status=DispenseStatus.COMPLETED,
        dispensed_by=_actor_id(actor),
        notes=notes,
    )
    total = Decimal("0")
    for item in items:
        needed = int(quantities.get(item.pk, 1) or 1)
        if needed <= 0:
            continue
        remaining = needed
        batches = list(_fifo_batches(store, item.drug))
        if sum(b.quantity for b in batches) < remaining:
            raise ValueError(
                _("Not enough stock for %(drug)s (need %(n)s).")
                % {"drug": item.drug, "n": needed}
            )
        for batch in batches:
            if remaining <= 0:
                break
            take = min(batch.quantity, remaining)
            unit_price = Decimal(str(batch.mrp or item.drug.unit_price or "0"))
            DispenseItem.objects.create(
                dispense=record,
                prescription_item=item,
                drug=item.drug,
                batch=batch,
                quantity=take,
                unit_price=unit_price,
            )
            _apply_movement(
                batch=batch,
                delta=-take,
                movement_type=MovementType.DISPENSE,
                reference=f"DISPENSE#{record.pk}",
                actor=actor,
                request=request,
            )
            total += unit_price * take
            remaining -= take

    record.total_amount = total
    record.save(update_fields=["total_amount", "updated_at"])
    log_action(
        AuditAction.CREATE,
        instance=record,
        changes=model_to_dict_safe(record),
        user=actor,
        request=request,
    )
    return record


# ---------------------------------------------------------------------------
# Requisition → PO
# ---------------------------------------------------------------------------
@transaction.atomic
def create_requisition(
    *,
    store: PharmacyStore,
    items: list[dict],
    needed_by=None,
    actor=None,
    request=None,
    notes: str = "",
) -> PurchaseRequisition:
    if not items:
        raise ValueError(_("A requisition needs at least one item."))
    requisition = PurchaseRequisition.objects.create(
        pr_number=_next_number(SequenceKind.REQUISITION),
        store=store,
        requested_by=_actor_id(actor),
        needed_by=needed_by,
        notes=notes,
    )
    for row in items:
        PurchaseRequisitionItem.objects.create(requisition=requisition, **row)
    log_action(
        AuditAction.CREATE,
        instance=requisition,
        changes=model_to_dict_safe(requisition),
        user=actor,
        request=request,
    )
    return requisition


@transaction.atomic
def set_requisition_status(
    *, requisition: PurchaseRequisition, status: str, actor=None, request=None
) -> PurchaseRequisition:
    requisition.status = status
    requisition.save(update_fields=["status", "updated_at"])
    return requisition


@transaction.atomic
def convert_requisition_to_po(
    *, requisition: PurchaseRequisition, vendor, actor=None, request=None
) -> PurchaseOrder:
    if requisition.status not in {
        RequisitionStatus.APPROVED,
        RequisitionStatus.SUBMITTED,
    }:
        raise ValueError(_("Only approved/submitted requisitions can be converted."))
    items = [
        {
            "drug": item.drug,
            "quantity_ordered": item.quantity,
            "unit_price": item.drug.unit_price,
        }
        for item in requisition.items.select_related("drug")
    ]
    po = create_purchase_order(
        vendor=vendor,
        store=requisition.store,
        items=items,
        requisition=requisition,
        actor=actor,
        request=request,
    )
    requisition.status = RequisitionStatus.CONVERTED
    requisition.save(update_fields=["status", "updated_at"])
    return po


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------
@transaction.atomic
def create_purchase_order(
    *,
    vendor,
    store: PharmacyStore,
    items: list[dict],
    requisition=None,
    actor=None,
    request=None,
    notes: str = "",
) -> PurchaseOrder:
    if not items:
        raise ValueError(_("A purchase order needs at least one item."))
    po = PurchaseOrder.objects.create(
        po_number=_next_number(SequenceKind.PURCHASE_ORDER),
        vendor=vendor,
        store=store,
        requisition=requisition,
        order_date=timezone.localdate(),
        notes=notes,
        created_by=_actor_id(actor),
    )
    for row in items:
        PurchaseOrderItem.objects.create(purchase_order=po, **row)
    po.recompute_total()
    log_action(
        AuditAction.CREATE,
        instance=po,
        changes=model_to_dict_safe(po),
        user=actor,
        request=request,
    )
    return po


@transaction.atomic
def set_purchase_order_status(
    *, purchase_order: PurchaseOrder, status: str, actor=None, request=None
) -> PurchaseOrder:
    if status not in POStatus.values:
        raise ValueError(_("Unknown purchase order status."))
    purchase_order.status = status
    purchase_order.save(update_fields=["status", "updated_at"])
    return purchase_order


# ---------------------------------------------------------------------------
# Goods receipt → stock
# ---------------------------------------------------------------------------
@transaction.atomic
def receive_grn(
    *,
    store: PharmacyStore,
    items: list[dict],
    purchase_order: PurchaseOrder | None = None,
    vendor=None,
    received_date=None,
    actor=None,
    request=None,
    notes: str = "",
) -> GoodsReceiptNote:
    """Create a GRN, push every line into stock and update the linked PO."""
    if not items:
        raise ValueError(_("A GRN needs at least one item."))
    if purchase_order is not None:
        vendor = vendor or purchase_order.vendor
        store = store or purchase_order.store
    if vendor is None:
        raise ValueError(_("A vendor is required."))

    grn = GoodsReceiptNote.objects.create(
        grn_number=_next_number(SequenceKind.GRN),
        purchase_order=purchase_order,
        vendor=vendor,
        store=store,
        received_date=received_date or timezone.localdate(),
        notes=notes,
        received_by=_actor_id(actor),
    )
    total = Decimal("0")
    for row in items:
        grn_item = GRNItem.objects.create(grn=grn, **row)
        add_stock_batch(
            store=store,
            drug=grn_item.drug,
            batch_no=grn_item.batch_no,
            quantity=grn_item.quantity,
            expiry_date=grn_item.expiry_date,
            purchase_price=grn_item.purchase_price,
            mrp=grn_item.mrp,
            actor=actor,
            request=request,
            reference=grn.grn_number,
        )
        total += grn_item.line_total
        if grn_item.po_item is not None:
            grn_item.po_item.quantity_received = (
                grn_item.po_item.quantity_received + grn_item.quantity
            )
            grn_item.po_item.save(update_fields=["quantity_received", "updated_at"])

    grn.total_amount = total
    grn.save(update_fields=["total_amount", "updated_at"])

    if purchase_order is not None:
        purchase_order.refresh_from_db()
        lines = list(purchase_order.items.all())
        if lines and all(line.is_fully_received for line in lines):
            purchase_order.status = POStatus.RECEIVED
        else:
            purchase_order.status = POStatus.PARTIAL
        purchase_order.save(update_fields=["status", "updated_at"])

    log_action(
        AuditAction.CREATE,
        instance=grn,
        changes=model_to_dict_safe(grn),
        user=actor,
        request=request,
    )
    accounting_hooks.on_grn_received(grn, actor=actor, request=request)
    return grn
