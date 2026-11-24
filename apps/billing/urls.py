"""URL routes for the Billing & Payments module."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    # Patient ledger
    path("ledger/", views.LedgerView.as_view(), name="ledger"),
    path("ledger/<int:pk>/", views.LedgerView.as_view(), name="ledger_detail"),
    # Bills
    path("bills/", views.BillListView.as_view(), name="bill_list"),
    path("bills/new/", views.BillCreateView.as_view(), name="bill_create"),
    path("bills/<int:pk>/", views.BillDetailView.as_view(), name="bill_detail"),
    path(
        "bills/<int:pk>/pay/",
        views.PaymentCreateView.as_view(),
        name="payment_create",
    ),
    path(
        "bills/<int:pk>/discount/<str:action>/",
        views.DiscountActionView.as_view(),
        name="discount_action",
    ),
    path(
        "bills/<int:pk>/pay-online/",
        views.OnlinePaymentView.as_view(),
        name="pay_online",
    ),
    path(
        "bills/<int:pk>/credit-note/",
        views.CreditNoteCreateView.as_view(),
        name="credit_note_create",
    ),
    path(
        "bills/<int:pk>/<str:action>/",
        views.BillActionView.as_view(),
        name="bill_action",
    ),
    # Online gateway
    path(
        "gateway/confirm/<str:txn>/",
        views.GatewayConfirmView.as_view(),
        name="gateway_confirm",
    ),
    # Payments & receipts
    path("payments/", views.PaymentListView.as_view(), name="payment_list"),
    path(
        "collections/daily/",
        views.DailyCollectionView.as_view(),
        name="daily_collection",
    ),
    path("receipts/<int:pk>/", views.ReceiptView.as_view(), name="receipt"),
    path("receipts/<int:pk>/pdf/", views.ReceiptPdfView.as_view(), name="receipt_pdf"),
    # Advances
    path("advances/", views.AdvanceListView.as_view(), name="advance_list"),
    path("advances/new/", views.AdvanceCreateView.as_view(), name="advance_create"),
    # Refunds
    path("refunds/", views.RefundListView.as_view(), name="refund_list"),
    path("refunds/new/", views.RefundCreateView.as_view(), name="refund_create"),
    path(
        "refunds/<int:pk>/<str:action>/",
        views.RefundActionView.as_view(),
        name="refund_action",
    ),
    # Credit notes
    path("credit-notes/", views.CreditNoteListView.as_view(), name="credit_note_list"),
    path(
        "credit-notes/<int:pk>/<str:action>/",
        views.CreditNoteActionView.as_view(),
        name="credit_note_action",
    ),
    # Service packages
    path("packages/", views.PackageListView.as_view(), name="package_list"),
    path(
        "packages/bill/",
        views.PackageBillCreateView.as_view(),
        name="package_bill_create",
    ),
]
