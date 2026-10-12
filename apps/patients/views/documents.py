"""Patient document upload and removal."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views import View

from core.audit import AuditAction, log_action
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import services
from ..forms import PatientDocumentForm
from ..models import Patient, PatientDocument


class DocumentCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Upload one document to a patient from their profile page."""

    permission_required = "patients.change_patient"

    def post(self, request, pk, *args, **kwargs):
        patient = get_object_or_404(Patient, pk=pk)
        form = PatientDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            services.add_document(
                patient=patient,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Document uploaded."))
        else:
            messages.error(
                request, _("Could not upload document. Please check the file.")
            )
        return redirect("patients:detail", pk=patient.pk)


class DocumentDeleteView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Remove a patient document (POST only)."""

    permission_required = "patients.change_patient"

    def post(self, request, pk, *args, **kwargs):
        document = get_object_or_404(PatientDocument, pk=pk)
        patient_pk = document.patient_id
        log_action(
            AuditAction.DELETE,
            instance=document,
            changes={"title": document.title},
            user=request.user,
            request=request,
        )
        document.file.delete(save=False)
        document.delete()
        messages.success(request, _("Document removed."))
        return redirect("patients:detail", pk=patient_pk)
