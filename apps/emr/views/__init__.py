"""EMR & CPOE views (encounters, records, CPOE orders, attachments, templates)."""

from .encounters import (EncounterCloseView, EncounterDetailView,
                         EncounterListView, EncounterOpenView, SoapSaveView,
                         VisitDiagnosisCreateView, VisitDiagnosisDeleteView,
                         VitalCreateView)
from .library import (AttachmentListView, AttachmentRemoveView,
                      SoapTemplateCreateView, SoapTemplateListView)
from .orders import (LabOrderCreateView, OrderStatusView,
                     PrescriptionCancelView, PrescriptionCreateView,
                     PrescriptionDetailView, PrescriptionListView,
                     PrescriptionPdfView, PrescriptionPrintView,
                     ProcedureOrderCreateView, RadiologyOrderCreateView)
from .records import (AllergyListView, PatientTimelineView, ProblemListView,
                      ProblemResolveView)

__all__ = [
    "EncounterListView",
    "EncounterOpenView",
    "EncounterDetailView",
    "EncounterCloseView",
    "SoapSaveView",
    "VitalCreateView",
    "VisitDiagnosisCreateView",
    "VisitDiagnosisDeleteView",
    "PatientTimelineView",
    "ProblemListView",
    "ProblemResolveView",
    "AllergyListView",
    "PrescriptionCreateView",
    "PrescriptionListView",
    "PrescriptionDetailView",
    "PrescriptionCancelView",
    "PrescriptionPrintView",
    "PrescriptionPdfView",
    "LabOrderCreateView",
    "RadiologyOrderCreateView",
    "ProcedureOrderCreateView",
    "OrderStatusView",
    "AttachmentListView",
    "AttachmentRemoveView",
    "SoapTemplateListView",
    "SoapTemplateCreateView",
]
