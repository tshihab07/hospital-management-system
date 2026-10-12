"""Discharge workflow views: order, clearance, finalisation, summary PDF."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from apps.masters.models import HospitalProfile
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import services
from ..forms import ClearanceForm, DischargeRequestForm, DischargeSummaryForm
from ..models import Admission


def _admission(pk):
    from django.shortcuts import get_object_or_404

    return get_object_or_404(
        Admission.objects.select_related("patient", "doctor", "bed__ward"),
        pk=pk,
    )


class DischargeRequestView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ipd.change_admission"

    def post(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        form = DischargeRequestForm(request.POST)
        if form.is_valid():
            try:
                services.mark_discharge_request(
                    admission=admission,
                    reason=form.cleaned_data["reason"],
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Discharge ordered."))
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect("ipd:admission_detail", pk=admission.pk)
        messages.error(request, _("Please provide a discharge reason."))
        return redirect("ipd:admission_detail", pk=admission.pk)


class ClearanceView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ipd.change_dischargeclearance"

    def post(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        form = ClearanceForm(request.POST)
        if form.is_valid():
            services.set_clearance(
                admission=admission,
                department=form.cleaned_data["department"],
                cleared=request.POST.get("cleared") == "on"
                or request.POST.get("cleared") == "1",
                notes=form.cleaned_data.get("notes", ""),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Clearance updated."))
        return redirect("ipd:admission_detail", pk=admission.pk)


class DischargeView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ("ipd.change_admission", "ipd.add_dischargesummary")

    def post(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        form = DischargeSummaryForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Please review the discharge summary fields."))
            return redirect("ipd:admission_detail", pk=admission.pk)
        try:
            services.discharge(
                admission=admission,
                summary_data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("ipd:admission_detail", pk=admission.pk)
        messages.success(request, _("Patient discharged."))
        return redirect("ipd:discharge_summary", pk=admission.pk)


class DischargeSummaryView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "ipd/discharge_summary.html"
    permission_required = "ipd.view_dischargesummary"

    def get(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        summary = admission.discharge_summary
        if summary is None:
            messages.info(request, _("No discharge summary yet."))
            return redirect("ipd:admission_detail", pk=admission.pk)
        return self.render_to_response(
            {
                "page_title": _("Discharge summary · %(name)s")
                % {"name": admission.patient.display_name},
                "admission": admission,
                "discharge_summary": summary,
                "hospital": HospitalProfile.load(),
                "pdf_mode": False,
            }
        )


class DischargeSummaryPdfView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View
):
    permission_required = "ipd.view_dischargesummary"

    def get(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        summary = admission.discharge_summary
        if summary is None:
            messages.info(request, _("No discharge summary yet."))
            return redirect("ipd:admission_detail", pk=admission.pk)
        try:
            from weasyprint import HTML
        except ImportError:  # pragma: no cover - defensive
            return redirect("ipd:discharge_summary", pk=admission.pk)
        context = {
            "admission": admission,
            "discharge_summary": summary,
            "hospital": HospitalProfile.load(),
            "pdf_mode": True,
        }
        html = render_to_string("ipd/discharge_summary.html", context, request=request)
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="discharge-{admission.ip_number or admission.pk}.pdf"'
        )
        return response
