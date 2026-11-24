"""View-level tests for the Accounting module."""

from __future__ import annotations

import pytest
from django.urls import reverse

from .. import services
from ..models import JournalEntry, SystemAccount
from . import factories

pytestmark = pytest.mark.django_db

PERMS = [
    "accounting.view_account",
    "accounting.add_account",
    "accounting.change_account",
    "accounting.view_journalentry",
    "accounting.add_journalentry",
    "accounting.post_journalentry",
    "accounting.reverse_journalentry",
    "accounting.view_accountingreports",
    "accounting.view_expense",
    "accounting.add_expense",
    "accounting.view_vendorpayment",
    "accounting.add_vendorpayment",
    "accounting.view_accountingperiod",
    "accounting.close_accountingperiod",
]


@pytest.fixture
def seeded():
    return services.seed_chart_of_accounts()


@pytest.fixture
def client_logged(client):
    client.force_login(factories.make_user(*PERMS))
    return client


REPORT_PAGES = [
    "accounting:dashboard",
    "accounting:chart",
    "accounting:ledger",
    "accounting:trial_balance",
    "accounting:income_statement",
    "accounting:balance_sheet",
    "accounting:receivables",
    "accounting:payables",
    "accounting:vat_return",
    "accounting:department_revenue",
    "accounting:doctor_revenue",
    "accounting:daily_report",
    "accounting:monthly_report",
    "accounting:journal_list",
    "accounting:expense_list",
    "accounting:vendor_payment_list",
    "accounting:period_list",
]


@pytest.mark.parametrize("url_name", REPORT_PAGES)
def test_pages_render(client_logged, seeded, url_name):
    assert client_logged.get(reverse(url_name)).status_code == 200


@pytest.mark.parametrize("url_name", REPORT_PAGES)
def test_pages_render_with_data(client_logged, seeded, url_name):
    from apps.billing import services as billing

    bill = factories.make_charged_bill(amount="1000.00", vat_rate="15")
    billing.issue_bill(bill)
    billing.collect_payment(bill, method="cash", amount="500.00")
    services.create_expense(
        category=factories.system_account(SystemAccount.EXPENSE_OTHER),
        paid_from=factories.system_account(SystemAccount.CASH),
        amount="120.00",
        description="Utilities",
    )
    cash = factories.system_account(SystemAccount.CASH)
    resp = client_logged.get(reverse(url_name), {"account": cash.pk})
    assert resp.status_code == 200


def test_create_pages_render(client_logged, seeded):
    for url_name in [
        "accounting:account_create",
        "accounting:journal_create",
        "accounting:expense_create",
        "accounting:vendor_payment_create",
    ]:
        assert client_logged.get(reverse(url_name)).status_code == 200


def test_chart_export_csv(client_logged, seeded):
    resp = client_logged.get(reverse("accounting:chart"), {"export": "csv"})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")


def test_trial_balance_export_xlsx(client_logged, seeded):
    resp = client_logged.get(reverse("accounting:trial_balance"), {"export": "xlsx"})
    assert resp.status_code == 200
    assert "spreadsheetml" in resp["Content-Type"]


def test_manual_journal_create(client_logged, seeded):
    cash = factories.system_account(SystemAccount.CASH)
    bank = factories.system_account(SystemAccount.BANK)
    data = {
        "date": "2026-01-15",
        "memo": "Opening transfer",
        "reference": "",
        "form-TOTAL_FORMS": "2",
        "form-INITIAL_FORMS": "0",
        "form-MIN_NUM_FORMS": "0",
        "form-MAX_NUM_FORMS": "1000",
        "form-0-account": str(cash.pk),
        "form-0-description": "Transfer in",
        "form-0-debit": "100.00",
        "form-0-credit": "",
        "form-1-account": str(bank.pk),
        "form-1-description": "Transfer out",
        "form-1-debit": "",
        "form-1-credit": "100.00",
    }
    resp = client_logged.post(reverse("accounting:journal_create"), data)
    assert resp.status_code == 302
    assert JournalEntry.objects.filter(memo="Opening transfer").exists()


def test_journal_detail_and_reverse(client_logged, seeded):
    cash = factories.system_account(SystemAccount.CASH)
    bank = factories.system_account(SystemAccount.BANK)
    entry = services.create_journal_entry(
        lines=[
            {"account": cash, "debit": "20.00"},
            {"account": bank, "credit": "20.00"},
        ]
    )
    assert (
        client_logged.get(
            reverse("accounting:journal_detail", args=[entry.pk])
        ).status_code
        == 200
    )
    resp = client_logged.post(
        reverse("accounting:journal_action", args=[entry.pk, "reverse"])
    )
    assert resp.status_code == 302
    entry.refresh_from_db()
    assert entry.status == "reversed"


def test_requires_permission(client, seeded):
    client.force_login(factories.make_user())  # no accounting perms
    resp = client.get(reverse("accounting:trial_balance"))
    assert resp.status_code in (302, 403)
