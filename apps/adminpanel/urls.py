"""URLs for the custom IHMS admin panel (mounted at ``/admin/``)."""

from django.urls import path

from .views.dashboard import DashboardHomeView

app_name = "panel"

urlpatterns = [
    path("", DashboardHomeView.as_view(), name="home"),
]
