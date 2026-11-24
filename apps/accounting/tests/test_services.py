"""Service-level (posting engine) tests for the Accounting module."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.billing import services as billing
from apps.billing.models import PaymentMode
from apps.pharmacy.models import GoodsReceiptNote, PharmacyStore, Vendor

from .. import services
from ..models import Account, JournalEntry, JournalStatus, SystemAccount
from . import factories

pytestmark = pytest.mark.django_db


def _balance(entry, key):
    account = factories.system_account(key)
    debit = credit = Decimal("0")
    for line in entry.lines.filter(account=account):
        debit += Decimal(str(line.debit))
        credit += Decimal(str(line.credit))
    return debit, credit


def test_seed_chart_is_idempotent():
    first = services.seed_chart_of_accounts()
    assert first["created"] > 0
    second = services.seed_chart_of_accounts()
    assert second["created"] == 0
    assert second["existing"] == first["created"]


def test_issue_bill_posts_receivable_and_revenue():
    bill = factories.make_charged_bill(amount="1000.00")
    billing.issue_bill(bill)
    entry = JournalEntry.objects.get(source_type="billing.bill", source_id=str(bill.pk))
    assert entry.status == JournalStatus.POSTED
    assert entry.total_debit == Decimal("1000.00")
    dr, _ = _balance(entry, SystemAccount.AR)
    assert dr == Decimal("1000.00")
    _, cr = _balance(entry, SystemAccount.REVENUE_CONSULTATION)
    assert cr == Decimal("1000.00")


def test_payment_posts_cash_and_clears_receivable():
    bill = factories.make_charged_bill(amount="500.00")
    billing.issue_bill(bill)
    payment = billing.collect_payment(bill, method=PaymentMode.CASH, amount="500.00")
    entry = JournalEntry.objects.get(
        source_type="billing.payment", source_id=str(payment.pk)
    )
    dr, _ = _balance(entry, SystemAccount.CASH)
    _, cr = _balance(entry, SystemAccount.AR)
    assert dr == Decimal("500.00")
    assert cr == Decimal("500.00")


def test_advance_posts_to_patient_advance_liability():
    patient = factories.make_patient()
    advance = billing.add_advance(patient, amount="2000.00", method=PaymentMode.CASH)
    entry = JournalEntry.objects.get(
        source_type="billing.advance", source_id=str(advance.pk)
    )
    dr, _ = _balance(entry, SystemAccount.CASH)
    _, cr = _balance(entry, SystemAccount.PATIENT_ADVANCE)
    assert dr == Decimal("2000.00")
    assert cr == Decimal("2000.00")


def test_applying_advance_debits_liability():
    patient = factories.make_patient()
    billing.add_advance(patient, amount="2000.00", method=PaymentMode.CASH)
    bill = factories.make_charged_bill(amount="800.00", patient=patient)
    billing.issue_bill(bill)
    advance = patient.advances.first()
    payment = billing.apply_advance(advance, bill, amount="800.00")
    entry = JournalEntry.objects.get(
        source_type="billing.payment", source_id=str(payment.pk)
    )
    dr, _ = _balance(entry, SystemAccount.PATIENT_ADVANCE)
    _, cr = _balance(entry, SystemAccount.AR)
    assert dr == Decimal("800.00")
    assert cr == Decimal("800.00")


def test_credit_note_posts_sales_return():
    from apps.billing.models import CreditNote

    bill = factories.make_charged_bill(amount="1000.00")
    billing.issue_bill(bill)
    billing.collect_payment(bill, method=PaymentMode.CASH, amount="1000.00")
    note = CreditNote.objects.create(
        bill=bill, note_no="CN-TEST-0001", amount="200.00", reason="Return"
    )
    billing.issue_credit_note(note)
    entry = JournalEntry.objects.get(
        source_type="billing.creditnote", source_id=str(note.pk)
    )
    dr, _ = _balance(entry, SystemAccount.SALES_RETURN)
    assert dr == Decimal("200.00")


def test_expense_records_balanced_journal():
    factories.seed_chart()
    category = Account.objects.get(system_key=SystemAccount.EXPENSE_OTHER)
    paid_from = factories.system_account(SystemAccount.CASH)
    expense = services.create_expense(
        category=category,
        paid_from=paid_from,
        amount="1500.00",
        description="Electricity",
    )
    assert expense.journal is not None
    entry = expense.journal
    assert entry.total_debit == Decimal("1500.00")


def test_vendor_payment_debits_payable():
    factories.seed_chart()
    vendor = Vendor.objects.create(name="Acme Supplies")
    payment = services.create_vendor_payment(
        vendor=vendor, amount="3000.00", method="cash"
    )
    entry = payment.journal
    dr, _ = _balance(entry, SystemAccount.AP)
    _, cr = _balance(entry, SystemAccount.CASH)
    assert dr == Decimal("3000.00")
    assert cr == Decimal("3000.00")


def test_grn_posts_inventory_and_payable():
    factories.seed_chart()
    store = PharmacyStore.objects.create(name="Main", code="MAIN")
    vendor = Vendor.objects.create(name="MedPlus")
    grn = GoodsReceiptNote.objects.create(
        grn_number="GRN-TEST-0001", vendor=vendor, store=store, total_amount="7500.00"
    )
    services.post_grn_journal(grn)
    entry = JournalEntry.objects.get(source_type="pharmacy.grn", source_id=str(grn.pk))
    dr, _ = _balance(entry, SystemAccount.INVENTORY)
    _, cr = _balance(entry, SystemAccount.AP)
    assert dr == Decimal("7500.00")
    assert cr == Decimal("7500.00")


def test_reversal_mirrors_entry():
    factories.seed_chart()
    cash = factories.system_account(SystemAccount.CASH)
    bank = factories.system_account(SystemAccount.BANK)
    entry = services.create_journal_entry(
        lines=[
            {"account": cash, "debit": "100.00"},
            {"account": bank, "credit": "100.00"},
        ]
    )
    reversal = services.reverse_journal_entry(entry)
    entry.refresh_from_db()
    assert entry.status == JournalStatus.REVERSED
    dr, _ = _balance(reversal, SystemAccount.BANK)
    _, cr = _balance(reversal, SystemAccount.CASH)
    assert dr == Decimal("100.00")
    assert cr == Decimal("100.00")


def test_close_period_blocks_posting():
    factories.seed_chart()
    cash = factories.system_account(SystemAccount.CASH)
    bank = factories.system_account(SystemAccount.BANK)
    entry = services.create_journal_entry(
        lines=[
            {"account": cash, "debit": "50.00"},
            {"account": bank, "credit": "50.00"},
        ]
    )
    period = entry.period
    services.close_period(period)
    period.refresh_from_db()
    assert period.is_closed is True
    with pytest.raises(ValueError):
        services.create_journal_entry(
            date=period.start_date,
            lines=[
                {"account": cash, "debit": "10.00"},
                {"account": bank, "credit": "10.00"},
            ],
        )
