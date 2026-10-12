"""Admission workflow views: advice, allocation, transfer, detail."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import (AdmissionFilterForm, AdmissionForm, BedAllocateForm,
                     BedTransferForm, ClearanceForm, DischargeRequestForm,
                     DischargeSummaryForm, IntakeOutputForm, MarForm,
                     NursingNoteForm)
from ..models import Admission, FluidType


def _admission(pk):
    return get_object_or_404(
        Admission.objects.select_related("patient", "doctor", "bed__ward", "encounter"),
        pk=pk,
    )


class AdmissionListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "ipd/admission_list.html"
    context_object_name = "admissions"
    paginate_by = 25
    permission_required = "ipd.view_admission"

    def get_queryset(self):
        self.filter_form = AdmissionFilterForm(self.request.GET or None)
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        return selectors.admission_list(
            status=data.get("status") or "",
            ward=data.get("ward"),
            search=data.get("search") or "",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_title"] = _("Inpatients")
        context["kpis"] = selectors.occupancy_kpis()
        context["bed_status"] = selectors.bed_status_counts()
        return context


class AdmissionCreateView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "ipd/admission_create.html"
    permission_required = "ipd.add_admission"

    def _context(self, form):
        return {"page_title": _("Admission advice"), "form": form}

    def get(self, request, *args, **kwargs):
        initial = {}
        patient_id = request.GET.get("patient")
        if patient_id:
            initial = {"patient": patient_id}
        return self.render_to_response(self._context(AdmissionForm(initial=initial)))

    def post(self, request, *args, **kwargs):
        form = AdmissionForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                admission = services.request_admission(
                    patient=data["patient"],
                    doctor=data["doctor"],
                    admission_type=data["admission_type"],
                    reason=data["reason"],
                    admission_note=data.get("admission_note", ""),
                    actor=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return self.render_to_response(self._context(form))
            messages.success(request, _("Admission requested."))
            return redirect("ipd:admission_detail", pk=admission.pk)
        return self.render_to_response(self._context(form))


class AdmissionDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "ipd/admission_detail.html"
    permission_required = "ipd.view_admission"

    def _context(self, admission):
        io_entries = admission.intake_output.all()
        return {
            "page_title": _("Admission %(ip)s") % {"ip": str(admission)},
            "admission": admission,
            "is_active": admission.is_active_admission,
            "clearances": admission.clearances.select_related("cleared_by"),
            "pending_clearances": admission.pending_clearance_departments,
            "charges": selectors.charge_summary(admission),
            "charge_rows": admission.daily_charges.order_by("-charge_date")[:60],
            "notes": admission.nursing_notes.select_related("nurse")[:20],
            "mar": admission.medications.select_related("drug", "given_by")[:40],
            "intake_output": io_entries.select_related("recorded_by")[:40],
            "io_totals": {
                "intake": sum(
                    io.volume_ml
                    for io in io_entries
                    if io.fluid_type == FluidType.INTAKE
                ),
                "output": sum(
                    io.volume_ml
                    for io in io_entries
                    if io.fluid_type == FluidType.OUTPUT
                ),
            },
            "transfers": selectors.recent_transfers(admission),
            "allocate_form": BedAllocateForm(),
            "transfer_form": BedTransferForm(),
            "discharge_request_form": DischargeRequestForm(),
            "clearance_form": ClearanceForm(),
            "discharge_form": DischargeSummaryForm(),
            "nursing_form": NursingNoteForm(),
            "mar_form": MarForm(),
            "intake_output_form": IntakeOutputForm(),
        }

    def get(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        return self.render_to_response(self._context(admission))


class BedAllocateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ipd.change_admission"

    def post(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        form = BedAllocateForm(request.POST)
        if form.is_valid():
            try:
                services.allocate_bed(
                    admission=admission,
                    bed=form.cleaned_data["bed"],
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    _("Bed allocated — IP number %(ip)s.")
                    % {"ip": admission.ip_number or admission.pk},
                )
                return redirect("ipd:admission_detail", pk=admission.pk)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("ipd:admission_detail", pk=admission.pk)
        messages.error(request, _("Please choose an available bed."))
        return redirect("ipd:admission_detail", pk=admission.pk)


class BedTransferView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ipd.add_bedtransfer"

    def post(self, request, *args, **kwargs):
        admission = _admission(kwargs["pk"])
        form = BedTransferForm(request.POST)
        if form.is_valid():
            try:
                transfer = services.transfer_bed(
                    admission=admission,
                    to_bed=form.cleaned_data["to_bed"],
                    reason=form.cleaned_data.get("reason", ""),
                    actor=request.user,
                    request=request,
                )
                messages.success(
                    request,
                    _("Patient moved to %(bed)s.") % {"bed": transfer.to_bed},
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect("ipd:admission_detail", pk=admission.pk)
        messages.error(request, _("Please choose a valid target bed."))
        return redirect("ipd:admission_detail", pk=admission.pk)
