"""Service-level tests for the Billing & Payments module."""

from __future__ import annotations

from decimal import Decimal

import pytest

from .. import services
from ..models import BillStatus, DiscountStatus, MoneyReceipt, Payment, RefundStatus
from . import factories

pytestmark = pytest.mark.django_db


def test_post_charge_and_vat_calculation():
    bill = factories.make_bill()
    services.post_charge(
        bill,
        item_type="lab",
        description="CBC",
        quantity=2,
        unit_price="150.00",
    )
    services.calculate_vat(bill, rate="15")
    bill.refresh_from_db()
    assert bill.subtotal == Decimal("300.00")
    assert bill.vat == Decimal("45.00")
    assert bill.total == Decimal("345.00")


def test_full_payment_creates_receipt_and_marks_paid():
    bill = factories.make_charged_bill(amount="500.00")
    payment = services.collect_payment(bill, method="cash", amount="500.00", actor=None)
    bill.refresh_from_db()
    assert bill.status == BillStatus.PAID
    assert bill.paid_amount == Decimal("500.00")
    assert MoneyReceipt.objects.filter(payment=payment).exists()
    assert payment.receipt.receipt_no.startswith("MR-")


def test_partial_then_full_payment_status():
    bill = factories.make_charged_bill(amount="1000.00")
    services.collect_payment(bill, method="card", amount="400.00")
    bill.refresh_from_db()
    assert bill.status == BillStatus.PARTIALLY_PAID
    services.collect_payment(bill, method="bkash", amount="600.00")
    bill.refresh_from_db()
    assert bill.status == BillStatus.PAID


def test_overpayment_is_rejected():
    bill = factories.make_charged_bill(amount="100.00")
    with pytest.raises(ValueError):
        services.collect_payment(bill, method="cash", amount="200.00")


def test_zero_payment_is_rejected():
    bill = factories.make_charged_bill(amount="100.00")
    with pytest.raises(ValueError):
        services.collect_payment(bill, method="cash", amount="0")


def test_large_discount_requires_approval():
    bill = factories.make_charged_bill(amount="10000.00")
    services.apply_discount(bill, amount="2000.00", reason="Charity", actor=None)
    bill.refresh_from_db()
    assert bill.discount_status == DiscountStatus.PENDING
    services.decide_discount(bill, approved=True, actor=None)
    bill.refresh_from_db()
    assert bill.discount_status == DiscountStatus.APPROVED
    assert bill.total == Decimal("8000.00")


def test_small_discount_auto_approved():
    bill = factories.make_charged_bill(amount="10000.00")
    services.apply_discount(bill, amount="100.00", reason="Goodwill", actor=None)
    bill.refresh_from_db()
    assert bill.discount_status == DiscountStatus.APPROVED


def test_rejected_discount_is_cleared():
    bill = factories.make_charged_bill(amount="10000.00")
    services.apply_discount(bill, amount="2000.00", actor=None)
    services.decide_discount(bill, approved=False, actor=None)
    bill.refresh_from_db()
    assert bill.discount == Decimal("0")
    assert bill.discount_status == DiscountStatus.REJECTED


def test_refund_workflow_reduces_paid_amount():
    bill = factories.make_charged_bill(amount="1000.00")
    payment = services.collect_payment(bill, method="cash", amount="1000.00")
    refund = services.create_refund(
        amount="300.00", reason="Overcharge", method="cash", bill=bill, payment=payment
    )
    services.decide_refund(refund, approved=True, actor=None)
    services.process_refund(refund, actor=None)
    refund.refresh_from_db()
    bill.refresh_from_db()
    assert refund.status == RefundStatus.PROCESSED
    assert bill.paid_amount == Decimal("700.00")
    assert bill.status == BillStatus.PARTIALLY_PAID


def test_cannot_process_unapproved_refund():
    bill = factories.make_charged_bill(amount="1000.00")
    services.collect_payment(bill, method="cash", amount="1000.00")
    refund = services.create_refund(amount="300.00", reason="x", bill=bill)
    with pytest.raises(ValueError):
        services.process_refund(refund, actor=None)


def test_advance_can_be_applied_to_bill():
    patient = factories.make_patient()
    advance = services.add_advance(patient, amount="5000.00")
    bill = factories.make_charged_bill(amount="1200.00", patient=patient)
    payment = services.apply_advance(advance, bill, amount="1200.00")
    advance.refresh_from_db()
    bill.refresh_from_db()
    assert isinstance(payment, Payment)
    assert advance.balance == Decimal("3800.00")
    assert bill.status == BillStatus.PAID
