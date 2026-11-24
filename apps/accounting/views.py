"""Thin views for the Accounting & Financial Reports module (RULES Phase 13).

Views validate input, delegate writes to :mod:`apps.accounting.services`, reads
to :mod:`apps.accounting.selectors`, and render a template or redirect. Reports
support ``?export=csv`` / ``?export=xlsx`` via :mod:`apps.accounting.exports`.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from . import exports, selectors, services
from .forms import (
    AccountForm,
    AsOfForm,
    DateRangeForm,
    ExpenseForm,
    JournalEntryForm,
    JournalLineFormSet,
    VendorPaymentForm,
)
from .models import (
    Account,
    AccountingPeriod,
    AccountType,
    Expense,
    JournalEntry,
    JournalStatus,
    VendorPayment,
)

VIEW_ACCOUNT = "accounting.view_account"
ADD_ACCOUNT = "accounting.add_account"
CHANGE_ACCOUNT = "accounting.change_account"
VIEW_JOURNAL = "accounting.view_journalentry"
ADD_JOURNAL = "accounting.add_journalentry"
POST_JOURNAL = "accounting.post_journalentry"
REVERSE_JOURNAL = "accounting.reverse_journalentry"
VIEW_REPORTS = "accounting.view_accountingreports"
VIEW_EXPENSE = "accounting.view_expense"
ADD_EXPENSE = "accounting.add_expense"
VIEW_VENDOR_PAYMENT = "accounting.view_vendorpayment"
ADD_VENDOR_PAYMENT = "accounting.add_vendorpayment"
VIEW_PERIOD = "accounting.view_accountingperiod"
CLOSE_PERIOD = "accounting.close_accountingperiod"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _date_param(request, key):
    raw = request.GET.get(key)
    return parse_date(raw) if raw else None


def _window(request, *, default_month=True):
    """Read ``start``/``end`` from the query string with sane defaults."""
    end = _date_param(request, "end") or timezone.localdate()
    start = _date_param(request, "start")
    if start is None and default_month:
        start = end.replace(day=1)
    return start, end


def _maybe_export(request, *, filename, headers, rows, title=""):
    return exports.export_response(
        request, filename=filename, headers=headers, rows=rows, title=title
    )


def _money_str(value) -> str:
    return f"{value:.2f}"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/dashboard.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        start, end = _window(request)
        return self.render_to_response(
            {
                "page_title": _("Accounting · Dashboard"),
                "kpis": selectors.dashboard_kpis(start=start, end=end),
                "recent_journals": selectors.journal_list()[:10],
                "receivables": selectors.ar_summary(),
                "payables": selectors.ap_summary(),
            }
        )


# ---------------------------------------------------------------------------
# Chart of accounts
# ---------------------------------------------------------------------------
class ChartOfAccountsView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/chart.html"
    permission_required = VIEW_ACCOUNT

    def get(self, request, *args, **kwargs):
        account_type = request.GET.get("account_type", "")
        search = request.GET.get("search", "").strip()
        export = _maybe_export(
            request,
            filename="chart-of-accounts",
            title=_("Chart of accounts"),
            headers=["Code", "Name", "Type", "Group", "Active"],
            rows=[
                [
                    a.code,
                    a.name,
                    a.get_account_type_display(),
                    "Yes" if a.is_group else "No",
                    "Yes" if a.is_active else "No",
                ]
                for a in selectors.chart_of_accounts(
                    account_type=account_type, search=search, active_only=False
                )
            ],
        )
        if export is not None:
            return export
        tree = selectors.account_tree()
        balances = selectors.account_balances()
        for row in tree:
            row["balance"] = balances.get(row["account"].pk, Decimal("0"))
        return self.render_to_response(
            {
                "page_title": _("Chart of accounts"),
                "tree": tree,
                "account_type": account_type,
                "account_types": AccountType.choices,
                "search": search,
            }
        )


class AccountCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_ACCOUNT

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "accounting/account_form.html",
            {"form": AccountForm(), "page_title": _("New account")},
        )

    def post(self, request, *args, **kwargs):
        form = AccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.created_by = request.user
            account.save()
            messages.success(request, _("Account created."))
            return redirect("accounting:chart")
        return render(
            request,
            "accounting/account_form.html",
            {"form": form, "page_title": _("New account")},
        )


class AccountUpdateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = CHANGE_ACCOUNT

    def get(self, request, pk, *args, **kwargs):
        account = get_object_or_404(Account, pk=pk)
        return render(
            request,
            "accounting/account_form.html",
            {
                "form": AccountForm(instance=account),
                "account": account,
                "page_title": _("Edit account"),
            },
        )

    def post(self, request, pk, *args, **kwargs):
        account = get_object_or_404(Account, pk=pk)
        form = AccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, _("Account updated."))
            return redirect("accounting:chart")
        return render(
            request,
            "accounting/account_form.html",
            {"form": form, "account": account, "page_title": _("Edit account")},
        )


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
class LedgerView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/ledger.html"
    permission_required = VIEW_REPORTS

    def get(self, request, pk=None, *args, **kwargs):
        accounts = selectors.chart_of_accounts(active_only=False)
        account_pk = pk or request.GET.get("account") or None
        account = get_object_or_404(Account, pk=account_pk) if account_pk else None
        ledger = None
        if account is not None:
            start, end = _window(request, default_month=False)
            party_type = request.GET.get("party_type", "")
            party_id = request.GET.get("party_id", "")
            ledger = selectors.account_ledger(
                account, start=start, end=end, party_type=party_type, party_id=party_id
            )
            _running = ledger["opening"]
            for line in ledger["rows"]:
                _running += selectors._signed(account, line.debit, line.credit)
                line.running_balance = _running
            export = _maybe_export(
                request,
                filename=f"ledger-{account.code}",
                title=_("Ledger") + f" · {account.display_name}",
                headers=["Date", "Entry", "Description", "Debit", "Credit", "Balance"],
                rows=self._export_rows(ledger),
            )
            if export is not None:
                return export
        return self.render_to_response(
            {
                "page_title": _("General ledger"),
                "accounts": accounts,
                "account": account,
                "ledger": ledger,
                "form": DateRangeForm(
                    initial={
                        "start": _date_param(request, "start"),
                        "end": _date_param(request, "end"),
                    }
                ),
            }
        )

    @staticmethod
    def _export_rows(ledger):
        rows = [["", "", _("Opening balance"), "", "", _money_str(ledger["opening"])]]
        balance = ledger["opening"]
        for line in ledger["rows"]:
            balance += selectors._signed(ledger["account"], line.debit, line.credit)
            rows.append(
                [
                    line.journal.date.isoformat(),
                    line.journal.entry_no,
                    line.description or line.journal.memo,
                    _money_str(line.debit) if line.debit else "",
                    _money_str(line.credit) if line.credit else "",
                    _money_str(balance),
                ]
            )
        rows.append(
            [
                "",
                "",
                _("Closing balance"),
                _money_str(ledger["total_debit"]),
                _money_str(ledger["total_credit"]),
                _money_str(ledger["closing"]),
            ]
        )
        return rows


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class TrialBalanceView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/trial_balance.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        as_of = _date_param(request, "as_of") or timezone.localdate()
        include_zero = request.GET.get("include_zero") == "1"
        tb = selectors.trial_balance(as_of=as_of, include_zero=include_zero)
        export = _maybe_export(
            request,
            filename="trial-balance",
            title=_("Trial balance"),
            headers=["Code", "Account", "Debit", "Credit"],
            rows=[
                [
                    r["account"].code,
                    r["account"].name,
                    _money_str(r["debit"]),
                    _money_str(r["credit"]),
                ]
                for r in tb["rows"]
            ]
            + [
                [
                    "",
                    _("Total"),
                    _money_str(tb["total_debit"]),
                    _money_str(tb["total_credit"]),
                ]
            ],
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Trial balance"),
                "tb": tb,
                "form": AsOfForm(initial={"as_of": as_of}),
                "include_zero": include_zero,
            }
        )


class IncomeStatementView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/income_statement.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        start, end = _window(request)
        statement = selectors.income_statement(start=start, end=end)
        export = _maybe_export(
            request,
            filename="income-statement",
            title=_("Income statement"),
            headers=["Code", "Account", "Amount"],
            rows=[
                [r["account"].code, r["account"].name, _money_str(r["amount"])]
                for r in statement["revenue_rows"]
            ]
            + [["", _("Total revenue"), _money_str(statement["total_revenue"])]]
            + [
                [r["account"].code, r["account"].name, _money_str(r["amount"])]
                for r in statement["expense_rows"]
            ]
            + [
                ["", _("Total expenses"), _money_str(statement["total_expense"])],
                ["", _("Net income"), _money_str(statement["net_income"])],
            ],
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Income statement"),
                "statement": statement,
                "form": DateRangeForm(initial={"start": start, "end": end}),
            }
        )


class BalanceSheetView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/balance_sheet.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        as_of = _date_param(request, "as_of") or timezone.localdate()
        bs = selectors.balance_sheet(as_of=as_of)
        export = _maybe_export(
            request,
            filename="balance-sheet",
            title=_("Balance sheet"),
            headers=["Section", "Code", "Account", "Amount"],
            rows=(
                [
                    [
                        "Asset",
                        r["account"].code,
                        r["account"].name,
                        _money_str(r["amount"]),
                    ]
                    for r in bs["assets"]
                ]
                + [
                    [
                        "Liabilities",
                        r["account"].code,
                        r["account"].name,
                        _money_str(r["amount"]),
                    ]
                    for r in bs["liabilities"]
                ]
                + [
                    [
                        "Equity",
                        r["account"].code,
                        r["account"].name,
                        _money_str(r["amount"]),
                    ]
                    for r in bs["equity"]
                ]
            ),
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Balance sheet"),
                "bs": bs,
                "form": AsOfForm(initial={"as_of": as_of}),
            }
        )


class ReceivablesView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/receivables.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        aging = selectors.ar_aging()
        export = _maybe_export(
            request,
            filename="receivables-aging",
            title=_("Accounts receivable aging"),
            headers=["Bill", "Patient", "Due", "Age (days)", "Bucket"],
            rows=[
                [
                    r["bill"].bill_no,
                    str(r["bill"].patient),
                    _money_str(r["due"]),
                    r["age"],
                    r["bucket"],
                ]
                for r in aging["rows"]
            ],
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Accounts receivable"),
                "aging": aging,
                "summary": selectors.ar_summary(),
            }
        )


class PayablesView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/payables.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        aging = selectors.ap_aging()
        export = _maybe_export(
            request,
            filename="payables-aging",
            title=_("Accounts payable aging"),
            headers=["GRN", "Vendor", "Due", "Age (days)", "Bucket"],
            rows=[
                [
                    r["grn"].grn_number,
                    str(r["vendor"]),
                    _money_str(r["due"]),
                    r["age"],
                    r["bucket"],
                ]
                for r in aging["rows"]
            ],
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Accounts payable"),
                "aging": aging,
                "summary": selectors.ap_summary(),
            }
        )


class VatReturnView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/vat_return.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        start, end = _window(request)
        vat = selectors.vat_return(start=start, end=end)
        export = _maybe_export(
            request,
            filename="vat-return",
            title=_("VAT return"),
            headers=["Item", "Amount"],
            rows=[
                [_("Output VAT"), _money_str(vat["output_vat"])],
                [_("Input VAT"), _money_str(vat["input_vat"])],
                [_("Net payable"), _money_str(vat["net_payable"])],
            ],
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("VAT return"),
                "vat": vat,
                "form": DateRangeForm(initial={"start": start, "end": end}),
            }
        )


class DepartmentRevenueView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/department_revenue.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        start, end = _window(request)
        rows = selectors.department_profitability(start=start, end=end)
        export = _maybe_export(
            request,
            filename="department-profitability",
            title=_("Department profitability"),
            headers=["Department", "Revenue", "Expense", "Profit"],
            rows=[
                [
                    r["department"],
                    _money_str(r["revenue"]),
                    _money_str(r["expense"]),
                    _money_str(r["profit"]),
                ]
                for r in rows
            ],
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Department profitability"),
                "rows": rows,
                "form": DateRangeForm(initial={"start": start, "end": end}),
            }
        )


class DoctorRevenueView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/doctor_revenue.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        start, end = _window(request)
        rows = selectors.doctor_revenue(start=start, end=end)
        export = _maybe_export(
            request,
            filename="doctor-revenue",
            title=_("Doctor revenue share"),
            headers=["Doctor", "Revenue", "Share %", "Share amount"],
            rows=[
                [
                    r["name"],
                    _money_str(r["revenue"]),
                    _money_str(r["share_pct"]),
                    _money_str(r["share_amount"]),
                ]
                for r in rows
            ],
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Doctor revenue share"),
                "rows": rows,
                "form": DateRangeForm(initial={"start": start, "end": end}),
            }
        )


class DailyReportView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/daily_report.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        day = _date_param(request, "day") or timezone.localdate()
        report = selectors.daily_financial(day=day)
        export = _maybe_export(
            request,
            filename=f"daily-financial-{day.isoformat()}",
            title=_("Daily financial report"),
            headers=["Item", "Amount"],
            rows=[
                [_("Revenue"), _money_str(report["revenue"])],
                [_("Expense"), _money_str(report["expense"])],
                [_("Net income"), _money_str(report["net_income"])],
                [_("Output VAT"), _money_str(report["output_vat"])],
                [_("Collections"), _money_str(report["collections"])],
                [_("Disbursements"), _money_str(report["disbursements"])],
                [_("Net cash"), _money_str(report["net_cash"])],
            ],
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Daily financial report"),
                "report": report,
            }
        )


class MonthlyReportView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/monthly_report.html"
    permission_required = VIEW_REPORTS

    def get(self, request, *args, **kwargs):
        try:
            year = int(request.GET.get("year") or timezone.localdate().year)
        except (TypeError, ValueError):
            year = timezone.localdate().year
        report = selectors.monthly_financial(year=year)
        export = _maybe_export(
            request,
            filename=f"monthly-financial-{year}",
            title=_("Monthly financial report"),
            headers=["Month", "Revenue", "Expense", "Net income"],
            rows=[
                [
                    m["month"],
                    _money_str(m["revenue"]),
                    _money_str(m["expense"]),
                    _money_str(m["net_income"]),
                ]
                for m in report["months"]
            ]
            + [
                [
                    "",
                    _money_str(report["total_revenue"]),
                    _money_str(report["total_expense"]),
                    _money_str(report["net_income"]),
                ]
            ],
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Monthly financial report"),
                "report": report,
                "years": range(
                    timezone.localdate().year, timezone.localdate().year - 6, -1
                ),
            }
        )


# ---------------------------------------------------------------------------
# Journals
# ---------------------------------------------------------------------------
class JournalListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "accounting/journal_list.html"
    context_object_name = "journals"
    paginate_by = 25
    permission_required = VIEW_JOURNAL

    def get_queryset(self):
        self.status = self.request.GET.get("status", "")
        self.entry_type = self.request.GET.get("entry_type", "")
        self.search = self.request.GET.get("search", "")
        start, end = _window(self.request, default_month=False)
        return selectors.journal_list(
            status=self.status,
            entry_type=self.entry_type,
            search=self.search,
            start=start,
            end=end,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page_title": _("Journal entries"),
                "status": self.status,
                "entry_type": self.entry_type,
                "search": self.search,
                "statuses": JournalStatus.choices,
                "entry_types": JournalEntry.entry_type.field.choices,
            }
        )
        return context


class JournalDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "accounting/journal_detail.html"
    permission_required = VIEW_JOURNAL

    def get(self, request, pk, *args, **kwargs):
        entry = get_object_or_404(JournalEntry, pk=pk)
        entry = selectors.journal_detail(entry)
        return self.render_to_response(
            {"page_title": _("Journal %(no)s") % {"no": entry.entry_no}, "entry": entry}
        )


class JournalCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_JOURNAL

    def _context(self, form, formset):
        return {
            "form": form,
            "formset": formset,
            "page_title": _("New journal entry"),
        }

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "accounting/journal_form.html",
            self._context(JournalEntryForm(), JournalLineFormSet()),
        )

    def post(self, request, *args, **kwargs):
        form = JournalEntryForm(request.POST)
        formset = JournalLineFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            lines = []
            for line in formset:
                data = line.cleaned_data
                if not data or not data.get("account"):
                    continue
                lines.append(
                    {
                        "account": data["account"],
                        "description": data.get("description", ""),
                        "debit": data.get("debit") or 0,
                        "credit": data.get("credit") or 0,
                    }
                )
            try:
                entry = services.create_journal_entry(
                    date=form.cleaned_data["date"],
                    lines=lines,
                    memo=form.cleaned_data.get("memo", ""),
                    reference=form.cleaned_data.get("reference", ""),
                    actor=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, _("Journal entry posted."))
                return redirect("accounting:journal_detail", pk=entry.pk)
        return render(
            request, "accounting/journal_form.html", self._context(form, formset)
        )


class JournalActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    def get_permission_required(self):
        return (
            [POST_JOURNAL] if self.kwargs.get("action") == "post" else [REVERSE_JOURNAL]
        )

    def post(self, request, pk, action, *args, **kwargs):
        entry = get_object_or_404(JournalEntry, pk=pk)
        try:
            if action == "post":
                services.post_journal_entry(entry, actor=request.user, request=request)
                messages.success(request, _("Journal entry posted."))
            elif action == "reverse":
                services.reverse_journal_entry(
                    entry, actor=request.user, request=request
                )
                messages.success(request, _("Journal entry reversed."))
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("accounting:journal_detail", pk=pk)


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------
class ExpenseListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "accounting/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 25
    permission_required = VIEW_EXPENSE

    def get_queryset(self):
        start, end = _window(self.request, default_month=False)
        qs = Expense.objects.select_related(
            "category", "paid_from", "vendor", "journal"
        )
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        return qs.order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Expenses")
        return context


class ExpenseCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_EXPENSE

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "accounting/expense_form.html",
            {"form": ExpenseForm(), "page_title": _("New expense")},
        )

    def post(self, request, *args, **kwargs):
        form = ExpenseForm(request.POST)
        if form.is_valid():
            try:
                services.create_expense(
                    category=form.cleaned_data["category"],
                    paid_from=form.cleaned_data["paid_from"],
                    amount=form.cleaned_data["amount"],
                    description=form.cleaned_data["description"],
                    date=form.cleaned_data["date"],
                    vendor=form.cleaned_data.get("vendor"),
                    reference=form.cleaned_data.get("reference", ""),
                    actor=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, _("Expense recorded."))
                return redirect("accounting:expense_list")
        return render(
            request,
            "accounting/expense_form.html",
            {"form": form, "page_title": _("New expense")},
        )


# ---------------------------------------------------------------------------
# Vendor payments
# ---------------------------------------------------------------------------
class VendorPaymentListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView
):
    template_name = "accounting/vendor_payment_list.html"
    context_object_name = "payments"
    paginate_by = 25
    permission_required = VIEW_VENDOR_PAYMENT

    def get_queryset(self):
        return VendorPayment.objects.select_related(
            "vendor", "grn", "journal"
        ).order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Vendor payments")
        return context


class VendorPaymentCreateView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View
):
    permission_required = ADD_VENDOR_PAYMENT

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "accounting/vendor_payment_form.html",
            {"form": VendorPaymentForm(), "page_title": _("New vendor payment")},
        )

    def post(self, request, *args, **kwargs):
        form = VendorPaymentForm(request.POST)
        if form.is_valid():
            try:
                services.create_vendor_payment(
                    vendor=form.cleaned_data["vendor"],
                    amount=form.cleaned_data["amount"],
                    method=form.cleaned_data["method"],
                    date=form.cleaned_data["date"],
                    grn=form.cleaned_data.get("grn"),
                    reference=form.cleaned_data.get("reference", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, _("Vendor payment recorded."))
                return redirect("accounting:vendor_payment_list")
        return render(
            request,
            "accounting/vendor_payment_form.html",
            {"form": form, "page_title": _("New vendor payment")},
        )


# ---------------------------------------------------------------------------
# Fiscal periods
# ---------------------------------------------------------------------------
class PeriodListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "accounting/period_list.html"
    context_object_name = "periods"
    paginate_by = 24
    permission_required = VIEW_PERIOD

    def get_queryset(self):
        return AccountingPeriod.objects.select_related("closed_by").order_by(
            "-start_date"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Accounting periods")
        return context


class PeriodActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = CLOSE_PERIOD

    def post(self, request, pk, action, *args, **kwargs):
        period = get_object_or_404(AccountingPeriod, pk=pk)
        if action == "close":
            services.close_period(period, actor=request.user, request=request)
            messages.success(request, _("Period closed."))
        else:
            messages.error(request, _("Unknown action."))
        return redirect("accounting:period_list")
