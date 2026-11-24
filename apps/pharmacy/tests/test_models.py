"""Model-level tests for the Pharmacy & Inventory module."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from ..models import POStatus, PurchaseOrder, PurchaseOrderItem, StockBatch
from . import factories

pytestmark = pytest.mark.django_db


def test_batch_expiry_flags():
    today = timezone.localdate()
    expired = factories.make_batch(quantity=5, expiry_date=today - timedelta(days=1))
    fresh = factories.make_batch(quantity=5, expiry_date=today + timedelta(days=10))
    no_expiry = factories.make_batch(quantity=5, expiry_date=None)

    assert expired.is_expired is True
    assert fresh.is_expired is False
    assert no_expiry.is_expired is False
    assert fresh.days_to_expiry == 10
    assert no_expiry.days_to_expiry is None


def test_batch_stock_value():
    batch = factories.make_batch(quantity=20, purchase_price="2.50")
    assert batch.stock_value == Decimal("50.00")


def test_po_item_line_total_and_recompute():
    po = PurchaseOrder.objects.create(
        po_number="PO-TEST-1",
        vendor=factories.make_vendor(),
        store=factories.make_store(),
        status=POStatus.DRAFT,
    )
    drug = factories.make_drug()
    PurchaseOrderItem.objects.create(
        purchase_order=po, drug=drug, quantity_ordered=4, unit_price="12.50"
    )
    PurchaseOrderItem.objects.create(
        purchase_order=po,
        drug=factories.make_drug(),
        quantity_ordered=2,
        unit_price="5.00",
    )
    assert po.recompute_total() == Decimal("60.00")
    po.refresh_from_db()
    assert po.total_amount == Decimal("60.00")


def test_batch_unique_per_store_drug():
    store = factories.make_store()
    drug = factories.make_drug()
    factories.make_batch(store=store, drug=drug, batch_no="X1")

    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        StockBatch.objects.create(store=store, drug=drug, batch_no="X1", quantity=1)
