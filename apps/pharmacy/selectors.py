"""Read-only query helpers for the Pharmacy & Inventory module."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q, Sum
from django.utils import timezone

from .models import (DispenseRecord, GoodsReceiptNote, PharmacyStore, POStatus,
                     PurchaseOrder, PurchaseRequisition, RequisitionStatus,
                     StockBatch, StockMovement, StoreType, Vendor)


def drug_options():
    from apps.masters.models import Drug

    return Drug.objects.order_by("generic_name")


def store_list(*, active_only: bool = True):
    qs = PharmacyStore.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("name")


def central_store():
    return (
        PharmacyStore.objects.filter(store_type=StoreType.CENTRAL, is_active=True)
        .order_by("id")
        .first()
    )


def vendor_list(*, active_only: bool = True):
    qs = Vendor.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("name")


def stock_list(
    *,
    store: PharmacyStore | None = None,
    drug=None,
    search: str = "",
    include_expired: bool = True,
    with_stock: bool = False,
):
    qs = StockBatch.objects.select_related("store", "drug")
    if store is not None:
        qs = qs.filter(store=store)
    if drug is not None:
        qs = qs.filter(drug=drug)
    if with_stock:
        qs = qs.filter(quantity__gt=0)
    if not include_expired:
        qs = qs.filter(
            Q(expiry_date__isnull=True) | Q(expiry_date__gte=timezone.localdate())
        )
    if search:
        qs = qs.filter(
            Q(drug__generic_name__icontains=search)
            | Q(drug__brand_name__icontains=search)
            | Q(batch_no__icontains=search)
        )
    return qs.order_by("drug__generic_name", "expiry_date", "id")


def expiring_batches(days: int):
    today = timezone.localdate()
    return (
        StockBatch.objects.select_related("store", "drug")
        .filter(
            quantity__gt=0,
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=days),
        )
        .order_by("expiry_date", "id")
    )


def expired_batches(*, store: PharmacyStore | None = None):
    qs = (
        StockBatch.objects.select_related("store", "drug")
        .filter(quantity__gt=0, expiry_date__lt=timezone.localdate())
        .order_by("expiry_date", "id")
    )
    if store is not None:
        qs = qs.filter(store=store)
    return qs


def low_stock_drugs(*, store: PharmacyStore | None = None):
    """Drugs whose available (non-expired) quantity is below reorder level."""
    today = timezone.localdate()
    qs = StockBatch.objects.filter(is_active=True, quantity__gt=0).filter(
        Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)
    )
    if store is not None:
        qs = qs.filter(store=store)
    rows = (
        qs.values(
            "drug__id",
            "drug__generic_name",
            "drug__brand_name",
            "drug__reorder_level",
            "drug__unit",
        )
        .annotate(available=Sum("quantity"))
        .order_by("drug__generic_name")
    )
    result = []
    for row in rows:
        reorder_level = row["drug__reorder_level"] or 0
        if row["available"] < reorder_level:
            result.append(
                {
                    "drug_id": row["drug__id"],
                    "name": row["drug__generic_name"],
                    "brand": row["drug__brand_name"],
                    "unit": row["drug__unit"],
                    "available": row["available"],
                    "reorder_level": reorder_level,
                }
            )
    return result


def dispense_list(*, store: PharmacyStore | None = None, patient=None, billed=None):
    qs = DispenseRecord.objects.select_related(
        "patient", "store", "prescription", "dispensed_by"
    )
    if store is not None:
        qs = qs.filter(store=store)
    if patient is not None:
        qs = qs.filter(patient=patient)
    if billed is not None:
        qs = qs.filter(is_billed=billed)
    return qs.order_by("-dispensed_at", "-id")


def unbilled_dispenses():
    return DispenseRecord.objects.filter(is_billed=False).order_by("dispensed_at")


def requisition_list(*, status: str = ""):
    qs = PurchaseRequisition.objects.select_related("store", "requested_by")
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


def purchase_order_list(*, status: str = "", store=None):
    qs = PurchaseOrder.objects.select_related("vendor", "store")
    if status:
        qs = qs.filter(status=status)
    if store is not None:
        qs = qs.filter(store=store)
    return qs.order_by("-order_date", "-id")


def open_purchase_orders():
    return PurchaseOrder.objects.filter(
        status__in=[POStatus.DRAFT, POStatus.SENT, POStatus.PARTIAL]
    ).order_by("order_date")


def grn_list(*, store=None):
    qs = GoodsReceiptNote.objects.select_related("vendor", "store", "purchase_order")
    if store is not None:
        qs = qs.filter(store=store)
    return qs.order_by("-received_date", "-id")


def stock_movements(*, batch=None, drug=None, store=None, movement_type: str = ""):
    qs = StockMovement.objects.select_related(
        "batch", "batch__drug", "batch__store", "moved_by"
    )
    if batch is not None:
        qs = qs.filter(batch=batch)
    if drug is not None:
        qs = qs.filter(batch__drug=drug)
    if store is not None:
        qs = qs.filter(batch__store=store)
    if movement_type:
        qs = qs.filter(movement_type=movement_type)
    return qs.order_by("-moved_at", "-id")


def pharmacy_dashboard(
    *, store: PharmacyStore | None = None, expiry_days: int = 30
) -> dict:
    from django.conf import settings

    days = expiry_days or int(settings.IHMS.get("PHARMACY_EXPIRY_ALERT_DAYS", 30))
    today = timezone.localdate()
    stock = StockBatch.objects.filter(quantity__gt=0, is_active=True)
    if store is not None:
        stock = stock.filter(store=store)
    return {
        "store": store,
        "store_count": PharmacyStore.objects.filter(is_active=True).count(),
        "batch_count": stock.count(),
        "expiring_soon": stock.filter(
            expiry_date__gte=today, expiry_date__lte=today + timedelta(days=days)
        ).count(),
        "expired": stock.filter(expiry_date__lt=today).count(),
        "low_stock": len(low_stock_drugs(store=store)),
        "open_pos": open_purchase_orders().count(),
        "pending_requisitions": PurchaseRequisition.objects.filter(
            status=RequisitionStatus.SUBMITTED
        ).count(),
        "dispensed_today": DispenseRecord.objects.filter(
            dispensed_at__date=today
        ).count(),
    }
