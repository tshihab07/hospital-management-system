"""Selector (report) tests for the Accounting module."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.billing import services as billing

from .. import selectors, services
from ..models import SystemAccount
from . import factories

pytestmark = pytest.mark.django_db


def test_trial_balance_is_balanced_after_postings():
    bill = factories.make_charged_bill(amount="1000.00", vat_rate="15")
    billing.issue_bill(bill)
    tb = selectors.trial_balance()
    assert tb["is_balanced"] is True
    assert tb["total_debit"] == tb["total_credit"]
    assert tb["total_debit"] > 0


def test_income_statement_reports_revenue_and_expense():
    bill = factories.make_charged_bill(amount="1000.00")
    billing.issue_bill(bill)
    factories.seed_chart()
    services.create_expense(
        category=factories.system_account(SystemAccount.EXPENSE_OTHER),
        paid_from=factories.system_account(SystemAccount.CASH),
        amount="250.00",
        description="Supplies",
    )
    statement = selectors.income_statement()
    assert statement["total_revenue"] == Decimal("1000.00")
    assert statement["total_expense"] == Decimal("250.00")
    assert statement["net_income"] == Decimal("750.00")


def test_balance_sheet_balances():
    bill = factories.make_charged_bill(amount="1000.00")
    billing.issue_bill(bill)
    bs = selectors.balance_sheet()
    assert bs["difference"] == Decimal("0")


def test_ar_summary_and_aging():
    bill = factories.make_charged_bill(amount="600.00")
    billing.issue_bill(bill)
    summary = selectors.ar_summary()
    assert summary["total"] == Decimal("600.00")
    assert summary["open_count"] == 1

    # Age the bill into the 31–60 day bucket.
    bill.issued_at = bill.issued_at - timedelta(days=45)
    bill.save(update_fields=["issued_at", "updated_at"])
    aging = selectors.ar_aging()
    assert aging["totals"]["31-60"] == Decimal("600.00")
    assert aging["grand_total"] == Decimal("600.00")


def test_vat_return_output_vat():
    bill = factories.make_charged_bill(amount="1000.00", vat_rate="15")
    billing.issue_bill(bill)
    vat = selectors.vat_return()
    assert vat["output_vat"] == Decimal("150.00")
    assert vat["net_payable"] == Decimal("150.00")


def test_account_ledger_running_totals():
    factories.seed_chart()
    cash = factories.system_account(SystemAccount.CASH)
    bank = factories.system_account(SystemAccount.BANK)
    services.create_journal_entry(
        lines=[
            {"account": cash, "debit": "300.00"},
            {"account": bank, "credit": "300.00"},
        ]
    )
    services.create_journal_entry(
        lines=[
            {"account": cash, "debit": "200.00"},
            {"account": bank, "credit": "200.00"},
        ]
    )
    ledger = selectors.account_ledger(cash)
    assert ledger["opening"] == Decimal("0")
    assert ledger["total_debit"] == Decimal("500.00")
    assert ledger["closing"] == Decimal("500.00")


def test_cash_and_bank_balance():
    bill = factories.make_charged_bill(amount="400.00")
    billing.issue_bill(bill)
    billing.collect_payment(bill, method="cash", amount="400.00")
    assert selectors.cash_and_bank_balance() == Decimal("400.00")


def test_dashboard_kpis_shape():
    bill = factories.make_charged_bill(amount="100.00")
    billing.issue_bill(bill)
    kpis = selectors.dashboard_kpis()
    assert kpis["revenue"] == Decimal("100.00")
    assert "receivable" in kpis and "trial_balanced" in kpis
