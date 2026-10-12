"""Inpatient care views: bed map, nursing notes, MAR, intake/output."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import (IntakeOutputForm, MarForm, NursingNoteForm,
                     WardTypeFilterForm)


def _admission(pk):
    from ..models import Admission

    return get_object_or_404(Admission, pk=pk)


class BedMapView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "ipd/bed_map.html"
    permission_required = ("ipd.view_ward", "ipd.view_bed")

    def get(self, request, *args, **kwargs):
        ward_type = request.GET.get("ward_type", "")
        return self.render_to_response(
            {
                "page_title": _("Ward & bed map"),
                "wards": selectors.ward_bed_map(ward_type=ward_type),
                "kpis": selectors.bed_kpis(),
                "ward_type_filter": WardTypeFilterForm(
                    initial={"ward_type": ward_type or ""}
                ),
            }
        )


class NursingNoteCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ipd.add_nursingnote"

    def post(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        form = NursingNoteForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.record_nursing_note(
                admission=admission,
                note=data["note"],
                shift=data["shift"],
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Nursing note recorded."))
        else:
            messages.error(request, _("Please review the note."))
        return redirect("ipd:admission_detail", pk=admission.pk)


class MarCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ipd.add_medicationadministration"

    def post(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        form = MarForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.record_mar(
                admission=admission,
                drug=data["drug"],
                dose=data["dose"],
                route=data["route"],
                scheduled_for=data["scheduled_for"],
                action=data["action"],
                notes=data.get("notes", ""),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("MAR entry recorded."))
        else:
            messages.error(request, _("Please review the MAR entry."))
        return redirect("ipd:admission_detail", pk=admission.pk)


class IntakeOutputCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ipd.add_intakeoutput"

    def post(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        form = IntakeOutputForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.record_intake_output(
                admission=admission,
                fluid_type=data["fluid_type"],
                category=data["category"],
                volume_ml=data["volume_ml"],
                shift=data["shift"],
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Intake/output recorded."))
        else:
            messages.error(request, _("Please review the intake/output entry."))
        return redirect("ipd:admission_detail", pk=admission.pk)
