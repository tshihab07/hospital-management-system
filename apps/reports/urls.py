"""URL routes for the Reports & Analytics module (RULES Phase 16)."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    # Reports
    path("daily-census/", views.DailyCensusView.as_view(), name="daily_census"),
    path(
        "monthly-revenue/",
        views.MonthlyRevenueView.as_view(),
        name="monthly_revenue",
    ),
    path(
        "doctor-performance/",
        views.DoctorPerformanceView.as_view(),
        name="doctor_performance",
    ),
    path(
        "department-profitability/",
        views.DepartmentProfitabilityView.as_view(),
        name="department_profitability",
    ),
    path(
        "inventory-consumption/",
        views.InventoryConsumptionView.as_view(),
        name="inventory_consumption",
    ),
    path("bed-occupancy/", views.BedOccupancyView.as_view(), name="bed_occupancy"),
    path("er-wait-times/", views.ErWaitTimesView.as_view(), name="er_wait_times"),
    path("vat/", views.VatReportView.as_view(), name="vat"),
    path("collection/", views.CollectionReportView.as_view(), name="collection"),
    path("payroll/", views.PayrollReportView.as_view(), name="payroll"),
    path("pnl/", views.ProfitAndLossView.as_view(), name="pnl"),
    # Schedules
    path("schedules/", views.ScheduleListView.as_view(), name="schedule_list"),
    path(
        "schedules/new/",
        views.ScheduleCreateView.as_view(),
        name="schedule_create",
    ),
    path(
        "schedules/<int:pk>/edit/",
        views.ScheduleUpdateView.as_view(),
        name="schedule_update",
    ),
    path(
        "schedules/<int:pk>/delete/",
        views.ScheduleDeleteView.as_view(),
        name="schedule_delete",
    ),
    path(
        "schedules/<int:pk>/run/",
        views.ScheduleRunNowView.as_view(),
        name="schedule_run",
    ),
    # Runs
    path("runs/", views.RunListView.as_view(), name="run_list"),
    path("runs/<int:pk>/", views.RunDetailView.as_view(), name="run_detail"),
    path("runs/<int:pk>/download/", views.RunDownloadView.as_view(), name="run_download"),
]
