"""Encounter lifecycle & in-consultation documentation views (RULES Phase 6)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, View
from django.views.generic.base import TemplateResponseMixin

from apps.opd.models import Appointment
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import (EncounterFilterForm, EncounterOpenForm, SoapNoteForm,
                     VisitDiagnosisForm, VitalForm)
from ..models import Encounter, EncounterStatus


class EncounterListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "emr/encounter_list.html"
    context_object_name = "encounters"
    paginate_by = 30
    permission_required = "emr.view_encounter"

    def get_queryset(self):
        self.filter_form = EncounterFilterForm(self.request.GET or None)
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        self.enc_date = data.get("enc_date")
        self.doctor = data.get("doctor")
        return selectors.encounter_list(
            doctor=self.doctor,
            status=data.get("status") or "",
            encounter_type=data.get("encounter_type") or "",
            search=data.get("q") or "",
            enc_date=self.enc_date,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_title"] = _("Encounters")
        context["summary"] = selectors.encounter_summary(
            self.doctor, enc_date=self.enc_date
        )
        return context


class EncounterOpenView(
    IHMSLoginRequiredMixin,
    IHMSPermissionRequiredMixin,
    TemplateResponseMixin,
    View,
):
    template_name = "emr/encounter_open.html"
    permission_required = "emr.add_encounter"

    def _context(self, form, appointment=None):
        return {
            "page_title": _("Open Encounter"),
            "form": form,
            "appointment": appointment,
        }

    def _appointment(self, request):
        appt_id = request.GET.get("appointment") or request.POST.get("appointment")
        if not appt_id:
            return None
        return get_object_or_404(
            Appointment.objects.select_related("patient", "doctor"), pk=appt_id
        )

    def get(self, request, *args, **kwargs):
        appointment = self._appointment(request)
        if appointment is not None:
            existing = Encounter.objects.filter(appointment=appointment).first()
            if existing is not None:
                return redirect("emr:encounter_detail", pk=existing.pk)
        initial = {}
        patient_id = request.GET.get("patient")
        if appointment is not None:
            initial = {"patient": appointment.patient, "doctor": appointment.doctor}
        elif patient_id:
            initial = {"patient": patient_id}
        form = EncounterOpenForm(initial=initial)
        return self.render_to_response(self._context(form, appointment))

    def post(self, request, *args, **kwargs):
        appointment = self._appointment(request)
        form = EncounterOpenForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            patient = appointment.patient if appointment else data["patient"]
            doctor = appointment.doctor if appointment else data["doctor"]
            encounter, _created = services.open_encounter(
                patient=patient,
                doctor=doctor,
                appointment=appointment,
                encounter_type=data["encounter_type"],
                chief_complaint=data["chief_complaint"],
                actor=request.user,
                request=request,
            )
            if appointment is not None:
                self._start_consultation(appointment, request)
            messages.success(request, _("Encounter opened."))
            return redirect("emr:encounter_detail", pk=encounter.pk)
        return self.render_to_response(self._context(form, appointment))

    @staticmethod
    def _start_consultation(appointment, request):
        """Best-effort: move the linked appointment into consultation.

        OPD enforces a linear flow (scheduled → arrived → in_consultation),
        so a still-scheduled appointment is first advanced to arrived.
        """
        from apps.opd import services as opd_services
        from apps.opd.models import AppointmentStatus

        if appointment.status == AppointmentStatus.SCHEDULED:
            try:
                opd_services.set_status(
                    instance=appointment,
                    status=AppointmentStatus.ARRIVED,
                    actor=request.user,
                    request=request,
                )
            except (ValueError, KeyError):  # pragma: no cover - defensive
                appointment.refresh_from_db()
        if appointment.status == AppointmentStatus.ARRIVED:
            try:
                opd_services.set_status(
                    instance=appointment,
                    status=AppointmentStatus.IN_CONSULTATION,
                    actor=request.user,
                    request=request,
                )
            except (ValueError, KeyError):  # pragma: no cover - defensive
                pass


class EncounterDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView
):
    model = Encounter
    template_name = "emr/encounter_detail.html"
    context_object_name = "encounter"
    permission_required = "emr.view_encounter"

    def get_queryset(self):
        return Encounter.objects.select_related("patient", "doctor", "appointment")

    def _soap_initial(self):
        soap = getattr(self.object, "soap", None)
        if soap is None:
            return {}
        return {
            "template": soap.template_id,
            "subjective": soap.subjective,
            "objective": soap.objective,
            "assessment": soap.assessment,
            "plan": soap.plan,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        encounter = self.object
        context.update(
            {
                "page_title": _("Encounter · %(name)s")
                % {"name": encounter.patient.display_name},
                "soap": getattr(encounter, "soap", None),
                "soap_form": SoapNoteForm(initial=self._soap_initial()),
                "vital_form": VitalForm(),
                "diagnosis_form": VisitDiagnosisForm(),
                "orders": selectors.encounter_orders(encounter),
                "vitals": encounter.vitals.select_related("recorded_by")[:10],
                "diagnoses": encounter.diagnoses.select_related("diagnosis"),
                "problems": selectors.active_problems(encounter.patient),
                "allergies": selectors.patient_allergies(encounter.patient),
                "is_open": encounter.is_open,
            }
        )
        return context


class EncounterCloseView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "emr.change_encounter"

    def post(self, request, *args, **kwargs):
        encounter = get_object_or_404(
            Encounter.objects.select_related("appointment"), pk=kwargs["pk"]
        )
        if encounter.status == EncounterStatus.CLOSED:
            messages.info(request, _("Encounter is already closed."))
        else:
            services.close_encounter(
                instance=encounter, actor=request.user, request=request
            )
            self._complete_consultation(encounter.appointment, request)
            messages.success(request, _("Encounter closed."))
        return redirect("emr:encounter_detail", pk=encounter.pk)

    @staticmethod
    def _complete_consultation(appointment, request):
        """Best-effort: complete the linked OPD appointment when in consult."""
        from apps.opd import services as opd_services
        from apps.opd.models import AppointmentStatus

        if (
            appointment is not None
            and appointment.status == AppointmentStatus.IN_CONSULTATION
        ):
            try:
                opd_services.set_status(
                    instance=appointment,
                    status=AppointmentStatus.COMPLETED,
                    actor=request.user,
                    request=request,
                )
            except (ValueError, KeyError):  # pragma: no cover - defensive
                pass


class SoapSaveView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "emr.change_soapnote"

    def post(self, request, *args, **kwargs):
        encounter = get_object_or_404(Encounter, pk=kwargs["pk"])
        form = SoapNoteForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.save_soap_note(
                encounter=encounter,
                subjective=data["subjective"],
                objective=data["objective"],
                assessment=data["assessment"],
                plan=data["plan"],
                template=data.get("template"),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("SOAP note saved."))
        else:
            messages.error(request, _("Could not save the SOAP note."))
        return redirect("emr:encounter_detail", pk=encounter.pk)


class VitalCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "emr.add_vital"

    def post(self, request, *args, **kwargs):
        encounter = get_object_or_404(Encounter, pk=kwargs["pk"])
        form = VitalForm(request.POST)
        if form.is_valid():
            services.record_vitals(
                encounter=encounter,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Vitals recorded."))
        else:
            messages.error(request, _("Could not record vitals."))
        return redirect("emr:encounter_detail", pk=encounter.pk)


class VisitDiagnosisCreateView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View
):
    permission_required = "emr.add_visitdiagnosis"

    def post(self, request, *args, **kwargs):
        encounter = get_object_or_404(Encounter, pk=kwargs["pk"])
        form = VisitDiagnosisForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.add_visit_diagnosis(
                encounter=encounter,
                diagnosis=data.get("diagnosis"),
                description=data.get("description", ""),
                is_primary=data.get("is_primary", False),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Diagnosis added."))
        else:
            messages.error(request, _("Could not add the diagnosis."))
        return redirect("emr:encounter_detail", pk=encounter.pk)


class VisitDiagnosisDeleteView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View
):
    permission_required = "emr.delete_visitdiagnosis"

    def post(self, request, *args, **kwargs):
        from ..models import VisitDiagnosis

        entry = get_object_or_404(VisitDiagnosis, pk=kwargs["pk"])
        encounter_id = entry.encounter_id
        services.remove_visit_diagnosis(
            instance=entry, actor=request.user, request=request
        )
        messages.success(request, _("Diagnosis removed."))
        return redirect("emr:encounter_detail", pk=encounter_id)
