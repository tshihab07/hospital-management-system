"""URLs for the OPD module."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "opd"

urlpatterns = [
    path("doctors/", views.DoctorListView.as_view(), name="doctor_list"),
    path("doctors/new/", views.DoctorCreateView.as_view(), name="doctor_create"),
    path(
        "doctors/<int:pk>/edit/", views.DoctorUpdateView.as_view(), name="doctor_update"
    ),
    path(
        "doctors/<int:pk>/availability/",
        views.DoctorAvailabilityView.as_view(),
        name="doctor_availability",
    ),
    path(
        "availability/<int:pk>/toggle/",
        views.AvailabilityToggleView.as_view(),
        name="availability_toggle",
    ),
    path("appointments/", views.AppointmentListView.as_view(), name="appointment_list"),
    path(
        "appointments/book/",
        views.AppointmentBookingView.as_view(),
        name="appointment_book",
    ),
    path(
        "appointments/<int:pk>/",
        views.AppointmentDetailView.as_view(),
        name="appointment_detail",
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
    path(
        "appointments/<int:pk>/status/",
        views.AppointmentStatusView.as_view(),
        name="appointment_status",
    ),
    path("queue/", views.QueueView.as_view(), name="queue"),
]
