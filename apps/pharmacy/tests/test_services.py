"""Service-level tests for the Pharmacy & Inventory module."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from .. import services
from ..models import (DispenseRecord, MovementType, POStatus,
                      RequisitionStatus, StockBatch, StockMovement)
from . import factories

pytestmark = pytest.mark.django_db


def _dispense(prescription, store, quantities=None, actor=None):
    return services.dispense_prescription(
        prescription=prescription, store=store, quantities=quantities, actor=actor
    )


def test_add_stock_batch_is_idempotent_per_batch():
    store = factories.make_store()
    drug = factories.make_drug()
    batch = services.add_stock_batch(
        store=store, drug=drug, batch_no="B1", quantity=10, reference="t"
    )
    services.add_stock_batch(
        store=store, drug=drug, batch_no="B1", quantity=5, reference="t2"
    )
    batch.refresh_from_db()
    assert batch.quantity == 15
    assert (
        StockMovement.objects.filter(
            batch=batch, movement_type=MovementType.RECEIPT
        ).count()
        == 2
    )


def test_dispense_uses_fifo_across_batches():
    store = factories.make_store()
    drug = factories.make_drug()
    today = timezone.localdate()
    old = factories.make_batch(
        store=store,
        drug=drug,
        batch_no="OLD",
        quantity=3,
        expiry_date=today + timedelta(days=5),
    )
    new = factories.make_batch(
        store=store,
        drug=drug,
        batch_no="NEW",
        quantity=10,
        expiry_date=today + timedelta(days=60),
    )
    prescription = factories.make_prescription(drugs=[drug])

    record = _dispense(
        prescription, store, quantities={prescription.items.first().pk: 5}
    )

    old.refresh_from_db()
    new.refresh_from_db()
    assert old.quantity == 0
    assert new.quantity == 8
    assert isinstance(record, DispenseRecord)
    assert record.items.count() == 2
    first = record.items.order_by("id").first()
    assert first.batch_id == old.id and first.quantity == 3
    assert record.total_amount == Decimal("25.00")
    assert (
        StockMovement.objects.filter(movement_type=MovementType.DISPENSE).count() == 2
    )


def test_dispense_blocks_expired_batches():
    store = factories.make_store()
    drug = factories.make_drug()
    factories.make_batch(
        store=store,
        drug=drug,
        batch_no="EXP",
        quantity=20,
        expiry_date=timezone.localdate() - timedelta(days=1),
    )
    prescription = factories.make_prescription(drugs=[drug])
    with pytest.raises(ValueError):
        _dispense(prescription, store, quantities={prescription.items.first().pk: 1})


def test_dispense_insufficient_stock_raises():
    store = factories.make_store()
    drug = factories.make_drug()
    factories.make_batch(
        store=store,
        drug=drug,
        quantity=2,
        expiry_date=timezone.localdate() + timedelta(days=30),
    )
    prescription = factories.make_prescription(drugs=[drug])
    with pytest.raises(ValueError):
        _dispense(prescription, store, quantities={prescription.items.first().pk: 5})


def test_transfer_stock_moves_between_stores():
    central = factories.make_store(store_type="central")
    ward = factories.make_store(store_type="sub_store")
    drug = factories.make_drug()
    factories.make_batch(
        store=central,
        drug=drug,
        batch_no="T1",
        quantity=10,
        expiry_date=timezone.localdate() + timedelta(days=30),
    )

    services.transfer_stock(from_store=central, to_store=ward, drug=drug, quantity=4)

    source = StockBatch.objects.get(store=central, drug=drug)
    dest = StockBatch.objects.get(store=ward, drug=drug)
    assert source.quantity == 6
    assert dest.quantity == 4
    assert dest.batch_no == "T1"
    assert (
        StockMovement.objects.filter(
            batch=dest, movement_type=MovementType.TRANSFER_IN
        ).count()
        == 1
    )


def test_transfer_same_store_raises():
    store = factories.make_store()
    drug = factories.make_drug()
    factories.make_batch(store=store, drug=drug, quantity=10)
    with pytest.raises(ValueError):
        services.transfer_stock(from_store=store, to_store=store, drug=drug, quantity=1)


def test_adjust_stock_requires_reason_and_records_delta():
    batch = factories.make_batch(quantity=10)
    with pytest.raises(ValueError):
        services.adjust_stock(batch=batch, new_quantity=7, reason="")
    movement = services.adjust_stock(batch=batch, new_quantity=7, reason="Damaged")
    batch.refresh_from_db()
    assert batch.quantity == 7
    assert movement.quantity == -3
    assert movement.balance_after == 7


def test_return_to_vendor_reduces_stock():
    batch = factories.make_batch(quantity=10)
    services.return_to_vendor(batch=batch, quantity=4, notes="Expired soon")
    batch.refresh_from_db()
    assert batch.quantity == 6
    assert (
        StockMovement.objects.filter(
            batch=batch, movement_type=MovementType.RETURN
        ).count()
        == 1
    )


def test_receive_grn_creates_stock_and_updates_po():
    vendor = factories.make_vendor()
    store = factories.make_store()
    drug = factories.make_drug()
    po = services.create_purchase_order(
        vendor=vendor,
        store=store,
        items=[{"drug_id": drug.id, "quantity_ordered": 10, "unit_price": "3.00"}],
    )
    po_item = po.items.first()

    grn = services.receive_grn(
        store=store,
        purchase_order=po,
        items=[
            {
                "po_item": po_item,
                "drug": drug,
                "batch_no": "G1",
                "expiry_date": timezone.localdate() + timedelta(days=365),
                "quantity": 10,
                "purchase_price": "3.00",
                "mrp": "5.00",
            }
        ],
    )

    batch = StockBatch.objects.get(store=store, drug=drug, batch_no="G1")
    assert batch.quantity == 10
    assert grn.total_amount == Decimal("30.00")
    po_item.refresh_from_db()
    po.refresh_from_db()
    assert po_item.quantity_received == 10
    assert po.status == POStatus.RECEIVED


def test_requisition_convert_to_po():
    store = factories.make_store()
    drug = factories.make_drug()
    requisition = services.create_requisition(
        store=store, items=[{"drug_id": drug.id, "quantity": 20}]
    )
    assert requisition.pr_number.startswith("PR-")
    services.set_requisition_status(
        requisition=requisition, status=RequisitionStatus.APPROVED
    )

    po = services.convert_requisition_to_po(
        requisition=requisition, vendor=factories.make_vendor()
    )

    requisition.refresh_from_db()
    assert requisition.status == RequisitionStatus.CONVERTED
    assert po.po_number.startswith("PO-")
    assert po.items.count() == 1
    assert po.items.first().quantity_ordered == 20
