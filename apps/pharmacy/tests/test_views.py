"""View-level tests for the Pharmacy & Inventory module."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from ..models import DispenseRecord, POStatus, StockBatch
from . import factories

pytestmark = pytest.mark.django_db

PERMS = [
    "pharmacy.view_stockbatch",
    "pharmacy.add_stockbatch",
    "pharmacy.change_stockbatch",
    "pharmacy.view_dispenserecord",
    "pharmacy.add_dispenserecord",
    "pharmacy.view_vendor",
    "pharmacy.add_vendor",
    "pharmacy.view_purchaserequisition",
    "pharmacy.add_purchaserequisition",
    "pharmacy.change_purchaserequisition",
    "pharmacy.view_purchaseorder",
    "pharmacy.add_purchaseorder",
    "pharmacy.change_purchaseorder",
    "pharmacy.view_goodsreceiptnote",
    "pharmacy.add_goodsreceiptnote",
]


@pytest.fixture
def client_logged(client):
    client.force_login(factories.make_user(*PERMS))
    return client


def test_dashboard_renders(client_logged):
    resp = client_logged.get(reverse("pharmacy:dashboard"))
    assert resp.status_code == 200


def test_stock_and_alert_pages(client_logged):
    for name in ("pharmacy:stock_list", "pharmacy:expiry_alerts", "pharmacy:low_stock"):
        assert client_logged.get(reverse(name)).status_code == 200


def test_vendor_and_po_pages(client_logged):
    assert client_logged.get(reverse("pharmacy:vendor_list")).status_code == 200
    assert client_logged.get(reverse("pharmacy:vendor_create")).status_code == 200
    assert client_logged.get(reverse("pharmacy:po_list")).status_code == 200
    assert client_logged.get(reverse("pharmacy:grn_list")).status_code == 200
    assert client_logged.get(reverse("pharmacy:requisition_list")).status_code == 200


def test_create_batch_via_view(client_logged):
    store = factories.make_store()
    drug = factories.make_drug()
    resp = client_logged.post(
        reverse("pharmacy:batch_create"),
        {
            "store": store.pk,
            "drug": drug.pk,
            "batch_no": "VB1",
            "quantity": 25,
            "purchase_price": "2.00",
            "mrp": "4.00",
        },
    )
    assert resp.status_code == 302
    assert StockBatch.objects.filter(
        store=store, drug=drug, batch_no="VB1", quantity=25
    ).exists()


def test_dispense_via_view(client_logged):
    store = factories.make_store()
    drug = factories.make_drug()
    factories.make_batch(
        store=store,
        drug=drug,
        quantity=10,
        expiry_date=timezone.localdate() + timedelta(days=30),
    )
    prescription = factories.make_prescription(drugs=[drug])
    item = prescription.items.first()

    resp = client_logged.post(
        reverse("pharmacy:dispense_create", args=[prescription.pk]),
        {"store": store.pk, f"qty_{item.pk}": 2},
    )
    assert resp.status_code == 302
    assert DispenseRecord.objects.filter(prescription=prescription).exists()


def test_batch_adjust_via_view(client_logged):
    batch = factories.make_batch(quantity=10)
    resp = client_logged.post(
        reverse("pharmacy:batch_action", args=[batch.pk, "adjust"]),
        {"new_quantity": 6, "reason": "Audit"},
    )
    assert resp.status_code == 302
    batch.refresh_from_db()
    assert batch.quantity == 6


def test_transfer_via_view(client_logged):
    central = factories.make_store(store_type="central")
    ward = factories.make_store(store_type="sub_store")
    drug = factories.make_drug()
    factories.make_batch(
        store=central,
        drug=drug,
        quantity=10,
        expiry_date=timezone.localdate() + timedelta(days=30),
    )
    resp = client_logged.post(
        reverse("pharmacy:stock_transfer"),
        {"from_store": central.pk, "to_store": ward.pk, "drug": drug.pk, "quantity": 3},
    )
    assert resp.status_code == 302
    assert StockBatch.objects.get(store=ward, drug=drug).quantity == 3


def test_requisition_create_and_convert_via_view(client_logged):
    store = factories.make_store()
    drug = factories.make_drug()
    resp = client_logged.post(
        reverse("pharmacy:requisition_list"),
        {"store": store.pk, "drug": [drug.pk], "quantity": [15]},
    )
    assert resp.status_code == 302
    from ..models import PurchaseRequisition

    requisition = PurchaseRequisition.objects.get()
    client_logged.post(
        reverse("pharmacy:requisition_action", args=[requisition.pk, "approve"])
    )
    requisition.refresh_from_db()
    vendor = factories.make_vendor()
    resp = client_logged.post(
        reverse("pharmacy:requisition_action", args=[requisition.pk, "convert"]),
        {"vendor": vendor.pk},
    )
    assert resp.status_code == 302


def test_po_create_and_grn_via_view(client_logged):
    store = factories.make_store()
    drug = factories.make_drug()
    vendor = factories.make_vendor()
    resp = client_logged.post(
        reverse("pharmacy:po_list"),
        {
            "vendor": vendor.pk,
            "store": store.pk,
            "drug": [drug.pk],
            "quantity": [10],
            "unit_price": ["3.00"],
        },
    )
    assert resp.status_code == 302
    from ..models import PurchaseOrder

    po = PurchaseOrder.objects.get()
    po_item = po.items.first()
    resp = client_logged.post(
        reverse("pharmacy:grn_create", args=[po.pk]),
        {
            "item_id": [po_item.pk],
            "batch_no": ["GRN1"],
            "expiry_date": [(timezone.localdate() + timedelta(days=200)).isoformat()],
            "quantity": [10],
            "purchase_price": ["3.00"],
            "mrp": ["5.00"],
        },
    )
    assert resp.status_code == 302
    batch = StockBatch.objects.get(store=store, drug=drug, batch_no="GRN1")
    assert batch.quantity == 10
    po.refresh_from_db()
    assert po.status == POStatus.RECEIVED


def test_views_require_permission(client, django_user_model):
    user = django_user_model.objects.create_user(username="noperms", password="x")
    client.force_login(user)
    resp = client.get(reverse("pharmacy:dashboard"))
    assert resp.status_code in (302, 403)
