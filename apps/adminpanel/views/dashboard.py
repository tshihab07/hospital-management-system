"""Control tower dashboard views."""

from __future__ import annotations

from django.views.generic import TemplateView

from core.mixins import StaffRequiredMixin
from core.utils.formatting import format_money


class DashboardHomeView(StaffRequiredMixin, TemplateView):
    """Landing control tower shown to authenticated staff at ``/admin/``.

    Renders headline operational KPIs and alerts drawn from the analytics
    selectors (RULES Phase 16). Reads are defensive: if an optional module is
    unavailable the tile falls back to a dash rather than failing the page.
    """

    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Control Tower"
        context["kpis"] = self._kpis()
        context["alerts"] = self._alerts()
        context["summary"] = self._summary()
        return context

    @staticmethod
    def _summary() -> dict:
        """Small headline figures for the control-tower panels."""
        try:
            from apps.reports import selectors as reports

            data = reports.dashboard_kpis()
        except Exception:  # pragma: no cover - defensive
            return {}
        ipd = data.get("ipd", {})
        accounting = data.get("accounting", {})
        return {
            "revenue_mtd": format_money(accounting.get("revenue_mtd", 0)),
            "expense_mtd": format_money(accounting.get("expense_mtd", 0)),
            "net_income_mtd": format_money(accounting.get("net_income_mtd", 0)),
            "beds_total": ipd.get("beds_total", 0),
            "beds_available": ipd.get("beds_available", 0),
            "beds_occupied": ipd.get("beds_occupied", 0),
        }

    @staticmethod
    def _kpis() -> list[dict]:
        """Real KPI tiles sourced from the analytics selectors."""
        try:
            from apps.reports import selectors as reports
        except Exception:  # pragma: no cover - defensive
            return []

        try:
            data = reports.dashboard_kpis()
        except Exception:  # pragma: no cover - defensive
            return []

        ipd = data.get("ipd", {})
        billing = data.get("billing", {})
        er = data.get("er", {})
        lab = data.get("lab", {})

        occupancy = ipd.get("occupancy_pct")
        return [
            {
                "label": "Bed Occupancy",
                "value": f"{occupancy}%" if occupancy is not None else "—",
                "icon": "bed-double",
                "accent": "#8B5CF6",
            },
            {
                "label": "Today's Collection",
                "value": format_money(billing.get("collected_today", 0)),
                "icon": "wallet",
                "accent": "#EAB308",
            },
            {
                "label": "ER Waiting",
                "value": str(er.get("waiting", 0)),
                "icon": "timer",
                "accent": "#F97316",
            },
            {
                "label": "Lab Pending",
                "value": str(lab.get("pending", 0)),
                "icon": "flask-conical",
                "accent": "#EF4444",
            },
        ]

    @staticmethod
    def _alerts() -> list[dict]:
        """Operational alerts for the control tower."""
        try:
            from apps.reports import selectors as reports

            return reports.dashboard_alerts()
        except Exception:  # pragma: no cover - defensive
            return []
