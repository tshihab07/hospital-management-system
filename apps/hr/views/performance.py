"""Doctor performance report (patients seen + revenue share)."""

from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors
from ..forms import PerformanceFilterForm


class DoctorPerformanceView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "hr/doctor_performance.html"
    permission_required = "opd.view_doctor"

    def get(self, request, *args, **kwargs):
        today = timezone.localdate()
        form = PerformanceFilterForm(
            request.GET or None, initial={"year": today.year, "month": today.month}
        )
        if form.is_valid():
            year = form.cleaned_data["year"]
            month = form.cleaned_data["month"]
        else:
            year, month = today.year, today.month
        context = {
            "page_title": _("Doctor Performance"),
            "form": form,
            "year": year,
            "month": month,
            "rows": selectors.doctor_performance(year=year, month=month),
        }
        return self.render_to_response(context)
