"""Admin-only patient merge tool (RULES Phase 3)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import services
from ..forms import PatientMergeForm


class PatientMergeView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, FormView):
    template_name = "patients/patient_merge.html"
    form_class = PatientMergeForm
    permission_required = "patients.merge_patient"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Merge Patients")
        return context

    def form_valid(self, form):
        primary = form.cleaned_data["primary"]
        duplicate = form.cleaned_data["duplicate"]
        services.merge_patients(
            primary=primary,
            duplicate=duplicate,
            actor=self.request.user,
            request=self.request,
        )
        messages.success(
            self.request,
            _("Merged %(dup)s into %(primary)s.")
            % {"dup": duplicate.uhid, "primary": primary.uhid},
        )
        return redirect("patients:detail", pk=primary.pk)
