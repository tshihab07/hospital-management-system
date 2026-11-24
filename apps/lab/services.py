"""Write operations for the Laboratory & Radiology module (atomic + audit).

The workflow mirrors the spec's exit criteria: order → sample → result →
verify → report → release. Verification freezes a result/report; corrections
after that are appended as :class:`LabResultAddendum` rows.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.emr.models import LabOrder, OrderStatus
from core.audit import AuditAction, log_action, model_to_dict_safe

from .models import (LabCharge, LabReport, LabResult, LabResultAddendum,
                     LabSample, LabSequence, RadiologyRecord, RadiologyStatus,
                     ReportStatus, ResultFlag, SampleStatus, SequenceKind)

_NUM = r"[-+]?\d+(?:\.\d+)?"


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _next_number(kind: SequenceKind) -> str:
    now = timezone.localtime()
    seq, _ = LabSequence.objects.select_for_update().get_or_create(
        year=now.year, kind=kind
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    width = int(settings.IHMS.get("LAB_NUMBER_WIDTH", 5))
    if kind == SequenceKind.SAMPLE:
        prefix = settings.IHMS.get("LAB_SAMPLE_PREFIX", "SMP")
        return f"{prefix}-{now:%Y%m%d}-{seq.last_number:0{width}d}"
    if kind == SequenceKind.REPORT:
        prefix = settings.IHMS.get("LAB_REPORT_PREFIX", "LR")
        return f"{prefix}-{now.year}-{seq.last_number:0{width}d}"
    return f"RR-{now.year}-{seq.last_number:0{width}d}"


def parse_reference_range(text: str):
    """Parse a reference range string into ``(low, high)`` (either may be None)."""
    if not text:
        return None
    text = text.strip()
    m = re.search(rf"({_NUM})\s*[-–]\s*({_NUM})", text)
    if m:
        return _to_decimal(m.group(1)), _to_decimal(m.group(2))
    m = re.search(r"<\s*=?\s*(" + _NUM + ")", text)
    if m:
        return None, _to_decimal(m.group(1))
    m = re.search(r">\s*=?\s*(" + _NUM + ")", text)
    if m:
        return _to_decimal(m.group(1)), None
    return None


def compute_flag(reference_range: str, value) -> str:
    """Return a :class:`ResultFlag` for a numeric value against a range."""
    bounds = parse_reference_range(reference_range)
    numeric = _to_decimal(value)
    if bounds is None or numeric is None:
        return ResultFlag.NORMAL
    low, high = bounds
    if low is not None and numeric < low:
        return (
            ResultFlag.CRITICAL_LOW
            if low and numeric < low * Decimal("0.7")
            else ResultFlag.LOW
        )
    if high is not None and numeric > high:
        return (
            ResultFlag.CRITICAL_HIGH
            if high and numeric > high * Decimal("1.3")
            else ResultFlag.HIGH
        )
    return ResultFlag.NORMAL


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------
@transaction.atomic
def ensure_sample(*, order: LabOrder, actor=None, request=None) -> LabSample:
    sample = getattr(order, "sample", None)
    if sample is not None:
        return sample
    first_test = order.items.select_related("test").first()
    sample = LabSample.objects.create(
        order=order,
        barcode=_next_number(SequenceKind.SAMPLE),
        sample_type=getattr(first_test.test, "sample_type", "") if first_test else "",
    )
    log_action(
        AuditAction.CREATE,
        instance=sample,
        changes=model_to_dict_safe(sample),
        user=actor,
        request=request,
    )
    return sample


@transaction.atomic
def collect_sample(*, sample: LabSample, actor=None, request=None) -> LabSample:
    sample.status = SampleStatus.COLLECTED
    sample.collected_at = timezone.now()
    sample.collected_by = actor if getattr(actor, "pk", None) else None
    sample.save()
    order = sample.order
    if order.status == OrderStatus.ORDERED:
        order.status = OrderStatus.IN_PROGRESS
        order.save(update_fields=["status", "updated_at"])
    post_lab_charges(order=order, actor=actor, request=request)
    log_action(
        AuditAction.UPDATE,
        instance=sample,
        changes=model_to_dict_safe(sample),
        user=actor,
        request=request,
    )
    return sample


@transaction.atomic
def receive_sample(*, sample: LabSample, actor=None, request=None) -> LabSample:
    sample.status = SampleStatus.IN_PROCESS
    sample.received_at = timezone.now()
    sample.save(update_fields=["status", "received_at", "updated_at"])
    return sample


@transaction.atomic
def reject_sample(
    *, sample: LabSample, reason: str = "", actor=None, request=None
) -> LabSample:
    sample.status = SampleStatus.REJECTED
    sample.rejected_reason = reason
    sample.save(update_fields=["status", "rejected_reason", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=sample,
        changes=model_to_dict_safe(sample),
        user=actor,
        request=request,
    )
    return sample


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@transaction.atomic
def enter_result(
    *,
    order_item,
    value: str,
    flag: str | None = None,
    remarks: str = "",
    actor=None,
    request=None,
) -> LabResult:
    test = order_item.test
    result, _created = LabResult.objects.get_or_create(
        order=order_item.order,
        order_item=order_item,
        defaults={"test": test},
    )
    if result.is_verified:
        raise ValueError(_("Verified results can only be changed via an addendum."))
    result.test = test
    result.value = value
    result.unit = test.unit
    result.reference_range = test.reference_range
    result.flag = flag or compute_flag(test.reference_range, value)
    result.remarks = remarks
    result.entered_by = actor if getattr(actor, "pk", None) else None
    result.entered_at = timezone.now()
    result.save()
    log_action(
        AuditAction.UPDATE,
        instance=result,
        changes=model_to_dict_safe(result),
        user=actor,
        request=request,
    )
    return result


@transaction.atomic
def verify_result(*, result: LabResult, actor=None, request=None) -> LabResult:
    result.is_verified = True
    result.verified_by = actor if getattr(actor, "pk", None) else None
    result.verified_at = timezone.now()
    result.save(
        update_fields=["is_verified", "verified_by", "verified_at", "updated_at"]
    )
    log_action(
        AuditAction.UPDATE,
        instance=result,
        changes=model_to_dict_safe(result),
        user=actor,
        request=request,
    )
    _maybe_verify_report(result.order, actor=actor, request=request)
    return result


@transaction.atomic
def add_result_addendum(
    *, result: LabResult, text: str, actor=None, request=None
) -> LabResultAddendum:
    addendum = LabResultAddendum.objects.create(
        result=result,
        text=text,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    log_action(
        AuditAction.CREATE,
        instance=addendum,
        changes=model_to_dict_safe(addendum),
        user=actor,
        request=request,
    )
    return addendum


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
@transaction.atomic
def _maybe_verify_report(
    order: LabOrder, *, actor=None, request=None
) -> LabReport | None:
    results = list(order.results.all())
    if not results or not all(r.is_verified for r in results):
        return None
    report = getattr(order, "report", None)
    if report is None:
        report = LabReport.objects.create(
            order=order, report_no=_next_number(SequenceKind.REPORT)
        )
    if report.status == ReportStatus.DRAFT:
        report.status = ReportStatus.VERIFIED
        report.verified_by = actor if getattr(actor, "pk", None) else None
        report.verified_at = timezone.now()
        report.save()
    order.status = OrderStatus.COMPLETED
    order.save(update_fields=["status", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=report,
        changes=model_to_dict_safe(report),
        user=actor,
        request=request,
    )
    return report


@transaction.atomic
def verify_report(*, report: LabReport, actor=None, request=None) -> LabReport:
    if report.status == ReportStatus.RELEASED:
        raise ValueError(_("A released report cannot be re-verified."))
    report.status = ReportStatus.VERIFIED
    report.verified_by = actor if getattr(actor, "pk", None) else None
    report.verified_at = timezone.now()
    report.save()
    log_action(
        AuditAction.UPDATE,
        instance=report,
        changes=model_to_dict_safe(report),
        user=actor,
        request=request,
    )
    return report


@transaction.atomic
def release_report(*, report: LabReport, actor=None, request=None) -> LabReport:
    if not report.is_verified:
        raise ValueError(_("Verify the report before releasing it."))
    report.is_released = True
    report.released_at = timezone.now()
    report.released_by = actor if getattr(actor, "pk", None) else None
    report.status = ReportStatus.RELEASED
    report.save()
    log_action(
        AuditAction.UPDATE,
        instance=report,
        changes=model_to_dict_safe(report),
        user=actor,
        request=request,
    )
    return report


# ---------------------------------------------------------------------------
# Charges
# ---------------------------------------------------------------------------
@transaction.atomic
def post_lab_charges(*, order: LabOrder, actor=None, request=None) -> list[LabCharge]:
    charges = []
    for item in order.items.select_related("test"):
        charge, created = LabCharge.objects.get_or_create(
            order=order, test=item.test, defaults={"amount": item.test.price}
        )
        if created:
            charges.append(charge)
    if charges:
        log_action(
            AuditAction.CREATE,
            instance=order,
            changes={"lab_charges_posted": len(charges)},
            user=actor,
            request=request,
        )
    return charges


# ---------------------------------------------------------------------------
# Radiology
# ---------------------------------------------------------------------------
@transaction.atomic
def ensure_radiology_record(*, order, actor=None, request=None) -> RadiologyRecord:
    record = getattr(order, "record", None)
    if record is not None:
        return record
    record = RadiologyRecord.objects.create(
        order=order, report_no=_next_number(SequenceKind.RADIOLOGY)
    )
    log_action(
        AuditAction.CREATE,
        instance=record,
        changes=model_to_dict_safe(record),
        user=actor,
        request=request,
    )
    return record


@transaction.atomic
def schedule_radiology(
    *, record: RadiologyRecord, scheduled_at, actor=None, request=None
) -> RadiologyRecord:
    record.scheduled_at = scheduled_at
    record.status = RadiologyStatus.SCHEDULED
    record.save(update_fields=["scheduled_at", "status", "updated_at"])
    return record


@transaction.atomic
def record_radiology_report(
    *,
    record: RadiologyRecord,
    findings: str = "",
    impression: str = "",
    radiologist=None,
    attachment=None,
    actor=None,
    request=None,
) -> RadiologyRecord:
    record.findings = findings
    record.impression = impression
    if radiologist is not None:
        record.radiologist = radiologist
    if attachment is not None:
        record.attachment = attachment
    record.status = RadiologyStatus.REPORTED
    record.performed_at = record.performed_at or timezone.now()
    record.performed_by = actor if getattr(actor, "pk", None) else record.performed_by
    record.save()
    order = record.order
    if order.status != OrderStatus.COMPLETED:
        order.status = OrderStatus.COMPLETED
        order.save(update_fields=["status", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=record,
        changes=model_to_dict_safe(record),
        user=actor,
        request=request,
    )
    return record


@transaction.atomic
def verify_radiology(
    *, record: RadiologyRecord, actor=None, request=None
) -> RadiologyRecord:
    record.verified_by = actor if getattr(actor, "pk", None) else None
    record.verified_at = timezone.now()
    record.save(update_fields=["verified_by", "verified_at", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=record,
        changes=model_to_dict_safe(record),
        user=actor,
        request=request,
    )
    return record


@transaction.atomic
def release_radiology(
    *, record: RadiologyRecord, actor=None, request=None
) -> RadiologyRecord:
    if record.verified_at is None:
        raise ValueError(_("Verify the report before releasing it."))
    record.is_released = True
    record.save(update_fields=["is_released", "updated_at"])
    return record
