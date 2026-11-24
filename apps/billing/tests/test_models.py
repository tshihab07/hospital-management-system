"""Model-level tests for the Billing & Payments module."""

from __future__ import annotations

from decimal import Decimal

import pytest

from .. import services
from ..models import BillStatus
from . import factories

pytestmark = pytest.mark.django_db


def test_bill_number_sequence_is_unique():
    b1 = factories.make_bill()
    b2 = factories.make_bill()
    assert b1.bill_no != b2.bill_no
    assert b1.bill_no.startswith("BILL-")


def test_recompute_sums_items_and_vat():
    bill = factories.make_charged_bill(amount="1000.00", vat_rate="5")
    bill.refresh_from_db()
    assert bill.subtotal == Decimal("1000.00")
    assert bill.vat == Decimal("50.00")
    assert bill.total == Decimal("1050.00")
    assert bill.due_amount == Decimal("1050.00")


def test_recompute_with_discount():
    bill = factories.make_charged_bill(amount="1000.00")
    services.apply_discount(bill, amount="100.00", actor=None)
    bill.refresh_from_db()
    assert bill.discount == Decimal("100.00")
    assert bill.total == Decimal("900.00")


def test_bill_defaults_to_draft():
    bill = factories.make_bill()
    assert bill.status == BillStatus.DRAFT
    assert not bill.is_settled


def test_advance_balance_property():
    patient = factories.make_patient()
    advance = services.add_advance(patient, amount="5000.00")
    assert advance.balance == Decimal("5000.00")
