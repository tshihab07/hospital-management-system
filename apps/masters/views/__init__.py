"""Master-data views."""

from .base import (MasterCreateView, MasterDeleteView, MasterListView,
                   MasterToggleActiveView, MasterUpdateView)
from .dashboard import MastersHomeView
from .hospital import HospitalProfileView
from .importer import MasterImportView

__all__ = [
    "MastersHomeView",
    "HospitalProfileView",
    "MasterListView",
    "MasterCreateView",
    "MasterUpdateView",
    "MasterDeleteView",
    "MasterToggleActiveView",
    "MasterImportView",
]
