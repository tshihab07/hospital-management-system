"""Billing Phase 12 completion tests: packages, credit notes, gateway, reports."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.masters.models import TaxCategory, TaxConfig
from apps.opd.models import Appointment, AppointmentStatus, Doctor

from .. import services
from ..gateways import GatewayError, get_gateway
from ..models import (
    BillStatus,
    CreditNoteStatus,
    Payment,
    ServicePackage,
    ServicePackageItem,
)
from . import factories

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# OPD charge posting
# ---------------------------------------------------------------------------
def test_post_opd_charges_posts_completed_appointment_once():
    patient = factories.make_patient()
    doctor = Doctor.objects.create(name_en="Dr. House", consultation_fee="800.00")
    Appointment.objects.create(
        doctor=doctor,
        patient=patient,
        appt_date="2026-01-05",
        token_no=1,
        status=AppointmentStatus.COMPLETED,
        consultation_fee="800.00",
    )
    bill = services.post_opd_charges(patient)
    bill.refresh_from_db()
    assert bill.subtotal == Decimal("800.00")
    assert bill.items.count() == 1
    # second call is idempotent
    services.post_opd_charges(patient)
    bill.refresh_from_db()
    assert bill.items.count() == 1


def test_opd_charges_skip_unfinished_appointments():
    patient = factories.make_patient()
    doctor = Doctor.objects.create(name_en="Dr. Who", consultation_fee="500.00")
    Appointment.objects.create(
        doctor=doctor,
        patient=patient,
        appt_date="2026-01-05",
        token_no=1,
        status=AppointmentStatus.SCHEDULED,
        consultation_fee="500.00",
    )
    bill = services.post_opd_charges(patient)
    bill.refresh_from_db()
    assert bill.subtotal == Decimal("0.00")


# ---------------------------------------------------------------------------
# VAT from TaxConfig master (NBR rules)
# ---------------------------------------------------------------------------
def test_resolve_vat_rate_uses_tax_config():
    TaxConfig.objects.create(name="Standard VAT", category=TaxCategory.VAT, rate="15")
    assert services.resolve_vat_rate() == Decimal("15")


def test_vat_falls_back_to_settings_default(settings):
    settings.IHMS = {**settings.IHMS, "BILL_DEFAULT_VAT_RATE": "7.5"}
    assert services.resolve_vat_rate() == Decimal("7.5")


# ---------------------------------------------------------------------------
# Package billing
# ---------------------------------------------------------------------------
def test_create_package_bill_from_components():
    package = ServicePackage.objects.create(
        code="CSEC", name="Caesarean Section", price="50000.00"
    )
    ServicePackageItem.objects.create(
        package=package,
        item_type="procedure",
        description="Surgeon fee",
        quantity=1,
        unit_price="30000.00",
    )
    ServicePackageItem.objects.create(
        package=package,
        item_type="bed",
        description="Cabin 3 days",
        quantity=1,
        unit_price="20000.00",
    )
    bill = services.create_package_bill(factories.make_patient(), package)
    bill.refresh_from_db()
    assert bill.bill_type == "package"
    assert bill.status == BillStatus.ISSUED
    assert bill.subtotal == Decimal("50000.00")
    assert bill.items.count() == 2


def test_create_package_bill_falls_back_to_flat_price():
    package = ServicePackage.objects.create(
        code="MAT", name="Normal Delivery", price="15000.00"
    )
    bill = services.create_package_bill(factories.make_patient(), package)
    bill.refresh_from_db()
    assert bill.subtotal == Decimal("15000.00")
    assert bill.items.count() == 1


# ---------------------------------------------------------------------------
# Locked-bill guard + credit notes
# ---------------------------------------------------------------------------
def test_paid_bill_is_locked_and_rejects_new_charges():
    bill = factories.make_charged_bill(amount="100.00")
    services.collect_payment(bill, method="cash", amount="100.00")
    bill.refresh_from_db()
    assert bill.is_locked is True
    with pytest.raises(ValueError):
        services.post_charge(
            bill, item_type="lab", description="X", unit_price="10.00"
        )


def test_open_bill_skips_locked_bills_for_charge_posting():
    patient = factories.make_patient()
    bill = services.create_bill(patient)
    services.post_charge(
        bill, item_type="lab", description="CBC", unit_price="200.00"
    )
    services.collect_payment(bill, method="cash", amount="200.00")
    # posting a lab charge again should open a fresh bill, not reuse the paid one
    fresh = services.get_or_create_open_bill(patient)
    assert fresh.pk != bill.pk


def test_credit_note_reduces_total():
    bill = factories.make_charged_bill(amount="1000.00")
    services.collect_payment(bill, method="cash", amount="1000.00")
    bill.refresh_from_db()
    assert bill.is_locked is True
    note = services.create_credit_note(bill, amount="150.00", reason="Overcharged")
    assert note.note_no.startswith("CN-")
    services.issue_credit_note(note)
    bill.refresh_from_db()
    assert bill.subtotal == Decimal("850.00")
    assert bill.total == Decimal("850.00")


def test_credit_note_cannot_exceed_bill_total():
    bill = factories.make_charged_bill(amount="100.00")
    with pytest.raises(ValueError):
        services.create_credit_note(bill, amount="200.00", reason="Nope")


def test_void_credit_note_restores_total():
    bill = factories.make_charged_bill(amount="1000.00")
    services.issue_bill(bill)
    note = services.create_credit_note(bill, amount="250.00", reason="Refund adj")
    services.issue_credit_note(note)
    services.void_credit_note(note)
    bill.refresh_from_db()
    assert bill.subtotal == Decimal("1000.00")
    note.refresh_from_db()
    assert note.status == CreditNoteStatus.VOID


# ---------------------------------------------------------------------------
# Online payment gateway
# ---------------------------------------------------------------------------
def test_gateway_rejects_cash_channel():
    with pytest.raises(GatewayError):
        get_gateway("cash")


def test_initiate_and_confirm_online_payment():
    bill = factories.make_charged_bill(amount="600.00")
    payment = services.initiate_online_payment(bill, method="bkash", amount="600.00")
    assert payment.txn_ref.startswith("BKASH-")
    services.confirm_online_payment(payment, success=True)
    bill.refresh_from_db()
    assert bill.status == BillStatus.PAID
    assert bill.paid_amount == Decimal("600.00")
    assert payment.receipt.receipt_no.startswith("MR-")


def test_cancel_online_payment_leaves_bill_unpaid():
    bill = factories.make_charged_bill(amount="600.00")
    payment = services.initiate_online_payment(bill, method="nagad", amount="600.00")
    pk = payment.pk
    services.confirm_online_payment(payment, success=False)
    bill.refresh_from_db()
    assert bill.paid_amount == Decimal("0.00")
    assert not Payment.objects.filter(pk=pk).exists()


# ---------------------------------------------------------------------------
# Daily collection report
# ---------------------------------------------------------------------------
def test_daily_collection_totals_by_method():
    from .. import selectors

    bill = factories.make_charged_bill(amount="1000.00")
    services.collect_payment(bill, method="cash", amount="400.00")
    services.collect_payment(bill, method="card", amount="600.00")
    report = selectors.daily_collection()
    assert report["count"] == 2
    assert report["grand_total"] == Decimal("1000.00")
    methods = {row["method"] for row in report["rows"]}
    assert methods == {"cash", "card"}


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
PERMS = [
    "billing.view_bill",
    "billing.add_bill",
    "billing.change_bill",
    "billing.view_payment",
    "billing.add_payment",
    "billing.view_servicepackage",
    "billing.add_servicepackage",
    "billing.view_creditnote",
    "billing.add_creditnote",
    "billing.change_creditnote",
]


@pytest.fixture
def client_logged(client):
    client.force_login(factories.make_user(*PERMS))
    return client


def test_package_pages_render(client_logged):
    assert client_logged.get(reverse("billing:package_list")).status_code == 200
    assert client_logged.get(reverse("billing:package_bill_create")).status_code == 200


def test_credit_note_list_renders(client_logged):
    assert client_logged.get(reverse("billing:credit_note_list")).status_code == 200


def test_daily_collection_view_and_csv(client_logged):
    bill = factories.make_charged_bill(amount="300.00")
    services.collect_payment(bill, method="cash", amount="300.00")
    assert client_logged.get(reverse("billing:daily_collection")).status_code == 200
    csv_resp = client_logged.get(reverse("billing:daily_collection"), {"export": "csv"})
    assert csv_resp.status_code == 200
    assert csv_resp["Content-Type"].startswith("text/csv")


def test_online_payment_view_flow(client_logged):
    bill = factories.make_charged_bill(amount="250.00")
    resp = client_logged.post(
        reverse("billing:pay_online", args=[bill.pk]),
        {"method": "bkash", "amount": "250.00"},
    )
    assert resp.status_code == 302
    payment = Payment.objects.get()
    confirm = client_logged.post(
        reverse("billing:gateway_confirm", args=[payment.txn_ref]),
        {"result": "success"},
    )
    assert confirm.status_code == 302
    bill.refresh_from_db()
    assert bill.status == BillStatus.PAID


def test_credit_note_created_via_view(client_logged):
    bill = factories.make_charged_bill(amount="500.00")
    services.collect_payment(bill, method="cash", amount="500.00")
    resp = client_logged.post(
        reverse("billing:credit_note_create", args=[bill.pk]),
        {"amount": "50.00", "reason": "Discount after payment"},
    )
    assert resp.status_code == 302
    assert bill.credit_notes.count() == 1
