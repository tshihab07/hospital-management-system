"""URLs for the Doctor & Staff Management module."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "hr"

urlpatterns = [
    # Staff
    path("", views.StaffListView.as_view(), name="staff_list"),
    path("staff/", views.StaffListView.as_view(), name="staff_list"),
    path("staff/new/", views.StaffCreateView.as_view(), name="staff_create"),
    path("staff/<int:pk>/", views.StaffDetailView.as_view(), name="staff_detail"),
    path("staff/<int:pk>/edit/", views.StaffUpdateView.as_view(), name="staff_update"),
    # Shifts
    path("shifts/", views.ShiftListView.as_view(), name="shift_list"),
    path("shifts/new/", views.ShiftCreateView.as_view(), name="shift_create"),
    path("shifts/<int:pk>/edit/", views.ShiftUpdateView.as_view(), name="shift_update"),
    # Roster
    path("roster/", views.RosterView.as_view(), name="roster"),
    path(
        "roster/generate/", views.RosterGenerateView.as_view(), name="roster_generate"
    ),
    path("roster/publish/", views.RosterPublishView.as_view(), name="roster_publish"),
    # Attendance
    path("attendance/", views.AttendanceListView.as_view(), name="attendance_list"),
    path(
        "attendance/mark/", views.AttendanceUpsertView.as_view(), name="attendance_mark"
    ),
    path(
        "attendance/<int:pk>/edit/",
        views.AttendanceUpsertView.as_view(),
        name="attendance_edit",
    ),
    path(
        "attendance/import/",
        views.AttendanceImportView.as_view(),
        name="attendance_import",
    ),
    # Leave
    path("leave-types/", views.LeaveTypeListView.as_view(), name="leave_type_list"),
    path(
        "leave-types/new/",
        views.LeaveTypeCreateView.as_view(),
        name="leave_type_create",
    ),
    path("leave/", views.LeaveListView.as_view(), name="leave_list"),
    path("leave/apply/", views.LeaveApplyView.as_view(), name="leave_apply"),
    path("leave/<int:pk>/", views.LeaveDetailView.as_view(), name="leave_detail"),
    path(
        "leave/<int:pk>/decide/", views.LeaveDecisionView.as_view(), name="leave_decide"
    ),
    path(
        "leave/<int:pk>/cancel/", views.LeaveCancelView.as_view(), name="leave_cancel"
    ),
    # Performance
    path(
        "performance/",
        views.DoctorPerformanceView.as_view(),
        name="doctor_performance",
    ),
]
