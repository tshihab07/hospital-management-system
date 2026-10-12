"""Patient views."""

from .detail import (PatientDeleteView, PatientDetailView, PatientRestoreView,
                     PatientUpdateView)
from .documents import DocumentCreateView, DocumentDeleteView
from .list import PatientExportView, PatientListView
from .merge import PatientMergeView
from .registration import PatientCreateView

__all__ = [
    "PatientListView",
    "PatientExportView",
    "PatientCreateView",
    "PatientDetailView",
    "PatientUpdateView",
    "PatientDeleteView",
    "PatientRestoreView",
    "DocumentCreateView",
    "DocumentDeleteView",
    "PatientMergeView",
]
