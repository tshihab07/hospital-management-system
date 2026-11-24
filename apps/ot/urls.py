"""URL patterns for the Operation Theatre module (namespace ``ot``)."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "ot"

urlpatterns = [
    path("", views.SurgeryListView.as_view(), name="surgery_list"),
    path("surgeries/new/", views.SurgeryCreateView.as_view(), name="surgery_create"),
    path(
        "surgeries/<int:pk>/reschedule/",
        views.SurgeryRescheduleView.as_view(),
        name="surgery_reschedule",
    ),
    path(
        "surgeries/<int:pk>/cancel/",
        views.SurgeryCancelView.as_view(),
        name="surgery_cancel",
    ),
    path(
        "surgeries/<int:pk>/checklist/",
        views.PreOpChecklistView.as_view(),
        name="preop_checklist",
    ),
    path(
        "surgeries/<int:pk>/anesthesia/",
        views.AnesthesiaView.as_view(),
        name="anesthesia",
    ),
    path(
        "surgeries/<int:pk>/note/intraop/",
        views.IntraOpNoteView.as_view(),
        name="intraop_note",
    ),
    path(
        "surgeries/<int:pk>/note/postop/",
        views.PostOpNoteView.as_view(),
        name="postop_note",
    ),
    path(
        "surgeries/<int:pk>/team/add/",
        views.TeamCreateView.as_view(),
        name="team_add",
    ),
    path(
        "surgeries/<int:pk>/implants/add/",
        views.ImplantCreateView.as_view(),
        name="implant_add",
    ),
    path(
        "surgeries/<int:pk>/consumables/add/",
        views.ConsumableView.as_view(),
        name="consumable_add",
    ),
    path(
        "surgeries/<int:pk>/", views.SurgeryDetailView.as_view(), name="surgery_detail"
    ),
    # Keep the generic action route last so it does not shadow the named routes.
    path(
        "surgeries/<int:pk>/<str:action>/",
        views.SurgeryActionView.as_view(),
        name="surgery_action",
    ),
    path("calendar/", views.OTCalendarView.as_view(), name="calendar"),
    path("utilization/", views.UtilizationView.as_view(), name="utilization"),
    path("rooms/", views.RoomListView.as_view(), name="room_list"),
    path("rooms/new/", views.RoomCreateView.as_view(), name="room_create"),
]
