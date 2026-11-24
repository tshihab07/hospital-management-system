"""URL routes for the Patient Portal (RULES Phase 15)."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    # Auth
    path("", views.PortalDashboardView.as_view(), name="dashboard"),
    path("register/", views.PortalRegisterView.as_view(), name="register"),
    path("verify/", views.PortalVerifyView.as_view(), name="verify"),
    path("verify/resend/", views.PortalResendView.as_view(), name="resend"),
    path("login/", views.PortalLoginView.as_view(), name="login"),
    path("logout/", views.PortalLogoutView.as_view(), name="logout"),
    # Appointments
    path("appointments/", views.AppointmentListView.as_view(), name="appointments"),
    path(
        "appointments/book/",
        views.AppointmentBookView.as_view(),
        name="appointment_book",
    ),
    path(
        "appointments/<int:pk>/cancel/",
        views.AppointmentCancelView.as_view(),
        name="appointment_cancel",
    ),
    path(
        "appointments/<int:pk>/reschedule/",
        views.AppointmentRescheduleView.as_view(),
        name="appointment_reschedule",
    ),
    # Clinical documents
    path("lab-reports/", views.LabReportListView.as_view(), name="lab_reports"),
    path(
        "lab-reports/<int:pk>/pdf/",
        views.LabReportPdfView.as_view(),
        name="lab_report_pdf",
    ),
    path(
        "discharge-summaries/",
        views.DischargeSummaryListView.as_view(),
        name="discharge_summaries",
    ),
    path(
        "discharge-summaries/<int:pk>/",
        views.DischargeSummaryDetailView.as_view(),
        name="discharge_summary_detail",
    ),
    path(
        "discharge-summaries/<int:pk>/pdf/",
        views.DischargeSummaryPdfView.as_view(),
        name="discharge_summary_pdf",
    ),
    # Bills & payment
    path("bills/", views.BillListView.as_view(), name="bills"),
    path("bills/<int:pk>/", views.BillDetailView.as_view(), name="bill_detail"),
    path("bills/<int:pk>/pay/", views.BillPayView.as_view(), name="bill_pay"),
    path(
        "gateway/<str:txn>/",
        views.PortalGatewayConfirmView.as_view(),
        name="gateway_confirm",
    ),
    # Profile / notifications / records
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("notifications/", views.NotificationPreferenceView.as_view(), name="notifications"),
    path(
        "record-requests/",
        views.RecordRequestListView.as_view(),
        name="record_requests",
    ),
]
