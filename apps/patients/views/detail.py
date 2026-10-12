"""Patient profile, edit, soft-delete and restore views."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, UpdateView

from core.audit import AuditLog
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import PatientForm
from ..models import Patient


class PatientDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView
):
    model = Patient
    template_name = "patients/patient_detail.html"
    context_object_name = "patient"
    permission_required = "patients.view_patient"

    def get_queryset(self):
        return Patient.all_objects.select_related("registered_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        patient = self.object
        context["page_title"] = patient.display_name
        context["documents"] = selectors.patient_documents(patient)
        context["timeline"] = AuditLog.objects.filter(
            model_name__icontains="patient",
            object_id=str(patient.pk),
        ).select_related("user")[:25]
        return context


class PatientUpdateView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, UpdateView
):
    model = Patient
    form_class = PatientForm
    template_name = "patients/patient_form.html"
    permission_required = "patients.change_patient"

    def get_queryset(self):
        return Patient.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Edit %(name)s") % {"name": self.object.display_name}
        context["is_create"] = False
        context.setdefault("duplicates", [])
        return context

    def form_valid(self, form):
        self.object = services.update_patient(
            instance=form.instance,
            data=form.cleaned_data,
            actor=self.request.user,
            request=self.request,
        )
        messages.success(self.request, _("Patient record updated."))
        return redirect("patients:detail", pk=self.object.pk)


class PatientDeleteView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Soft-delete a patient (POST only)."""

    permission_required = "patients.delete_patient"

    def post(self, request, pk, *args, **kwargs):
        patient = Patient.objects.filter(pk=pk).first()
        if patient is None:
            messages.error(request, _("Patient not found."))
            return redirect("patients:list")
        services.soft_delete_patient(
            instance=patient, actor=request.user, request=request
        )
        messages.success(request, _("Patient archived."))
        return redirect("patients:list")


class PatientRestoreView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Restore a soft-deleted patient (POST only)."""

    permission_required = "patients.change_patient"

    def post(self, request, pk, *args, **kwargs):
        patient = Patient.all_objects.filter(pk=pk, is_deleted=True).first()
        if patient is None:
            messages.error(request, _("Archived patient not found."))
            return redirect("patients:list")
        services.restore_patient(instance=patient, actor=request.user, request=request)
        messages.success(request, _("Patient restored."))
        return redirect(reverse("patients:detail", kwargs={"pk": patient.pk}))
