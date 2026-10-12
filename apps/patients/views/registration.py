"""Patient registration with duplicate detection (RULES Phase 3)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import PatientForm


class PatientCreateView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, CreateView
):
    """Register a new patient; warn (once) about likely duplicates."""

    model = None  # not used directly; creation goes through the service
    form_class = PatientForm
    template_name = "patients/patient_form.html"
    permission_required = "patients.add_patient"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Register Patient")
        context["is_create"] = True
        context.setdefault("duplicates", [])
        return context

    def form_valid(self, form):
        duplicates = selectors.find_duplicates(
            phone=form.cleaned_data.get("phone"),
            dob=form.cleaned_data.get("date_of_birth"),
            full_name_en=form.cleaned_data.get("full_name_en"),
        )
        confirm = self.request.POST.get("confirm_duplicate") == "1"
        if duplicates.exists() and not confirm:
            messages.warning(
                self.request,
                _(
                    "Possible duplicate patient(s) found. Review and confirm to proceed."
                ),
            )
            return self.render_to_response(
                self.get_context_data(form=form, duplicates=list(duplicates))
            )

        patient = services.register_patient(
            data=form.cleaned_data,
            actor=self.request.user,
            request=self.request,
        )
        messages.success(
            self.request,
            _("Patient %(uhid)s registered successfully.") % {"uhid": patient.uhid},
        )
        return redirect("patients:detail", pk=patient.pk)
