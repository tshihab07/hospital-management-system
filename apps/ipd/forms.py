"""Forms for the IPD module."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.emr.models import Route
from apps.masters.models import Drug
from apps.opd.models import Doctor
from apps.patients.models import Patient

from .models import (AdmissionStatus, AdmissionType, Bed, BedStatus,
                     ClearanceDepartment, DischargeType, FluidCategory,
                     FluidType, MarAction, NursingShift, Ward, WardType)


class StyledFormMixin:
    """Applies IHMS input styling to every widget automatically."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                continue
            existing = widget.attrs.get("class", "")
            if INPUT_CLASSES not in existing:
                widget.attrs["class"] = f"{existing} {INPUT_CLASSES}".strip()
            if isinstance(widget, forms.Textarea) and "rows" not in widget.attrs:
                widget.attrs["rows"] = 3


def _patient_field():
    return forms.ModelChoiceField(
        queryset=Patient.objects.all().order_by("full_name_en"),
        label=_("Patient"),
        widget=forms.Select(attrs={"data-search": "true"}),
    )


class WardTypeFilterForm(StyledFormMixin, forms.Form):
    ward_type = forms.ChoiceField(
        choices=[("", _("All wards"))] + WardType.choices, required=False, label=""
    )


class AdmissionForm(StyledFormMixin, forms.Form):
    patient = _patient_field()
    doctor = forms.ModelChoiceField(
        queryset=Doctor.objects.filter(is_active=True).order_by("name_en"),
        label=_("Admitting doctor"),
    )
    admission_type = forms.ChoiceField(
        choices=AdmissionType.choices, initial=AdmissionType.ROUTINE
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), label=_("Reason")
    )
    admission_note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("Note")
    )


class BedAllocateForm(StyledFormMixin, forms.Form):
    bed = forms.ModelChoiceField(
        queryset=Bed.objects.filter(
            status=BedStatus.AVAILABLE, ward__is_active=True
        ).select_related("ward"),
        label=_("Bed"),
        empty_label=_("— select an available bed —"),
    )


class BedTransferForm(StyledFormMixin, forms.Form):
    to_bed = forms.ModelChoiceField(
        queryset=Bed.objects.filter(
            status=BedStatus.AVAILABLE, ward__is_active=True
        ).select_related("ward"),
        label=_("To bed"),
        empty_label=_("— select target bed —"),
    )
    reason = forms.CharField(
        required=False, max_length=255, label=_("Reason"), widget=forms.TextInput()
    )


class AdmissionFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False, choices=[("", _("All statuses")), *AdmissionStatus.choices]
    )
    ward = forms.ModelChoiceField(
        queryset=Ward.objects.filter(is_active=True).order_by("name"),
        required=False,
        empty_label=_("All wards"),
    )
    search = forms.CharField(
        required=False,
        label=_("Search"),
        widget=forms.TextInput(attrs={"placeholder": _("Patient, UHID or IP number")}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} {INPUT_CLASSES}".strip()


class DischargeRequestForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(
        max_length=255,
        label=_("Discharge reason"),
        widget=forms.TextInput(attrs={"placeholder": _("e.g. Improved, advised")}),
    )


class ClearanceForm(StyledFormMixin, forms.Form):
    department = forms.ChoiceField(choices=ClearanceDepartment.choices)
    notes = forms.CharField(required=False, max_length=255, label=_("Notes"))


class DischargeSummaryForm(StyledFormMixin, forms.Form):
    discharge_type = forms.ChoiceField(choices=DischargeType.choices)
    diagnosis_summary = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), label=_("Diagnosis / summary")
    )
    treatment_given = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), label=_("Treatment given")
    )
    follow_up = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), label=_("Follow-up plan")
    )
    discharge_advice = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("Advice")
    )


class NursingNoteForm(StyledFormMixin, forms.Form):
    shift = forms.ChoiceField(choices=NursingShift.choices, initial=NursingShift.DAY)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), label=_("Note"))


class MarForm(StyledFormMixin, forms.Form):
    drug = forms.ModelChoiceField(
        queryset=Drug.objects.filter(is_active=True).order_by("generic_name"),
        label=_("Drug"),
    )
    dose = forms.CharField(max_length=100, label=_("Dose"))
    route = forms.ChoiceField(choices=Route.choices, initial=Route.ORAL)
    scheduled_for = forms.DateTimeField(
        label=_("Scheduled for"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=[
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
        ],
    )
    action = forms.ChoiceField(choices=MarAction.choices, initial=MarAction.GIVEN)
    notes = forms.CharField(required=False, max_length=255, label=_("Notes"))


class IntakeOutputForm(StyledFormMixin, forms.Form):
    fluid_type = forms.ChoiceField(choices=FluidType.choices)
    category = forms.ChoiceField(choices=FluidCategory.choices)
    volume_ml = forms.IntegerField(min_value=0, label=_("Volume (ml)"))
    shift = forms.ChoiceField(choices=NursingShift.choices, initial=NursingShift.DAY)
