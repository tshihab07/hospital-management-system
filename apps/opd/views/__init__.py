"""OPD views (doctors, availability, appointments, queue)."""

from .appointments import (AppointmentBookingView, AppointmentCancelView,
                           AppointmentDetailView, AppointmentListView,
                           AppointmentRescheduleView, AppointmentStatusView,
                           QueueView)
from .doctors import (AvailabilityToggleView, DoctorAvailabilityView,
                      DoctorCreateView, DoctorListView, DoctorUpdateView)

__all__ = [
    "AppointmentBookingView",
    "AppointmentCancelView",
    "AppointmentDetailView",
    "AppointmentListView",
    "AppointmentRescheduleView",
    "AppointmentStatusView",
    "QueueView",
    "AvailabilityToggleView",
    "DoctorAvailabilityView",
    "DoctorCreateView",
    "DoctorListView",
    "DoctorUpdateView",
]
