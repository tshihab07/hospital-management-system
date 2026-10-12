from __future__ import annotations

from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "ipd"

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="ipd:admission_list", permanent=False),
        name="home",
    ),
    # Admission workflow
    path("admissions/", views.AdmissionListView.as_view(), name="admission_list"),
    path(
        "admissions/new/", views.AdmissionCreateView.as_view(), name="admission_create"
    ),
    path(
        "admissions/<int:pk>/",
        views.AdmissionDetailView.as_view(),
        name="admission_detail",
    ),
    path(
        "admissions/<int:pk>/allocate/",
        views.BedAllocateView.as_view(),
        name="admission_allocate",
    ),
    path(
        "admissions/<int:pk>/transfer/",
        views.BedTransferView.as_view(),
        name="admission_transfer",
    ),
    # Discharge workflow
    path(
        "admissions/<int:pk>/discharge/request/",
        views.DischargeRequestView.as_view(),
        name="discharge_request",
    ),
    path(
        "admissions/<int:pk>/discharge/clearance/",
        views.ClearanceView.as_view(),
        name="discharge_clearance",
    ),
    path(
        "admissions/<int:pk>/discharge/",
        views.DischargeView.as_view(),
        name="discharge",
    ),
    path(
        "discharge/<int:pk>/",
        views.DischargeSummaryView.as_view(),
        name="discharge_summary",
    ),
    path(
        "discharge/<int:pk>/pdf/",
        views.DischargeSummaryPdfView.as_view(),
        name="discharge_summary_pdf",
    ),
    # Inpatient care & bed map
    path("bed-map/", views.BedMapView.as_view(), name="bed_map"),
    path(
        "admissions/<int:pk>/nursing-note/",
        views.NursingNoteCreateView.as_view(),
        name="nursing_note_create",
    ),
    path(
        "admissions/<int:pk>/mar/",
        views.MarCreateView.as_view(),
        name="mar_create",
    ),
    path(
        "admissions/<int:pk>/intake-output/",
        views.IntakeOutputCreateView.as_view(),
        name="intake_output_create",
    ),
]
