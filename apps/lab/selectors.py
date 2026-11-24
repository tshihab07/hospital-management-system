"""Read-only queries for the Laboratory & Radiology module."""

from __future__ import annotations

from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from apps.emr.models import (LabOrder, LabOrderItem, OrderStatus,
                             RadiologyOrder, RadiologyOrderItem)

from .models import LabResult, LabSample, RadiologyRecord, SampleStatus


def lab_order_list(*, q: str = "", status: str = "", priority: str = ""):
    qs = (
        LabOrder.objects.select_related("patient", "doctor")
        .prefetch_related(
            Prefetch("items", queryset=LabOrderItem.objects.select_related("test"))
        )
        .order_by("-ordered_at", "-id")
    )
    if q:
        qs = qs.filter(
            Q(patient__full_name_en__icontains=q)
            | Q(patient__uhid__icontains=q)
            | Q(id__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    return qs


def pending_lab_orders():
    return lab_order_list().filter(
        status__in=[OrderStatus.ORDERED, OrderStatus.IN_PROGRESS]
    )


def sample_list(*, q: str = "", status: str = ""):
    qs = LabSample.objects.select_related(
        "order", "order__patient", "collected_by"
    ).order_by("-created_at")
    if q:
        qs = qs.filter(
            Q(barcode__icontains=q)
            | Q(order__patient__full_name_en__icontains=q)
            | Q(order__patient__uhid__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    return qs


def result_list(*, q: str = "", status: str = "", flagged: bool = False):
    qs = LabResult.objects.select_related(
        "order", "order__patient", "order_item", "test", "verified_by"
    ).order_by("-created_at")
    if q:
        qs = qs.filter(
            Q(test__name__icontains=q)
            | Q(order__patient__full_name_en__icontains=q)
            | Q(order__patient__uhid__icontains=q)
        )
    if status == "pending":
        qs = qs.filter(is_verified=False)
    elif status == "verified":
        qs = qs.filter(is_verified=True)
    if flagged:
        qs = qs.exclude(flag="normal")
    return qs


def results_for_order(*, order: LabOrder):
    return (
        LabResult.objects.filter(order=order)
        .select_related("test", "verified_by")
        .prefetch_related("addenda")
        .order_by("id")
    )


def radiology_order_list(*, q: str = "", status: str = ""):
    qs = (
        RadiologyOrder.objects.select_related("patient", "doctor")
        .prefetch_related(
            Prefetch(
                "items", queryset=RadiologyOrderItem.objects.select_related("test")
            )
        )
        .order_by("-ordered_at", "-id")
    )
    if q:
        qs = qs.filter(
            Q(patient__full_name_en__icontains=q) | Q(patient__uhid__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    return qs


def radiology_record_list(*, q: str = "", status: str = ""):
    qs = RadiologyRecord.objects.select_related(
        "order", "order__patient", "radiologist", "verified_by"
    ).order_by("-created_at")
    if q:
        qs = qs.filter(
            Q(report_no__icontains=q)
            | Q(order__patient__full_name_en__icontains=q)
            | Q(order__patient__uhid__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    return qs


def lab_dashboard():
    """Counters for the lab landing page / nav badge."""
    return {
        "pending_orders": LabOrder.objects.filter(
            status__in=[OrderStatus.ORDERED, OrderStatus.IN_PROGRESS]
        ).count(),
        "pending_samples": LabSample.objects.filter(
            status__in=[SampleStatus.PENDING, SampleStatus.COLLECTED]
        ).count(),
        "pending_results": LabResult.objects.filter(is_verified=False).count(),
        "flagged_results": LabResult.objects.exclude(flag="normal")
        .filter(is_verified=False)
        .count(),
        "abnormal_today": LabResult.objects.exclude(flag="normal")
        .filter(entered_at__date=timezone.localdate())
        .count(),
        "pending_radiology": RadiologyOrder.objects.filter(
            status__in=[OrderStatus.ORDERED, OrderStatus.IN_PROGRESS]
        ).count(),
    }


def charges_for_order(*, order: LabOrder):
    return order.charges.select_related("test")


def unbilled_charges():
    return (
        LabOrder.objects.filter(charges__is_billed=False)
        .annotate(charge_count=Count("charges"))
        .distinct()
    )
