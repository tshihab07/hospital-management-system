"""Patient list, search, filtering and CSV export."""

from __future__ import annotations

import csv

from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, View

from core.audit import AuditAction, log_action
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors
from ..forms import PatientFilterForm
from ..models import Patient


def _filtered_queryset(request):
    form = PatientFilterForm(request.GET or None)
    data = form.cleaned_data if form.is_valid() else {}
    return (
        selectors.patient_list(
            search=data.get("q") or None,
            gender=data.get("gender") or None,
            patient_type=data.get("patient_type") or None,
        ),
        form,
    )


class PatientListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    model = Patient
    template_name = "patients/patient_list.html"
    context_object_name = "patients"
    paginate_by = 20
    permission_required = "patients.view_patient"

    def get_queryset(self):
        qs, self.filter_form = _filtered_queryset(self.request)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_title"] = _("Patients")
        context["total"] = self.get_queryset().count()
        return context


class PatientExportView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Stream the filtered patient list as CSV and audit the export."""

    permission_required = "patients.view_patient"

    def get(self, request, *args, **kwargs):
        qs, _ = _filtered_queryset(request)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="patients.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "UHID",
                "Name (EN)",
                "Name (BN)",
                "Gender",
                "Age",
                "Blood Group",
                "Phone",
                "NID",
                "Type",
                "Registered",
            ]
        )
        for patient in qs[:5000]:
            writer.writerow(
                [
                    patient.uhid,
                    patient.full_name_en,
                    patient.full_name_bn,
                    patient.get_gender_display(),
                    patient.age or "",
                    patient.get_blood_group_display(),
                    patient.phone,
                    patient.nid,
                    patient.get_patient_type_display(),
                    patient.created_at.isoformat(),
                ]
            )
        log_action(
            AuditAction.EXPORT,
            model_name="patient",
            object_repr=f"{qs.count()} patients",
            changes={"count": qs.count()},
            user=request.user,
            request=request,
        )
        return response
