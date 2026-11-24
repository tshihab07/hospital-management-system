"""URL routes for the Payroll module (RULES Phase 14)."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "payroll"

urlpatterns = [
    # Runs
    path("", views.RunListView.as_view(), name="run_list"),
    path("runs/", views.RunListView.as_view(), name="run_list"),
    path("runs/new/", views.RunCreateView.as_view(), name="run_create"),
    path("runs/<int:pk>/", views.RunDetailView.as_view(), name="run_detail"),
    path(
        "runs/<int:pk>/bank-file/",
        views.RunBankFileView.as_view(),
        name="run_bank_file",
    ),
    path("runs/<int:pk>/register/", views.RegisterView.as_view(), name="register"),
    path(
        "runs/<int:pk>/<str:action>/",
        views.RunActionView.as_view(),
        name="run_action",
    ),
    # Payslips
    path(
        "payslips/<int:pk>/", views.PayslipDetailView.as_view(), name="payslip_detail"
    ),
    path("payslips/<int:pk>/pdf/", views.PayslipPdfView.as_view(), name="payslip_pdf"),
    # Salary structure
    path(
        "salary-structure/",
        views.SalaryStructureView.as_view(),
        name="salary_structure",
    ),
    # Adjustments
    path("adjustments/", views.AdjustmentListView.as_view(), name="adjustment_list"),
    path(
        "adjustments/new/",
        views.AdjustmentCreateView.as_view(),
        name="adjustment_create",
    ),
    path(
        "adjustments/<int:pk>/<str:action>/",
        views.AdjustmentActionView.as_view(),
        name="adjustment_action",
    ),
    # Tax slabs
    path("tax-slabs/", views.TaxSlabListView.as_view(), name="tax_slab_list"),
    path("tax-slabs/new/", views.TaxSlabCreateView.as_view(), name="tax_slab_create"),
    path(
        "tax-slabs/<int:pk>/edit/",
        views.TaxSlabUpdateView.as_view(),
        name="tax_slab_update",
    ),
    # Settings
    path("settings/", views.PayrollSettingView.as_view(), name="settings"),
]
