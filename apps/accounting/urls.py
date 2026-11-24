"""URL routes for the Accounting & Financial Reports module."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "accounting"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    # Chart of accounts
    path("chart/", views.ChartOfAccountsView.as_view(), name="chart"),
    path("accounts/new/", views.AccountCreateView.as_view(), name="account_create"),
    path(
        "accounts/<int:pk>/edit/",
        views.AccountUpdateView.as_view(),
        name="account_update",
    ),
    # General ledger
    path("ledger/", views.LedgerView.as_view(), name="ledger"),
    path("ledger/<int:pk>/", views.LedgerView.as_view(), name="ledger_detail"),
    # Core reports
    path("trial-balance/", views.TrialBalanceView.as_view(), name="trial_balance"),
    path(
        "income-statement/",
        views.IncomeStatementView.as_view(),
        name="income_statement",
    ),
    path("balance-sheet/", views.BalanceSheetView.as_view(), name="balance_sheet"),
    path("receivables/", views.ReceivablesView.as_view(), name="receivables"),
    path("payables/", views.PayablesView.as_view(), name="payables"),
    path("vat-return/", views.VatReturnView.as_view(), name="vat_return"),
    path(
        "department-revenue/",
        views.DepartmentRevenueView.as_view(),
        name="department_revenue",
    ),
    path("doctor-revenue/", views.DoctorRevenueView.as_view(), name="doctor_revenue"),
    path("daily-report/", views.DailyReportView.as_view(), name="daily_report"),
    path("monthly-report/", views.MonthlyReportView.as_view(), name="monthly_report"),
    # Journals
    path("journals/", views.JournalListView.as_view(), name="journal_list"),
    path("journals/new/", views.JournalCreateView.as_view(), name="journal_create"),
    path(
        "journals/<int:pk>/", views.JournalDetailView.as_view(), name="journal_detail"
    ),
    path(
        "journals/<int:pk>/<str:action>/",
        views.JournalActionView.as_view(),
        name="journal_action",
    ),
    # Expenses
    path("expenses/", views.ExpenseListView.as_view(), name="expense_list"),
    path("expenses/new/", views.ExpenseCreateView.as_view(), name="expense_create"),
    # Vendor payments
    path(
        "vendor-payments/",
        views.VendorPaymentListView.as_view(),
        name="vendor_payment_list",
    ),
    path(
        "vendor-payments/new/",
        views.VendorPaymentCreateView.as_view(),
        name="vendor_payment_create",
    ),
    # Fiscal periods
    path("periods/", views.PeriodListView.as_view(), name="period_list"),
    path(
        "periods/<int:pk>/<str:action>/",
        views.PeriodActionView.as_view(),
        name="period_action",
    ),
]
