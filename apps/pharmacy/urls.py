"""URL routes for the Pharmacy & Inventory module."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "pharmacy"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    # Dispensing
    path("dispense/", views.DispenseListView.as_view(), name="dispense"),
    path(
        "dispense/new/<int:pk>/",
        views.DispenseCreateView.as_view(),
        name="dispense_create",
    ),
    path(
        "dispense/<int:pk>/", views.DispenseDetailView.as_view(), name="dispense_detail"
    ),
    # Stock
    path("stock/", views.StockListView.as_view(), name="stock_list"),
    path("stock/batch/new/", views.BatchCreateView.as_view(), name="batch_create"),
    path("stock/transfer/", views.TransferView.as_view(), name="stock_transfer"),
    path("stock/batch/<int:pk>/", views.BatchDetailView.as_view(), name="batch_detail"),
    path(
        "stock/batch/<int:pk>/<str:action>/",
        views.BatchActionView.as_view(),
        name="batch_action",
    ),
    # Alerts
    path("expiry/", views.ExpiryAlertsView.as_view(), name="expiry_alerts"),
    path("low-stock/", views.LowStockView.as_view(), name="low_stock"),
    # Vendors
    path("vendors/", views.VendorListView.as_view(), name="vendor_list"),
    path("vendors/new/", views.VendorCreateView.as_view(), name="vendor_create"),
    # Requisitions
    path("requisitions/", views.RequisitionListView.as_view(), name="requisition_list"),
    path(
        "requisitions/<int:pk>/<str:action>/",
        views.RequisitionActionView.as_view(),
        name="requisition_action",
    ),
    # Purchase orders
    path("purchase-orders/", views.POListView.as_view(), name="po_list"),
    path("purchase-orders/<int:pk>/", views.PODetailView.as_view(), name="po_detail"),
    path(
        "purchase-orders/<int:pk>/<str:action>/",
        views.POActionView.as_view(),
        name="po_action",
    ),
    # Goods receipt notes
    path("grn/", views.GRNListView.as_view(), name="grn_list"),
    path("grn/new/<int:pk>/", views.GRNCreateView.as_view(), name="grn_create"),
    path("grn/<int:pk>/", views.GRNDetailView.as_view(), name="grn_detail"),
]
