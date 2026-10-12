"""URL configuration for master data (`app_name = "masters"`)."""

from django.urls import path

from . import views

app_name = "masters"

urlpatterns = [
    path("", views.MastersHomeView.as_view(), name="home"),
    path("hospital/", views.HospitalProfileView.as_view(), name="hospital_profile"),
    path("<slug:slug>/", views.MasterListView.as_view(), name="master_list"),
    path("<slug:slug>/new/", views.MasterCreateView.as_view(), name="master_create"),
    path(
        "<slug:slug>/import/",
        views.MasterImportView.as_view(),
        name="master_import",
    ),
    path(
        "<slug:slug>/<int:pk>/edit/",
        views.MasterUpdateView.as_view(),
        name="master_update",
    ),
    path(
        "<slug:slug>/<int:pk>/delete/",
        views.MasterDeleteView.as_view(),
        name="master_delete",
    ),
    path(
        "<slug:slug>/<int:pk>/toggle/",
        views.MasterToggleActiveView.as_view(),
        name="master_toggle",
    ),
]
