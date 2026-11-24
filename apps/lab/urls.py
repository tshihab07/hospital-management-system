"""URL configuration for the Laboratory & Radiology module."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "lab"

urlpatterns = [
    # Lab orders / samples / results
    path("orders/", views.LabOrderListView.as_view(), name="order_list"),
    path("orders/<int:pk>/", views.LabOrderDetailView.as_view(), name="order_detail"),
    path(
        "orders/<int:pk>/sample/create/",
        views.SampleCreateView.as_view(),
        name="sample_create",
    ),
    path(
        "orders/<int:pk>/results/",
        views.ResultEntryView.as_view(),
        name="result_entry",
    ),
    path(
        "orders/<int:pk>/report/",
        views.ReportDetailView.as_view(),
        name="report_detail",
    ),
    path(
        "orders/<int:pk>/report/pdf/",
        views.ReportPdfView.as_view(),
        name="report_pdf",
    ),
    path(
        "orders/<int:pk>/report/<str:action>/",
        views.ReportActionView.as_view(),
        name="report_action",
    ),
    path("samples/", views.SampleListView.as_view(), name="sample_list"),
    path(
        "samples/<int:pk>/<str:action>/",
        views.SampleActionView.as_view(),
        name="sample_action",
    ),
    path("results/", views.ResultListView.as_view(), name="result_list"),
    path(
        "results/<int:pk>/verify/",
        views.ResultVerifyView.as_view(),
        name="result_verify",
    ),
    path(
        "results/<int:pk>/addendum/",
        views.ResultAddendumView.as_view(),
        name="result_addendum",
    ),
    # Radiology
    path("radiology/", views.RadiologyListView.as_view(), name="radiology_list"),
    path(
        "radiology/<int:pk>/",
        views.RadiologyDetailView.as_view(),
        name="radiology_detail",
    ),
    path(
        "radiology/<int:pk>/<str:action>/",
        views.RadiologyActionView.as_view(),
        name="radiology_action",
    ),
]
