"""Model-level tests for the Laboratory & Radiology module."""

from __future__ import annotations

import pytest

from apps.lab.models import LabResult, ResultFlag

from .factories import make_lab_order, make_lab_test

pytestmark = pytest.mark.django_db


def test_lab_test_str_includes_code_and_name():
    test = make_lab_test(code="CBC", name="Complete Blood Count")
    assert "CBC" in str(test) and "Complete Blood Count" in str(test)


def test_lab_order_creates_items():
    order = make_lab_order(tests=[make_lab_test(), make_lab_test()])
    assert order.items.count() == 2


def test_result_is_abnormal_flag():
    order = make_lab_order()
    result = LabResult.objects.create(
        order=order,
        order_item=order.items.first(),
        test=order.items.first().test,
        value="15",
        flag=ResultFlag.HIGH,
    )
    assert result.is_abnormal


def test_parse_reference_range_variants():
    from apps.lab.services import parse_reference_range

    assert parse_reference_range("4.0 - 10.0") == (4, 10)
    assert parse_reference_range("<200")[1] == 200
    assert parse_reference_range(">40")[0] == 40
    assert parse_reference_range("") is None


def test_compute_flag_boundaries():
    from apps.lab.services import compute_flag

    assert compute_flag("4.0 - 10.0", "7") == ResultFlag.NORMAL
    assert compute_flag("4.0 - 10.0", "2") == ResultFlag.CRITICAL_LOW
    assert compute_flag("4.0 - 10.0", "12") == ResultFlag.HIGH
    assert compute_flag("4.0 - 10.0", "20") == ResultFlag.CRITICAL_HIGH
    assert compute_flag("", "anything") == ResultFlag.NORMAL
