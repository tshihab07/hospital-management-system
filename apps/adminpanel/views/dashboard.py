"""Control tower dashboard views."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class DashboardHomeView(LoginRequiredMixin, TemplateView):
    """Landing control tower shown to authenticated staff at ``/admin/``."""

    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Control Tower"
        context["kpis"] = self._kpis()
        return context

    @staticmethod
    def _kpis() -> list[dict]:
        """Placeholder KPI tiles until the analytics phase wires real metrics."""
        return [
            {
                "label": "Bed Occupancy",
                "value": "—",
                "icon": "bed-double",
                "accent": "#8B5CF6",
            },
            {
                "label": "Today's Revenue",
                "value": "—",
                "icon": "wallet",
                "accent": "#EAB308",
            },
            {
                "label": "ER Wait Time",
                "value": "—",
                "icon": "timer",
                "accent": "#F97316",
            },
            {
                "label": "Critical Alerts",
                "value": "—",
                "icon": "alert-triangle",
                "accent": "#EF4444",
            },
        ]
