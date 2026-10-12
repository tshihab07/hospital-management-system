"""HR views (staff, shifts, roster, attendance, leave, performance)."""

from .attendance import (AttendanceImportView, AttendanceListView,
                         AttendanceUpsertView)
from .leave import (LeaveApplyView, LeaveCancelView, LeaveDecisionView,
                    LeaveDetailView, LeaveListView, LeaveTypeCreateView,
                    LeaveTypeListView)
from .performance import DoctorPerformanceView
from .roster import RosterGenerateView, RosterPublishView, RosterView
from .shifts import ShiftCreateView, ShiftListView, ShiftUpdateView
from .staff import (StaffCreateView, StaffDetailView, StaffListView,
                    StaffUpdateView)

__all__ = [
    "AttendanceImportView",
    "AttendanceListView",
    "AttendanceUpsertView",
    "LeaveApplyView",
    "LeaveCancelView",
    "LeaveDecisionView",
    "LeaveDetailView",
    "LeaveListView",
    "LeaveTypeCreateView",
    "LeaveTypeListView",
    "DoctorPerformanceView",
    "RosterGenerateView",
    "RosterPublishView",
    "RosterView",
    "ShiftCreateView",
    "ShiftListView",
    "ShiftUpdateView",
    "StaffCreateView",
    "StaffDetailView",
    "StaffListView",
    "StaffUpdateView",
]
