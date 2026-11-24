"""Forms for the ICU / Emergency module."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.opd.models import Doctor
from apps.patients.models import Patient

from .models import (EmergencyCase, EmergencyStatus, IcuRecord, ScoreType,
                     TriageLevel, Unit, UnitShift, VentilatorMode)


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


def _doctor_field(required: bool = False):
    return forms.ModelChoiceField(
        queryset=Doctor.objects.filter(is_active=True).order_by("name_en"),
        required=required,
        label=_("Doctor"),
    )


class IcuRecordForm(StyledFormMixin, forms.ModelForm):
    """Hourly ICU chart entry."""

    class Meta:
        model = IcuRecord
        fields = [
            "recorded_at",
            "temperature",
            "pulse",
            "respiratory_rate",
            "bp_systolic",
            "bp_diastolic",
            "spo2",
            "gcs",
            "ventilator_mode",
            "fio2",
            "peep",
            "tidal_volume",
            "set_rate",
            "intake_ml",
            "output_ml",
            "notes",
        ]
        widgets = {
            "recorded_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recorded_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["recorded_at"].required = False

    def clean_gcs(self):
        gcs = self.cleaned_data.get("gcs")
        if gcs is not None and not 3 <= gcs <= 15:
            raise forms.ValidationError(_("GCS must be between 3 and 15."))
        return gcs


class ScoreForm(StyledFormMixin, forms.Form):
    """APACHE II / SOFA calculator inputs (shared, blank fields ignored)."""

    score_type = forms.ChoiceField(choices=ScoreType.choices, label=_("Score type"))
    temperature = forms.DecimalField(required=False, max_digits=4, decimal_places=1)
    map = forms.DecimalField(
        required=False, max_digits=5, decimal_places=1, label=_("MAP (mmHg)")
    )
    heart_rate = forms.IntegerField(required=False)
    respiratory_rate = forms.IntegerField(required=False)
    pao2 = forms.DecimalField(
        required=False, max_digits=5, decimal_places=1, label=_("PaO₂")
    )
    pao2_fio2 = forms.DecimalField(
        required=False, max_digits=6, decimal_places=1, label=_("PaO₂/FiO₂")
    )
    resp_support = forms.BooleanField(required=False, label=_("Respiratory support"))
    ph = forms.DecimalField(
        required=False, max_digits=4, decimal_places=2, label=_("Arterial pH")
    )
    sodium = forms.DecimalField(required=False, max_digits=5, decimal_places=1)
    potassium = forms.DecimalField(required=False, max_digits=4, decimal_places=1)
    creatinine = forms.DecimalField(required=False, max_digits=5, decimal_places=2)
    acute_renal_failure = forms.BooleanField(required=False)
    hematocrit = forms.DecimalField(required=False, max_digits=4, decimal_places=1)
    wbc = forms.DecimalField(
        required=False, max_digits=5, decimal_places=2, label=_("WBC")
    )
    platelets = forms.DecimalField(required=False, max_digits=6, decimal_places=1)
    bilirubin = forms.DecimalField(required=False, max_digits=5, decimal_places=2)
    urine_output = forms.DecimalField(required=False, max_digits=7, decimal_places=1)
    vasopressor_level = forms.IntegerField(required=False, min_value=0, max_value=4)
    gcs = forms.IntegerField(required=False, min_value=3, max_value=15)
    age = forms.IntegerField(required=False, min_value=0, max_value=130)
    chronic_points = forms.IntegerField(required=False, min_value=0, max_value=5)


class QuickRegistrationForm(StyledFormMixin, forms.Form):
    """Minimal patient fields for a fast ER registration."""

    full_name_en = forms.CharField(label=_("Name"))
    phone = forms.CharField(label=_("Phone"))
    gender = forms.ChoiceField(
        choices=[("male", _("Male")), ("female", _("Female")), ("other", _("Other"))]
    )
    age_years = forms.IntegerField(required=False, min_value=0, max_value=130)
    date_of_birth = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    complaint = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))
    triage_level = forms.ChoiceField(
        choices=TriageLevel.choices, initial=TriageLevel.YELLOW
    )
    attending_doctor = _doctor_field(required=False)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("date_of_birth") and cleaned.get("age_years") is None:
            raise forms.ValidationError(_("Provide a date of birth or an age."))
        return cleaned


class EmergencyCaseForm(StyledFormMixin, forms.ModelForm):
    """Edit core details of an existing ER case."""

    class Meta:
        model = EmergencyCase
        fields = [
            "patient",
            "complaint",
            "triage_level",
            "attending_doctor",
            "temperature",
            "pulse",
            "respiratory_rate",
            "bp_systolic",
            "bp_diastolic",
            "spo2",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"] = _patient_field()
        self.fields["attending_doctor"].required = False


class TriageForm(StyledFormMixin, forms.Form):
    triage_level = forms.ChoiceField(choices=TriageLevel.choices)


class EmergencyStatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(choices=EmergencyStatus.choices)


class ConvertAdmissionForm(StyledFormMixin, forms.Form):
    doctor = _doctor_field(required=True)
    reason = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("Reason")
    )


class CodeBlueForm(StyledFormMixin, forms.Form):
    location = forms.CharField(label=_("Location"))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class HandoverForm(StyledFormMixin, forms.Form):
    unit = forms.ChoiceField(choices=Unit.choices)
    shift = forms.ChoiceField(choices=UnitShift.choices)
    summary = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    pending_tasks = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    handover_to = forms.ModelChoiceField(
        queryset=None, required=False, label=_("Hand over to")
    )

    def __init__(self, *args, **kwargs):
        from django.contrib.auth import get_user_model

        super().__init__(*args, **kwargs)
        self.fields["handover_to"].queryset = (
            get_user_model().objects.filter(is_active=True).order_by("username")
        )


class EmergencyFilterForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(
        choices=[("", _("Open cases"))] + EmergencyStatus.choices, required=False
    )
    triage = forms.ChoiceField(
        choices=[("", _("All triage levels"))] + TriageLevel.choices, required=False
    )
    search = forms.CharField(required=False)


class VentilatorModeFilterForm(StyledFormMixin, forms.Form):
    ventilator_mode = forms.ChoiceField(
        choices=[("", _("Any"))] + VentilatorMode.choices, required=False, label=""
    )
