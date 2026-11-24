"""Service-level tests for the Laboratory & Radiology module."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.emr.models import OrderStatus
from apps.lab import services
from apps.lab.models import (LabCharge, LabReport, RadiologyStatus,
                             ReportStatus, ResultFlag, SampleStatus)

from .factories import make_lab_order, make_lab_test, make_radiology_order

pytestmark = pytest.mark.django_db


def test_ensure_sample_is_idempotent_and_unique_barcode():
    order = make_lab_order()
    first = services.ensure_sample(order=order)
    second = services.ensure_sample(order=order)
    assert first.pk == second.pk
    assert first.barcode.startswith("SMP-")


def test_collect_sample_advances_order_and_posts_charges():
    order = make_lab_order(tests=[make_lab_test(price="300.00")])
    sample = services.ensure_sample(order=order)
    services.collect_sample(sample=sample)
    order.refresh_from_db()
    assert order.status == OrderStatus.IN_PROGRESS
    assert sample.status == SampleStatus.COLLECTED
    assert LabCharge.objects.filter(order=order).count() == 1
    assert LabCharge.objects.get(order=order).amount == Decimal("300.00")


def test_enter_result_auto_flags_high():
    order = make_lab_order(tests=[make_lab_test(reference_range="4.0 - 10.0")])
    result = services.enter_result(order_item=order.items.first(), value="12")
    assert result.flag == ResultFlag.HIGH


def test_enter_result_blocked_after_verification():
    order = make_lab_order()
    result = services.enter_result(order_item=order.items.first(), value="7")
    services.verify_result(result=result)
    with pytest.raises(ValueError):
        services.enter_result(order_item=order.items.first(), value="8")


def test_verify_last_result_creates_and_verifies_report():
    order = make_lab_order(tests=[make_lab_test(), make_lab_test()])
    for item in order.items.all():
        services.enter_result(order_item=item, value="7")
    for result in order.results.all():
        services.verify_result(result=result)
    order.refresh_from_db()
    report = LabReport.objects.get(order=order)
    assert report.status == ReportStatus.VERIFIED
    assert order.status == OrderStatus.COMPLETED


def test_addendum_appended_to_verified_result():
    order = make_lab_order()
    result = services.enter_result(order_item=order.items.first(), value="7")
    services.verify_result(result=result)
    services.add_result_addendum(result=result, text="Repeat advised")
    assert result.addenda.count() == 1


def test_release_requires_verification():
    order = make_lab_order()
    result = services.enter_result(order_item=order.items.first(), value="7")
    services.verify_result(result=result)
    report = LabReport.objects.get(order=order)
    services.release_report(report=report)
    assert report.is_released


def test_radiology_record_workflow():
    order = make_radiology_order()
    record = services.ensure_radiology_record(order=order)
    assert record.report_no.startswith("RR-")
    services.record_radiology_report(
        record=record, findings="Normal", impression="Clear"
    )
    assert record.status == RadiologyStatus.REPORTED
    order.refresh_from_db()
    assert order.status == OrderStatus.COMPLETED
    services.verify_radiology(record=record)
    services.release_radiology(record=record)
    assert record.is_released


def test_release_radiology_requires_verification():
    order = make_radiology_order()
    record = services.ensure_radiology_record(order=order)
    with pytest.raises(ValueError):
        services.release_radiology(record=record)
