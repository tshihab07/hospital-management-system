"""Patient timeline, problem list and allergy register views (RULES Phase 6)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from apps.patients.models import Patient
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import AllergyForm, ProblemForm
from ..models import Allergy, ProblemListEntry


class PatientTimelineView(
    IHMSLoginRequiredMixin,
    IHMSPermissionRequiredMixin,
    TemplateResponseMixin,
    View,
):
    template_name = "emr/patient_timeline.html"
    permission_required = "emr.view_encounter"

    def get(self, request, *args, **kwargs):
        patient = get_object_or_404(Patient, pk=kwargs["pk"])
        context = {
            "page_title": _("EMR · %(name)s") % {"name": patient.display_name},
            "patient": patient,
            "timeline": selectors.patient_timeline(patient),
            "encounters": selectors.patient_encounters(patient)[:20],
            "problems": selectors.active_problems(patient),
            "allergies": selectors.patient_allergies(patient),
            "vitals": selectors.latest_vitals(patient),
            "prescriptions": selectors.prescription_list(patient=patient)[:10],
        }
        return self.render_to_response(context)


class ProblemListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "emr/problem_list.html"
    permission_required = "emr.view_problemlistentry"

    def _context(self, patient, form=None):
        return {
            "page_title": _("Problem List · %(name)s") % {"name": patient.display_name},
            "patient": patient,
            "problems": ProblemListEntry.objects.filter(patient=patient).select_related(
                "diagnosis"
            ),
            "form": form or ProblemForm(),
        }

    def get(self, request, *args, **kwargs):
        patient = get_object_or_404(Patient, pk=kwargs["pk"])
        return self.render_to_response(self._context(patient))

    def post(self, request, *args, **kwargs):
        patient = get_object_or_404(Patient, pk=kwargs["pk"])
        form = ProblemForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.add_problem(
                patient=patient,
                description=data["description"],
                diagnosis=data.get("diagnosis"),
                onset_date=data.get("onset_date"),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Problem added to the list."))
            return redirect("emr:problem_list", pk=patient.pk)
        return self.render_to_response(self._context(patient, form))


class ProblemResolveView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "emr.change_problemlistentry"

    def post(self, request, *args, **kwargs):
        entry = get_object_or_404(ProblemListEntry, pk=kwargs["pk"])
        services.resolve_problem(instance=entry, actor=request.user, request=request)
        messages.success(request, _("Problem marked as resolved."))
        return redirect("emr:problem_list", pk=entry.patient_id)


class AllergyListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "emr/allergy_list.html"
    permission_required = "emr.view_allergy"

    def _context(self, patient, form=None):
        return {
            "page_title": _("Allergy Register · %(name)s")
            % {"name": patient.display_name},
            "patient": patient,
            "allergies": Allergy.objects.filter(patient=patient),
            "form": form or AllergyForm(),
        }

    def get(self, request, *args, **kwargs):
        patient = get_object_or_404(Patient, pk=kwargs["pk"])
        return self.render_to_response(self._context(patient))

    def post(self, request, *args, **kwargs):
        patient = get_object_or_404(Patient, pk=kwargs["pk"])
        form = AllergyForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.add_allergy(
                patient=patient,
                allergen=data["allergen"],
                allergy_type=data.get("allergy_type"),
                reaction=data.get("reaction", ""),
                severity=data.get("severity"),
                noted_on=data.get("noted_on"),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Allergy recorded."))
            return redirect("emr:allergy_list", pk=patient.pk)
        return self.render_to_response(self._context(patient, form))
