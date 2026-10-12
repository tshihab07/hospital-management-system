"""URLs for the EMR & CPOE (Clinical Core) module (RULES Phase 6)."""

from __future__ import annotations

from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "emr"

urlpatterns = [
    # Encounters
    path(
        "",
        RedirectView.as_view(pattern_name="emr:encounter_list", permanent=False),
        name="home",
    ),
    path("encounters/", views.EncounterListView.as_view(), name="encounter_list"),
    path("encounters/open/", views.EncounterOpenView.as_view(), name="encounter_open"),
    path(
        "encounters/<int:pk>/",
        views.EncounterDetailView.as_view(),
        name="encounter_detail",
    ),
    path(
        "encounters/<int:pk>/close/",
        views.EncounterCloseView.as_view(),
        name="encounter_close",
    ),
    path("encounters/<int:pk>/soap/", views.SoapSaveView.as_view(), name="soap_save"),
    path(
        "encounters/<int:pk>/vitals/",
        views.VitalCreateView.as_view(),
        name="vital_create",
    ),
    path(
        "encounters/<int:pk>/diagnoses/",
        views.VisitDiagnosisCreateView.as_view(),
        name="diagnosis_create",
    ),
    path(
        "diagnoses/<int:pk>/delete/",
        views.VisitDiagnosisDeleteView.as_view(),
        name="diagnosis_delete",
    ),
    # Patient longitudinal record
    path(
        "patients/<int:pk>/timeline/",
        views.PatientTimelineView.as_view(),
        name="patient_timeline",
    ),
    path(
        "patients/<int:pk>/problems/",
        views.ProblemListView.as_view(),
        name="problem_list",
    ),
    path(
        "problems/<int:pk>/resolve/",
        views.ProblemResolveView.as_view(),
        name="problem_resolve",
    ),
    path(
        "patients/<int:pk>/allergies/",
        views.AllergyListView.as_view(),
        name="allergy_list",
    ),
    # Prescriptions
    path(
        "encounters/<int:pk>/prescriptions/new/",
        views.PrescriptionCreateView.as_view(),
        name="prescription_create",
    ),
    path(
        "prescriptions/",
        views.PrescriptionListView.as_view(),
        name="prescription_list",
    ),
    path(
        "prescriptions/<int:pk>/",
        views.PrescriptionDetailView.as_view(),
        name="prescription_detail",
    ),
    path(
        "prescriptions/<int:pk>/cancel/",
        views.PrescriptionCancelView.as_view(),
        name="prescription_cancel",
    ),
    path(
        "prescriptions/<int:pk>/print/",
        views.PrescriptionPrintView.as_view(),
        name="prescription_print",
    ),
    path(
        "prescriptions/<int:pk>/pdf/",
        views.PrescriptionPdfView.as_view(),
        name="prescription_pdf",
    ),
    # Diagnostic & procedure orders
    path(
        "encounters/<int:pk>/lab-orders/new/",
        views.LabOrderCreateView.as_view(),
        name="lab_order_create",
    ),
    path(
        "encounters/<int:pk>/radiology-orders/new/",
        views.RadiologyOrderCreateView.as_view(),
        name="radiology_order_create",
    ),
    path(
        "encounters/<int:pk>/procedure-orders/new/",
        views.ProcedureOrderCreateView.as_view(),
        name="procedure_order_create",
    ),
    path(
        "orders/<str:kind>/<int:pk>/status/",
        views.OrderStatusView.as_view(),
        name="order_status",
    ),
    # Attachments
    path(
        "patients/<int:pk>/attachments/",
        views.AttachmentListView.as_view(),
        name="attachment_list",
    ),
    path(
        "attachments/<int:pk>/remove/",
        views.AttachmentRemoveView.as_view(),
        name="attachment_remove",
    ),
    # SOAP templates
    path(
        "soap-templates/",
        views.SoapTemplateListView.as_view(),
        name="soap_template_list",
    ),
    path(
        "soap-templates/new/",
        views.SoapTemplateCreateView.as_view(),
        name="soap_template_create",
    ),
]
