"""Read-only queries for the Billing & Payments module (RULES §2.2)."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    Advance,
    Bill,
    BillItem,
    BillStatus,
    CreditNote,
    Payment,
    Refund,
    ServicePackage,
    _dec,
)


def bill_list(*, status: str = "", bill_type: str = "", search: str = ""):
    """Filtered bill queryset for the billing worklist."""
    qs = Bill.objects.select_related("patient", "admission").prefetch_related("items")
    if status:
        qs = qs.filter(status=status)
    if bill_type:
        qs = qs.filter(bill_type=bill_type)
    if search:
        qs = qs.filter(
            Q(bill_no__icontains=search)
            | Q(patient__full_name_en__icontains=search)
            | Q(patient__uhid__icontains=search)
        )
    return qs


def open_bills():
    """Bills that still carry an outstanding balance."""
    return (
        Bill.objects.exclude(status=BillStatus.CANCELLED)
        .exclude(status=BillStatus.PAID)
        .select_related("patient")
        .order_by("-created_at")
    )


def payment_list(*, method: str = "", search: str = ""):
    """Filtered payment queryset."""
    qs = Payment.objects.select_related("bill__patient", "received_by")
    if method:
        qs = qs.filter(method=method)
    if search:
        qs = qs.filter(
            Q(bill__bill_no__icontains=search)
            | Q(txn_ref__icontains=search)
            | Q(bill__patient__full_name_en__icontains=search)
        )
    return qs


def refund_list(*, status: str = ""):
    qs = Refund.objects.select_related("bill__patient", "payment")
    if status:
        qs = qs.filter(status=status)
    return qs


def advances(patient=None):
    qs = Advance.objects.select_related("patient", "admission")
    if patient is not None:
        qs = qs.filter(patient=patient)
    return qs.order_by("-paid_at")


def bill_detail(bill: Bill):
    """Return the bill with its lines and payments fully loaded."""
    return (
        Bill.objects.select_related(
            "patient", "admission", "created_by", "discount_approved_by"
        )
        .prefetch_related("items", "payments__receipt", "refunds")
        .get(pk=bill.pk)
    )


def patient_ledger(patient):
    """Aggregate every money movement for a patient into a ledger view."""
    bills = (
        Bill.objects.filter(patient=patient)
        .exclude(status=BillStatus.CANCELLED)
        .prefetch_related("items", "payments")
        .order_by("created_at")
    )
    payments = (
        Payment.objects.filter(bill__patient=patient)
        .select_related("bill")
        .order_by("paid_at")
    )
    advance_rows = Advance.objects.filter(patient=patient).order_by("paid_at")
    refund_rows = Refund.objects.filter(bill__patient=patient).order_by("created_at")
    charged = _dec(bills.aggregate(t=Coalesce(Sum("total"), Decimal("0")))["t"])
    paid = _dec(payments.aggregate(t=Coalesce(Sum("amount"), Decimal("0")))["t"])
    advanced = _dec(
        advance_rows.aggregate(t=Coalesce(Sum("amount"), Decimal("0")))["t"]
    )
    refunded = _dec(
        Refund.objects.filter(bill__patient=patient, status="processed").aggregate(
            t=Coalesce(Sum("amount"), Decimal("0"))
        )["t"]
    )
    return {
        "bills": bills,
        "payments": payments,
        "advances": advance_rows,
        "refunds": refund_rows,
        "total_charged": charged,
        "total_paid": paid,
        "total_advanced": advanced,
        "total_refunded": refunded,
        "outstanding": charged - paid,
    }


def billing_dashboard():
    """Headline KPIs for the billing dashboard."""
    today = timezone.localdate()
    bills = Bill.objects.exclude(status=BillStatus.CANCELLED)
    today_payments = Payment.objects.filter(paid_at__date=today)
    open_bills = bills.exclude(status=BillStatus.PAID).only("total", "paid_amount")
    return {
        "bills_total": bills.count(),
        "open_bills": open_bills.count(),
        "paid_bills": bills.filter(status=BillStatus.PAID).count(),
        "pending_discounts": bills.filter(discount_status="pending").count(),
        "today_collected": _dec(
            today_payments.aggregate(t=Coalesce(Sum("amount"), Decimal("0")))["t"]
        ),
        "outstanding_total": sum((b.due_amount for b in open_bills), Decimal("0")),
        "payments_today": today_payments.count(),
        "pending_refunds": Refund.objects.filter(status="requested").count(),
    }


def unbilled_source_counts():
    """Counts of clinical charges still waiting to be posted (dashboard aid)."""
    from apps.lab.models import LabCharge
    from apps.pharmacy.models import DispenseRecord

    return {
        "lab": LabCharge.objects.filter(is_billed=False).count(),
        "pharmacy": DispenseRecord.objects.filter(is_billed=False).count(),
    }


def bill_items_by_type(bill: Bill):
    return (
        BillItem.objects.filter(bill=bill)
        .values("item_type")
        .annotate(lines=Count("id"), total=Sum("amount"))
        .order_by("item_type")
    )


def daily_collection(*, day=None, method: str = ""):
    """Daily collection report: per-channel totals for a single day.

    Returns ``{"day", "rows", "grand_total", "count"}`` where each row is a
    ``{method, count, total}`` dict (RULES Phase 12: *"Daily collection
    report"*).
    """
    day = day or timezone.localdate()
    payments = Payment.objects.filter(paid_at__date=day)
    if method:
        payments = payments.filter(method=method)
    rows = list(
        payments.values("method")
        .annotate(count=Count("id"), total=Coalesce(Sum("amount"), Decimal("0")))
        .order_by("method")
    )
    grand_total = sum((_dec(r["total"]) for r in rows), Decimal("0"))
    return {
        "day": day,
        "rows": rows,
        "grand_total": grand_total,
        "count": sum(r["count"] for r in rows),
    }


def collection_range(*, start, end, method: str = ""):
    """Per-day collection totals across a date range (monthly reports)."""
    payments = Payment.objects.filter(paid_at__date__gte=start, paid_at__date__lte=end)
    if method:
        payments = payments.filter(method=method)
    return (
        payments.values("paid_at__date")
        .annotate(count=Count("id"), total=Coalesce(Sum("amount"), Decimal("0")))
        .order_by("paid_at__date")
    )


def credit_note_list(*, status: str = "", search: str = ""):
    qs = CreditNote.objects.select_related("bill__patient", "created_by")
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(
            Q(note_no__icontains=search)
            | Q(bill__bill_no__icontains=search)
            | Q(bill__patient__full_name_en__icontains=search)
        )
    return qs


def package_list(*, active_only: bool = True):
    qs = ServicePackage.objects.prefetch_related("components")
    if active_only:
        qs = qs.filter(is_active=True)
    return qs

