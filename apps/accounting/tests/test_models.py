"""Model-level tests for the Accounting module."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from .. import services
from ..models import (
    Account,
    AccountType,
    JournalEntry,
    JournalEntryType,
    JournalLine,
    NormalBalance,
    SystemAccount,
)
from . import factories

pytestmark = pytest.mark.django_db


def test_account_normal_balance_defaults_from_type():
    account = Account.objects.create(
        code="T-1", name="Test Asset", account_type=AccountType.ASSET
    )
    assert account.normal_balance == NormalBalance.DEBIT
    income = Account.objects.create(
        code="T-2", name="Test income", account_type=AccountType.INCOME
    )
    assert income.normal_balance == NormalBalance.CREDIT


def test_system_key_marks_account_as_system():
    account = Account.objects.create(
        code="T-3",
        name="Cash",
        account_type=AccountType.ASSET,
        system_key=SystemAccount.CASH,
    )
    assert account.is_system is True


def test_account_balance_uses_normal_direction():
    factories.seed_chart()
    account = factories.system_account(SystemAccount.CASH)
    entry = services.create_journal_entry(
        lines=[
            {"account": account, "debit": "500.00"},
            {
                "account": factories.system_account(SystemAccount.BANK),
                "credit": "500.00",
            },
        ]
    )
    assert entry.status == "posted"
    assert account.balance == Decimal("500.00")


def test_journal_line_rejects_zero_amounts():
    factories.seed_chart()
    entry = JournalEntry.objects.create(
        entry_no="JE-TEST-0001", entry_type=JournalEntryType.MANUAL
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        JournalLine.objects.create(
            journal=entry, account=factories.system_account(SystemAccount.CASH)
        )


def test_group_account_cannot_be_posted_to():
    factories.seed_chart()
    group = Account.objects.filter(is_group=True).first()
    with pytest.raises(ValueError):
        services.create_journal_entry(
            lines=[
                {"account": group, "debit": "10.00"},
                {
                    "account": factories.system_account(SystemAccount.CASH),
                    "credit": "10.00",
                },
            ]
        )


def test_unbalanced_journal_is_rejected():
    factories.seed_chart()
    with pytest.raises(ValueError):
        services.create_journal_entry(
            lines=[
                {
                    "account": factories.system_account(SystemAccount.CASH),
                    "debit": "10.00",
                },
                {
                    "account": factories.system_account(SystemAccount.BANK),
                    "credit": "5.00",
                },
            ]
        )
