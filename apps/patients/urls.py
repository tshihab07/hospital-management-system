"""URL configuration for patients (`app_name = "patients"`)."""

from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.PatientListView.as_view(), name="list"),
    path("new/", views.PatientCreateView.as_view(), name="create"),
    path("export/", views.PatientExportView.as_view(), name="export"),
    path("merge/", views.PatientMergeView.as_view(), name="merge"),
    path("<int:pk>/", views.PatientDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.PatientUpdateView.as_view(), name="update"),
    path("<int:pk>/delete/", views.PatientDeleteView.as_view(), name="delete"),
    path("<int:pk>/restore/", views.PatientRestoreView.as_view(), name="restore"),
    path(
        "<int:pk>/documents/add/",
        views.DocumentCreateView.as_view(),
        name="document_create",
    ),
    path(
        "documents/<int:pk>/delete/",
        views.DocumentDeleteView.as_view(),
        name="document_delete",
    ),
]
