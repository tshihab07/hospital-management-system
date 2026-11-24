from __future__ import annotations

from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "icu"

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="icu:record_list", permanent=False),
        name="home",
    ),
    # ICU / CCU charting
    path("records/", views.IcuRecordListView.as_view(), name="record_list"),
    path(
        "records/<int:pk>/",
        views.AdmissionChartsView.as_view(),
        name="admission_charts",
    ),
    path(
        "records/<int:pk>/chart/",
        views.IcuRecordCreateView.as_view(),
        name="record_create",
    ),
    path(
        "records/<int:pk>/score/",
        views.ScoreCreateView.as_view(),
        name="score_create",
    ),
    # Critical alerts
    path("alerts/", views.AlertListView.as_view(), name="alert_list"),
    path(
        "alerts/<int:pk>/acknowledge/",
        views.AlertActionView.as_view(action="acknowledge"),
        name="alert_acknowledge",
    ),
    path(
        "alerts/<int:pk>/resolve/",
        views.AlertActionView.as_view(action="resolve"),
        name="alert_resolve",
    ),
    # Emergency
    path("emergency/", views.EmergencyListView.as_view(), name="emergency_list"),
    path(
        "emergency/new/",
        views.EmergencyRegisterView.as_view(),
        name="emergency_register",
    ),
    path(
        "emergency/<int:pk>/",
        views.EmergencyDetailView.as_view(),
        name="emergency_detail",
    ),
    path(
        "emergency/<int:pk>/triage/",
        views.EmergencyTriageView.as_view(),
        name="emergency_triage",
    ),
    path(
        "emergency/<int:pk>/status/",
        views.EmergencyStatusView.as_view(),
        name="emergency_status",
    ),
    path(
        "emergency/<int:pk>/convert/",
        views.EmergencyConvertView.as_view(),
        name="emergency_convert",
    ),
    path(
        "emergency/<int:pk>/discharge/",
        views.EmergencyDischargeView.as_view(),
        name="emergency_discharge",
    ),
    # Code Blue
    path("code-blue/", views.CodeBlueListView.as_view(), name="code_blue_list"),
    path("code-blue/new/", views.CodeBlueRaiseView.as_view(), name="code_blue_raise"),
    path(
        "code-blue/<int:pk>/resolve/",
        views.CodeBlueResolveView.as_view(),
        name="code_blue_resolve",
    ),
    # Shift handover
    path("handover/", views.HandoverListView.as_view(), name="handover_list"),
    path("handover/new/", views.HandoverCreateView.as_view(), name="handover_create"),
    path(
        "handover/<int:pk>/acknowledge/",
        views.HandoverAcknowledgeView.as_view(),
        name="handover_acknowledge",
    ),
]
