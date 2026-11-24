"""Read-only queries and financial reports for the Accounting module (RULES §2.2).

Every report is built from *posted* journal lines so drafts never leak into the
numbers. Balance-sheet and trial-balance figures combine each account's opening
balance with its cumulative postings; income-statement figures use movement
within the requested window only.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    Account,
    AccountType,
    JournalEntry,
    JournalStatus,
    NormalBalance,
    SystemAccount,
    _dec,
)


def _money(value) -> Decimal:
    return _dec(value)


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _add_month(day: date) -> date:
    year = day.year + (day.month // 12)
    month = day.month % 12 + 1
    return day.replace(year=year, month=month, day=1)


# ---------------------------------------------------------------------------
# Accounts & ledgers
# ---------------------------------------------------------------------------
def chart_of_accounts(
    *, account_type: str = "", search: str = "", active_only: bool = True
):
    qs = Account.objects.select_related("parent")
    if account_type:
        qs = qs.filter(account_type=account_type)
    if active_only:
        qs = qs.filter(is_active=True)
    if search:
        qs = qs.filter(
            Q(code__icontains=search)
            | Q(name__icontains=search)
            | Q(name_bn__icontains=search)
        )
    return qs.order_by("code")


def account_balances() -> dict[int, Decimal]:
    """Bulk net balance (in each account's normal direction) keyed by account id.

    Includes each account's opening balance so it matches the trial balance.
    """
    rows = (
        JournalEntry.objects.filter(status=JournalStatus.POSTED)
        .values("lines__account_id")
        .annotate(
            debit=Coalesce(Sum("lines__debit"), Decimal("0")),
            credit=Coalesce(Sum("lines__credit"), Decimal("0")),
        )
    )
    posted = {r["lines__account_id"]: r for r in rows}
    balances: dict[int, Decimal] = {}
    for account in Account.objects.all():
        row = posted.get(account.pk)
        movement = _movement_signed(account, row)
        balances[account.pk] = _opening_signed(account) + movement
    return balances


def account_tree() -> list[dict]:
    """Hierarchical chart of accounts for display."""
    accounts = list(
        Account.objects.filter(is_active=True).order_by("code").select_related("parent")
    )
    by_parent: dict[int | None, list] = {}
    for account in accounts:
        by_parent.setdefault(account.parent_id, []).append(account)
    rows: list[dict] = []

    def walk(parent_id, depth):
        for account in by_parent.get(parent_id, []):
            rows.append({"account": account, "depth": depth})
            walk(account.pk, depth + 1)

    walk(None, 0)
    return rows


def account_ledger(
    account: Account, *, start=None, end=None, party_type="", party_id=""
):
    """Movement ledger for one account between ``start`` and ``end``.

    Returns ``{account, opening, rows, closing, total_debit, total_credit}``.
    """
    posted = JournalStatus.POSTED
    opening_qs = account.lines.filter(journal__status=posted)
    rows_qs = account.lines.filter(journal__status=posted).select_related(
        "journal", "department", "doctor"
    )
    if party_type:
        opening_qs = opening_qs.filter(party_type=party_type)
        rows_qs = rows_qs.filter(party_type=party_type)
    if party_id:
        opening_qs = opening_qs.filter(party_id=str(party_id))
        rows_qs = rows_qs.filter(party_id=str(party_id))
    opening = _opening_signed(account)
    if start is not None:
        before = opening_qs.filter(journal__date__lt=start).aggregate(
            debit=Coalesce(Sum("debit"), Decimal("0")),
            credit=Coalesce(Sum("credit"), Decimal("0")),
        )
        opening += _signed(account, before["debit"], before["credit"])
        rows_qs = rows_qs.filter(journal__date__gte=start)
    if end is not None:
        rows_qs = rows_qs.filter(journal__date__lte=end)
    rows = list(rows_qs.order_by("journal__date", "journal__id", "id"))
    total_debit = sum((_money(r.debit) for r in rows), Decimal("0"))
    total_credit = sum((_money(r.credit) for r in rows), Decimal("0"))
    movement = (
        total_credit - total_debit
        if account.normal_balance == NormalBalance.CREDIT
        else total_debit - total_credit
    )
    return {
        "account": account,
        "opening": opening,
        "rows": rows,
        "closing": opening + movement,
        "total_debit": total_debit,
        "total_credit": total_credit,
    }


def _signed(account: Account, debit, credit) -> Decimal:
    debit = _money(debit)
    credit = _money(credit)
    if account.normal_balance == NormalBalance.CREDIT:
        return credit - debit
    return debit - credit


# ---------------------------------------------------------------------------
# Trial balance
# ---------------------------------------------------------------------------
def trial_balance(*, as_of=None, include_zero: bool = False) -> dict:
    """Balanced trial balance as of ``as_of`` (all posted movements + openings)."""
    as_of = as_of or timezone.localdate()
    lines = (
        JournalEntry.objects.filter(status=JournalStatus.POSTED, date__lte=as_of)
        .values("lines__account_id")
        .annotate(
            debit=Coalesce(Sum("lines__debit"), Decimal("0")),
            credit=Coalesce(Sum("lines__credit"), Decimal("0")),
        )
    )
    posted = {row["lines__account_id"]: row for row in lines}
    accounts = Account.objects.filter(is_active=True).order_by("code")
    rows: list[dict] = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for account in accounts:
        movement = posted.get(
            account.pk, {"debit": Decimal("0"), "credit": Decimal("0")}
        )
        raw = _money(movement["debit"]) - _money(movement["credit"])
        # Net balance expressed debit-positive.
        debit_positive = raw + (
            -_opening_signed(account)
            if account.normal_balance == NormalBalance.CREDIT
            else _opening_signed(account)
        )
        if debit_positive > 0:
            debit, credit = debit_positive, Decimal("0")
        elif debit_positive < 0:
            debit, credit = Decimal("0"), -debit_positive
        else:
            debit = credit = Decimal("0")
        if not include_zero and debit == 0 and credit == 0:
            continue
        total_debit += debit
        total_credit += credit
        rows.append(
            {
                "account": account,
                "debit": debit,
                "credit": credit,
            }
        )
    return {
        "as_of": as_of,
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_balanced": total_debit == total_credit,
        "difference": total_debit - total_credit,
    }


def _opening_signed(account: Account) -> Decimal:
    """Opening balance expressed in the account's normal direction."""
    return _money(account.opening_balance)


# ---------------------------------------------------------------------------
# Income statement (P&L)
# ---------------------------------------------------------------------------
def income_statement(*, start=None, end=None) -> dict:
    end = end or timezone.localdate()
    start = start or end.replace(month=1, day=1)
    movement = (
        JournalEntry.objects.filter(
            status=JournalStatus.POSTED, date__gte=start, date__lte=end
        )
        .values("lines__account_id")
        .annotate(
            debit=Coalesce(Sum("lines__debit"), Decimal("0")),
            credit=Coalesce(Sum("lines__credit"), Decimal("0")),
        )
    )
    posted = {row["lines__account_id"]: row for row in movement}
    revenue_rows = []
    expense_rows = []
    total_revenue = Decimal("0")
    total_expense = Decimal("0")
    for account in Account.objects.filter(
        is_active=True, account_type__in=[AccountType.INCOME, AccountType.EXPENSE]
    ).order_by("code"):
        row = posted.get(account.pk)
        if not row:
            continue
        debit = _money(row["debit"])
        credit = _money(row["credit"])
        if account.account_type == AccountType.INCOME:
            amount = credit - debit
            if amount:
                revenue_rows.append({"account": account, "amount": amount})
                total_revenue += amount
        else:
            amount = debit - credit
            if amount:
                expense_rows.append({"account": account, "amount": amount})
                total_expense += amount
    return {
        "start": start,
        "end": end,
        "revenue_rows": revenue_rows,
        "expense_rows": expense_rows,
        "total_revenue": total_revenue,
        "total_expense": total_expense,
        "net_income": total_revenue - total_expense,
    }


# ---------------------------------------------------------------------------
# Balance sheet
# ---------------------------------------------------------------------------
def balance_sheet(*, as_of=None) -> dict:
    as_of = as_of or timezone.localdate()
    posted = _cumulative_postings(as_of)
    assets, liabilities, equity = [], [], []
    total_assets = total_liabilities = total_equity = Decimal("0")
    for account in Account.objects.filter(is_active=True).order_by("code"):
        if account.account_type not in {
            AccountType.ASSET,
            AccountType.LIABILITY,
            AccountType.EQUITY,
        }:
            continue
        net = _opening_signed(account) + _movement_signed(
            account, posted.get(account.pk)
        )
        if net == 0:
            continue
        row = {"account": account, "amount": net}
        if account.account_type == AccountType.ASSET:
            assets.append(row)
            total_assets += net
        elif account.account_type == AccountType.LIABILITY:
            liabilities.append(row)
            total_liabilities += net
        else:
            equity.append(row)
            total_equity += net
    net_income = _net_income_to(as_of)
    total_equity_with_earnings = total_equity + net_income
    return {
        "as_of": as_of,
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity_with_earnings,
        "retained_earnings": net_income,
        "liabilities_and_equity": total_liabilities + total_equity_with_earnings,
        "difference": total_assets - (total_liabilities + total_equity_with_earnings),
    }


def _cumulative_postings(as_of):
    rows = (
        JournalEntry.objects.filter(status=JournalStatus.POSTED, date__lte=as_of)
        .values("lines__account_id")
        .annotate(
            debit=Coalesce(Sum("lines__debit"), Decimal("0")),
            credit=Coalesce(Sum("lines__credit"), Decimal("0")),
        )
    )
    return {r["lines__account_id"]: r for r in rows}


def _movement_signed(account: Account, row) -> Decimal:
    if not row:
        return Decimal("0")
    raw = _money(row["debit"]) - _money(row["credit"])
    if account.normal_balance == NormalBalance.CREDIT:
        return -raw
    return raw


def _net_income_to(as_of) -> Decimal:
    rows = (
        JournalEntry.objects.filter(status=JournalStatus.POSTED, date__lte=as_of)
        .values("lines__account__account_type")
        .annotate(
            debit=Coalesce(Sum("lines__debit"), Decimal("0")),
            credit=Coalesce(Sum("lines__credit"), Decimal("0")),
        )
    )
    income = expense = Decimal("0")
    for row in rows:
        kind = row["lines__account__account_type"]
        debit = _money(row["debit"])
        credit = _money(row["credit"])
        if kind == AccountType.INCOME:
            income += credit - debit
        elif kind == AccountType.EXPENSE:
            expense += debit - credit
    return income - expense


# ---------------------------------------------------------------------------
# Accounts receivable (patient dues)
# ---------------------------------------------------------------------------
def ar_summary():
    """Patient receivables from the billing module (source of truth for dues)."""
    from apps.billing.models import Bill, BillStatus

    qs = Bill.objects.exclude(status=BillStatus.CANCELLED).select_related("patient")
    total = Decimal("0")
    open_count = 0
    for bill in qs:
        due = bill.due_amount
        if due > 0:
            total += due
            open_count += 1
    return {"total": total, "open_count": open_count}


def _aging_keys(buckets) -> list[str]:
    """Human labels for age buckets, e.g. ``current``, ``31-60``, ``91+``."""
    keys = ["current"]
    for low, high in zip(buckets, buckets[1:]):
        keys.append(f"{low + 1}-{high}")
    keys.append(f"{buckets[-1] + 1}+")
    return keys


def _bucket_for(age: int, buckets) -> str:
    if age <= buckets[0]:
        return "current"
    for low, high in zip(buckets, buckets[1:]):
        if low < age <= high:
            return f"{low + 1}-{high}"
    return f"{buckets[-1] + 1}+"


def ar_aging(*, buckets=(30, 60, 90)) -> dict:
    from apps.billing.models import Bill, BillStatus

    today = timezone.localdate()
    qs = (
        Bill.objects.exclude(status=BillStatus.CANCELLED)
        .select_related("patient")
        .order_by("issued_at", "created_at")
    )
    rows = []
    totals = {key: Decimal("0") for key in _aging_keys(buckets)}
    for bill in qs:
        due = bill.due_amount
        if due <= 0:
            continue
        ref_date = bill.issued_at.date() if bill.issued_at else bill.created_at.date()
        age = (today - ref_date).days
        bucket = _bucket_for(age, buckets)
        totals[bucket] += due
        rows.append({"bill": bill, "due": due, "age": age, "bucket": bucket})
    return {
        "rows": rows,
        "totals": totals,
        "buckets": list(buckets),
        "grand_total": sum(totals.values(), Decimal("0")),
    }


# ---------------------------------------------------------------------------
# Accounts payable (vendor dues)
# ---------------------------------------------------------------------------
def ap_aging(*, buckets=(30, 60, 90)) -> dict:
    from collections import defaultdict

    from apps.pharmacy.models import GoodsReceiptNote

    from .models import VendorPayment

    today = timezone.localdate()
    grns = list(
        GoodsReceiptNote.objects.select_related("vendor").order_by(
            "received_date", "id"
        )
    )
    totals = {key: Decimal("0") for key in _aging_keys(buckets)}
    rows = []
    # Allocate payments FIFO per vendor against the oldest receipts.
    paid_by_vendor: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for payment in VendorPayment.objects.all():
        paid_by_vendor[payment.vendor_id] += _money(payment.amount)
    for grn in grns:
        outstanding = _money(grn.total_amount)
        available = paid_by_vendor.get(grn.vendor_id, Decimal("0"))
        if available > 0:
            applied = min(available, outstanding)
            paid_by_vendor[grn.vendor_id] = available - applied
            outstanding -= applied
        if outstanding <= 0:
            continue
        age = (today - grn.received_date).days if grn.received_date else 0
        bucket = _bucket_for(age, buckets)
        totals[bucket] += outstanding
        rows.append(
            {
                "grn": grn,
                "vendor": grn.vendor,
                "due": outstanding,
                "age": age,
                "bucket": bucket,
            }
        )
    return {
        "rows": rows,
        "totals": totals,
        "buckets": list(buckets),
        "grand_total": sum(totals.values(), Decimal("0")),
    }


def ap_summary():
    aging = ap_aging()
    return {
        "total": aging["grand_total"],
        "open_count": len(aging["rows"]),
    }


# ---------------------------------------------------------------------------
# VAT return (NBR format)
# ---------------------------------------------------------------------------
def vat_return(*, start=None, end=None) -> dict:
    end = end or timezone.localdate()
    start = start or _month_start(end)
    output = JournalEntry.objects.filter(
        status=JournalStatus.POSTED,
        date__gte=start,
        date__lte=end,
        lines__account__system_key=SystemAccount.VAT_PAYABLE,
    ).aggregate(
        debit=Coalesce(Sum("lines__debit"), Decimal("0")),
        credit=Coalesce(Sum("lines__credit"), Decimal("0")),
    )
    input_vat = JournalEntry.objects.filter(
        status=JournalStatus.POSTED,
        date__gte=start,
        date__lte=end,
        lines__account__system_key=SystemAccount.VAT_RECEIVABLE,
    ).aggregate(
        debit=Coalesce(Sum("lines__debit"), Decimal("0")),
        credit=Coalesce(Sum("lines__credit"), Decimal("0")),
    )
    output_vat = _money(output["credit"]) - _money(output["debit"])
    input_credit = _money(input_vat["debit"]) - _money(input_vat["credit"])
    return {
        "start": start,
        "end": end,
        "output_vat": output_vat,
        "input_vat": input_credit,
        "net_payable": output_vat - input_credit,
    }


# ---------------------------------------------------------------------------
# Department-wise profitability
# ---------------------------------------------------------------------------
def revenue_by_department(*, start=None, end=None) -> list[dict]:
    end = end or timezone.localdate()
    start = start or _month_start(end)
    rows = (
        JournalEntry.objects.filter(
            status=JournalStatus.POSTED,
            date__gte=start,
            date__lte=end,
            lines__account__account_type=AccountType.INCOME,
        )
        .values("lines__department__name", "lines__department_id")
        .annotate(
            debit=Coalesce(Sum("lines__debit"), Decimal("0")),
            credit=Coalesce(Sum("lines__credit"), Decimal("0")),
        )
        .order_by("-credit")
    )
    result = []
    for row in rows:
        amount = _money(row["credit"]) - _money(row["debit"])
        result.append(
            {
                "department": row["lines__department__name"] or "Unattributed",
                "amount": amount,
            }
        )
    return result


def expense_by_department(*, start=None, end=None) -> list[dict]:
    end = end or timezone.localdate()
    start = start or _month_start(end)
    rows = (
        JournalEntry.objects.filter(
            status=JournalStatus.POSTED,
            date__gte=start,
            date__lte=end,
            lines__account__account_type=AccountType.EXPENSE,
        )
        .values("lines__department__name", "lines__department_id")
        .annotate(
            debit=Coalesce(Sum("lines__debit"), Decimal("0")),
            credit=Coalesce(Sum("lines__credit"), Decimal("0")),
        )
        .order_by("-debit")
    )
    return [
        {
            "department": row["lines__department__name"] or "Unattributed",
            "amount": _money(row["debit"]) - _money(row["credit"]),
        }
        for row in rows
    ]


def department_profitability(*, start=None, end=None) -> list[dict]:
    revenue = {
        r["department"]: r["amount"]
        for r in revenue_by_department(start=start, end=end)
    }
    expense = {
        r["department"]: r["amount"]
        for r in expense_by_department(start=start, end=end)
    }
    names = sorted(set(revenue) | set(expense))
    rows = []
    for name in names:
        rev = revenue.get(name, Decimal("0"))
        exp = expense.get(name, Decimal("0"))
        rows.append(
            {
                "department": name,
                "revenue": rev,
                "expense": exp,
                "profit": rev - exp,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Doctor-wise revenue share
# ---------------------------------------------------------------------------
def doctor_revenue(*, start=None, end=None) -> list[dict]:
    from apps.opd.models import Doctor

    end = end or timezone.localdate()
    start = start or _month_start(end)
    rows = (
        JournalEntry.objects.filter(
            status=JournalStatus.POSTED,
            date__gte=start,
            date__lte=end,
            lines__doctor__isnull=False,
            lines__account__account_type=AccountType.INCOME,
        )
        .values("lines__doctor_id", "lines__doctor__name_en")
        .annotate(
            debit=Coalesce(Sum("lines__debit"), Decimal("0")),
            credit=Coalesce(Sum("lines__credit"), Decimal("0")),
        )
        .order_by("-credit")
    )
    doctors = {
        d.pk: d
        for d in Doctor.objects.filter(pk__in=[r["lines__doctor_id"] for r in rows])
    }
    result = []
    for row in rows:
        doctor = doctors.get(row["lines__doctor_id"])
        revenue = _money(row["credit"]) - _money(row["debit"])
        share_pct = (
            _money(getattr(doctor, "revenue_share_pct", 0)) if doctor else Decimal("0")
        )
        result.append(
            {
                "doctor": doctor,
                "name": row["lines__doctor__name_en"],
                "revenue": revenue,
                "share_pct": share_pct,
                "share_amount": (revenue * share_pct / Decimal("100")).quantize(
                    Decimal("0.01")
                ),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Cash / daily / monthly reporting
# ---------------------------------------------------------------------------
def daily_financial(*, day=None) -> dict:
    day = day or timezone.localdate()
    revenue = income_statement(start=day, end=day)
    output_vat = vat_return(start=day, end=day)
    cash_keys = [
        SystemAccount.CASH,
        SystemAccount.BANK,
        SystemAccount.MFS,
        SystemAccount.CARD,
    ]
    cash_lines = JournalEntry.objects.filter(
        status=JournalStatus.POSTED,
        date=day,
        lines__account__system_key__in=cash_keys,
    ).aggregate(
        debit=Coalesce(Sum("lines__debit"), Decimal("0")),
        credit=Coalesce(Sum("lines__credit"), Decimal("0")),
    )
    collections = _money(cash_lines["debit"])
    disbursements = _money(cash_lines["credit"])
    return {
        "day": day,
        "revenue": revenue["total_revenue"],
        "expense": revenue["total_expense"],
        "net_income": revenue["net_income"],
        "output_vat": output_vat["output_vat"],
        "collections": collections,
        "disbursements": disbursements,
        "net_cash": collections - disbursements,
    }


def monthly_financial(*, year=None) -> dict:
    today = timezone.localdate()
    year = year or today.year
    months = []
    for month in range(1, 13):
        start = date(year, month, 1)
        end = _add_month(start) - timedelta(days=1)
        summary = income_statement(start=start, end=end)
        months.append(
            {
                "month": start.strftime("%b"),
                "month_number": month,
                "revenue": summary["total_revenue"],
                "expense": summary["total_expense"],
                "net_income": summary["net_income"],
            }
        )
    total_revenue = sum((m["revenue"] for m in months), Decimal("0"))
    total_expense = sum((m["expense"] for m in months), Decimal("0"))
    return {
        "year": year,
        "months": months,
        "total_revenue": total_revenue,
        "total_expense": total_expense,
        "net_income": total_revenue - total_expense,
    }


# ---------------------------------------------------------------------------
# Journals & dashboard
# ---------------------------------------------------------------------------
def journal_list(
    *, status: str = "", entry_type: str = "", search: str = "", start=None, end=None
):
    qs = JournalEntry.objects.select_related("created_by", "posted_by", "period")
    if status:
        qs = qs.filter(status=status)
    if entry_type:
        qs = qs.filter(entry_type=entry_type)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    if search:
        qs = qs.filter(
            Q(entry_no__icontains=search)
            | Q(memo__icontains=search)
            | Q(reference__icontains=search)
        )
    return qs.order_by("-date", "-id")


def journal_detail(entry: JournalEntry):
    return (
        JournalEntry.objects.select_related(
            "created_by", "posted_by", "period", "reversal_of"
        )
        .prefetch_related("lines__account", "lines__department", "lines__doctor")
        .get(pk=entry.pk)
    )


def dashboard_kpis(*, start=None, end=None) -> dict:
    end = end or timezone.localdate()
    start = start or _month_start(end)
    statement = income_statement(start=start, end=end)
    ar = ar_summary()
    ap = ap_summary()
    trial = trial_balance()
    return {
        "start": start,
        "end": end,
        "revenue": statement["total_revenue"],
        "expense": statement["total_expense"],
        "net_income": statement["net_income"],
        "receivable": ar["total"],
        "payable": ap["total"],
        "cash_and_bank": cash_and_bank_balance(),
        "trial_balanced": trial["is_balanced"],
        "trial_difference": trial["difference"],
    }


def cash_and_bank_balance() -> Decimal:
    keys = [
        SystemAccount.CASH,
        SystemAccount.BANK,
        SystemAccount.MFS,
        SystemAccount.CARD,
    ]
    total = Decimal("0")
    for account in Account.objects.filter(system_key__in=keys):
        total += account.balance
    return total
