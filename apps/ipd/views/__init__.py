"""View package for the IPD module — re-exports every view class."""

from __future__ import annotations

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .admissions import (AdmissionCreateView, AdmissionDetailView,
                         AdmissionListView, BedAllocateView, BedTransferView)
from .care import (BedMapView, IntakeOutputCreateView, MarCreateView,
                   NursingNoteCreateView)
from .discharge import (ClearanceView, DischargeRequestView,
                        DischargeSummaryPdfView, DischargeSummaryView,
                        DischargeView)

__all__ = [
    "IHMSLoginRequiredMixin",
    "IHMSPermissionRequiredMixin",
    "AdmissionListView",
    "AdmissionCreateView",
    "AdmissionDetailView",
    "BedAllocateView",
    "BedTransferView",
    "BedMapView",
    "NursingNoteCreateView",
    "MarCreateView",
    "IntakeOutputCreateView",
    "ClearanceView",
    "DischargeRequestView",
    "DischargeView",
    "DischargeSummaryView",
    "DischargeSummaryPdfView",
]
