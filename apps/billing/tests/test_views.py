"""View-level tests for the Billing & Payments module."""

from __future__ import annotations

import pytest
from django.urls import reverse

from ..models import MoneyReceipt
from . import factories

pytestmark = pytest.mark.django_db

PERMS = [
    "billing.view_bill",
    "billing.add_bill",
    "billing.change_bill",
    "billing.view_billitem",
    "billing.view_payment",
    "billing.add_payment",
    "billing.view_moneyreceipt",
    "billing.view_advance",
    "billing.add_advance",
    "billing.view_refund",
    "billing.add_refund",
    "billing.change_refund",
]


@pytest.fixture
def client_logged(client):
    client.force_login(factories.make_user(*PERMS))
    return client


def test_dashboard_renders(client_logged):
    assert client_logged.get(reverse("billing:dashboard")).status_code == 200


def test_bill_list_and_create_pages(client_logged):
    assert client_logged.get(reverse("billing:bill_list")).status_code == 200
    assert client_logged.get(reverse("billing:bill_create")).status_code == 200


def test_bill_detail_renders(client_logged):
    bill = factories.make_charged_bill(amount="250.00")
    resp = client_logged.get(reverse("billing:bill_detail", args=[bill.pk]))
    assert resp.status_code == 200
    assert bill.bill_no.encode() in resp.content


def test_collect_payment_via_view_creates_receipt(client_logged):
    bill = factories.make_charged_bill(amount="300.00")
    resp = client_logged.post(
        reverse("billing:payment_create", args=[bill.pk]),
        {"method": "cash", "amount": "300.00", "txn_ref": ""},
    )
    assert resp.status_code == 302
    assert MoneyReceipt.objects.count() == 1


def test_receipt_page_renders(client_logged):
    bill = factories.make_charged_bill(amount="300.00")
    from .. import services

    payment = services.collect_payment(bill, method="cash", amount="300.00")
    resp = client_logged.get(reverse("billing:receipt", args=[payment.pk]))
    assert resp.status_code == 200


def test_advance_list_and_create(client_logged):
    assert client_logged.get(reverse("billing:advance_list")).status_code == 200
    assert client_logged.get(reverse("billing:advance_create")).status_code == 200


def test_refund_list_renders(client_logged):
    assert client_logged.get(reverse("billing:refund_list")).status_code == 200


def test_ledger_page_renders_with_and_without_patient(client_logged):
    patient = factories.make_patient()
    assert client_logged.get(reverse("billing:ledger")).status_code == 200
    resp = client_logged.get(reverse("billing:ledger_detail", args=[patient.pk]))
    assert resp.status_code == 200


def test_permission_required(client, django_user_model):
    user = django_user_model.objects.create_user(username="noperm", password="x")
    client.force_login(user)
    resp = client.get(reverse("billing:bill_list"))
    assert resp.status_code == 403
