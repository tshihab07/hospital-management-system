"""Clinical attachments and SOAP template library views (RULES Phase 6)."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, View
from django.views.generic.base import TemplateResponseMixin

from apps.patients.models import Patient
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import ClinicalAttachmentForm, SoapTemplateForm
from ..models import ClinicalAttachment, SoapTemplate


class AttachmentListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "emr/attachment_list.html"
    permission_required = "emr.view_clinicalattachment"

    def _context(self, patient, form=None):
        return {
            "page_title": _("Clinical Attachments · %(name)s")
            % {"name": patient.display_name},
            "patient": patient,
            "attachments": selectors.attachments_for(patient),
            "form": form or ClinicalAttachmentForm(),
        }

    def get(self, request, *args, **kwargs):
        patient = get_object_or_404(Patient, pk=kwargs["pk"])
        return self.render_to_response(self._context(patient))

    def post(self, request, *args, **kwargs):
        patient = get_object_or_404(Patient, pk=kwargs["pk"])
        form = ClinicalAttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            services.add_attachment(
                patient=patient,
                file=data["file"],
                title=data["title"],
                category=data.get("category"),
                description=data.get("description", ""),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Attachment uploaded."))
            return redirect("emr:attachment_list", pk=patient.pk)
        return self.render_to_response(self._context(patient, form))


class AttachmentRemoveView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "emr.delete_clinicalattachment"

    def post(self, request, *args, **kwargs):
        attachment = get_object_or_404(ClinicalAttachment, pk=kwargs["pk"])
        patient_id = attachment.patient_id
        services.remove_attachment(
            instance=attachment, actor=request.user, request=request
        )
        messages.success(request, _("Attachment removed."))
        return redirect("emr:attachment_list", pk=patient_id)


class SoapTemplateListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView
):
    template_name = "emr/soap_template_list.html"
    context_object_name = "templates"
    permission_required = "emr.view_soaptemplate"
    queryset = SoapTemplate.objects.all()


class SoapTemplateCreateView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "emr/soap_template_form.html"
    permission_required = "emr.add_soaptemplate"

    def _context(self, form):
        return {
            "page_title": _("New SOAP Template"),
            "form": form,
        }

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self._context(SoapTemplateForm()))

    def post(self, request, *args, **kwargs):
        form = SoapTemplateForm(request.POST)
        if form.is_valid():
            template = form.save()
            messages.success(
                request,
                _("Template “%(name)s” saved.") % {"name": template.name},
            )
            return redirect("emr:soap_template_list")
        return self.render_to_response(self._context(form))
