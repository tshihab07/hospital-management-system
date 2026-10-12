"""Forms for the EMR & CPOE module."""

from __future__ import annotations

from django import forms
from django.forms import modelformset_factory
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.masters.models import (Diagnosis, Drug, LabTest, Procedure,
                                 RadiologyTest)
from apps.opd.models import Doctor
from apps.patients.models import Patient

from .models import (Allergy, ClinicalAttachment, Encounter, EncounterStatus,
                     EncounterType, OrderPriority, OrderStatus,
                     PrescriptionItem, ProblemListEntry, ProcedureOrder,
                     SoapTemplate, VisitDiagnosis, Vital)


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


def _doctor_field():
    return forms.ModelChoiceField(
        queryset=Doctor.objects.filter(is_active=True).order_by("name_en"),
        label=_("Doctor"),
    )


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------
class EncounterOpenForm(StyledFormMixin, forms.ModelForm):
    patient = _patient_field()
    doctor = _doctor_field()

    class Meta:
        model = Encounter
        fields = ["patient", "doctor", "encounter_type", "chief_complaint"]
        widgets = {"chief_complaint": forms.Textarea(attrs={"rows": 2})}


class EncounterFilterForm(forms.Form):
    enc_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    doctor = forms.ModelChoiceField(
        queryset=Doctor.objects.filter(is_active=True).order_by("name_en"),
        required=False,
        empty_label=_("All doctors"),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[("", _("All statuses")), *EncounterStatus.choices],
    )
    encounter_type = forms.ChoiceField(
        required=False,
        choices=[("", _("All types")), *EncounterType.choices],
    )
    q = forms.CharField(
        required=False,
        label=_("Search"),
        widget=forms.TextInput(attrs={"placeholder": _("Patient, UHID or complaint")}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} {INPUT_CLASSES}".strip()


# ---------------------------------------------------------------------------
# Clinical documentation
# ---------------------------------------------------------------------------
class SoapNoteForm(StyledFormMixin, forms.Form):
    template = forms.ModelChoiceField(
        queryset=SoapTemplate.objects.filter(is_active=True),
        required=False,
        label=_("Start from template"),
        empty_label=_("— none —"),
    )
    subjective = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label=_("Subjective (S)"),
    )
    objective = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label=_("Objective (O)"),
    )
    assessment = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label=_("Assessment (A)"),
    )
    plan = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label=_("Plan (P)"),
    )


class VitalForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Vital
        fields = [
            "temperature_c",
            "pulse",
            "respiratory_rate",
            "bp_systolic",
            "bp_diastolic",
            "spo2",
            "height_cm",
            "weight_kg",
            "pain_score",
            "notes",
        ]


class VisitDiagnosisForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = VisitDiagnosis
        fields = ["diagnosis", "description", "is_primary"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["diagnosis"].queryset = Diagnosis.objects.filter(
            is_active=True
        ).order_by("code")
        self.fields["diagnosis"].required = False

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("diagnosis") and not cleaned.get("description"):
            raise forms.ValidationError(
                _("Provide a coded diagnosis or a free-text description.")
            )
        return cleaned


class ProblemForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProblemListEntry
        fields = ["description", "diagnosis", "onset_date"]
        widgets = {"onset_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["diagnosis"].queryset = Diagnosis.objects.filter(
            is_active=True
        ).order_by("code")
        self.fields["diagnosis"].required = False


class AllergyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Allergy
        fields = ["allergen", "allergy_type", "reaction", "severity", "noted_on"]
        widgets = {"noted_on": forms.DateInput(attrs={"type": "date"})}


# ---------------------------------------------------------------------------
# CPOE: prescriptions
# ---------------------------------------------------------------------------
class PrescriptionForm(StyledFormMixin, forms.Form):
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label=_("Notes / advice"),
    )


class PrescriptionItemForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PrescriptionItem
        fields = [
            "drug",
            "dose",
            "route",
            "frequency",
            "duration_days",
            "quantity",
            "is_prn",
            "instructions",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drug"].queryset = Drug.objects.filter(is_active=True).order_by(
            "generic_name", "brand_name"
        )
        self.fields["drug"].required = False

    def clean(self):
        cleaned = super().clean()
        if self.has_changed() and not cleaned.get("drug"):
            self.add_error("drug", _("Choose a drug for this line."))
        return cleaned


PrescriptionItemFormSet = modelformset_factory(
    PrescriptionItem,
    form=PrescriptionItemForm,
    extra=1,
    can_delete=True,
)


# ---------------------------------------------------------------------------
# CPOE: diagnostic & procedure orders
# ---------------------------------------------------------------------------
class LabOrderForm(StyledFormMixin, forms.Form):
    tests = forms.ModelMultipleChoiceField(
        queryset=LabTest.objects.filter(is_active=True).order_by("name"),
        widget=forms.CheckboxSelectMultiple,
        label=_("Tests"),
    )
    priority = forms.ChoiceField(
        choices=OrderPriority.choices, initial=OrderPriority.ROUTINE
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class RadiologyOrderForm(StyledFormMixin, forms.Form):
    tests = forms.ModelMultipleChoiceField(
        queryset=RadiologyTest.objects.filter(is_active=True).order_by("name"),
        widget=forms.CheckboxSelectMultiple,
        label=_("Tests"),
    )
    priority = forms.ChoiceField(
        choices=OrderPriority.choices, initial=OrderPriority.ROUTINE
    )
    clinical_indication = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label=_("Clinical indication"),
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class ProcedureOrderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProcedureOrder
        fields = ["procedure", "priority", "scheduled_for", "notes"]
        widgets = {"scheduled_for": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["procedure"].queryset = Procedure.objects.filter(
            is_active=True
        ).order_by("name")


class OrderStatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(choices=OrderStatus.choices)


# ---------------------------------------------------------------------------
# Attachments & SOAP templates
# ---------------------------------------------------------------------------
class ClinicalAttachmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ClinicalAttachment
        fields = ["title", "category", "file", "description"]


class SoapTemplateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SoapTemplate
        fields = [
            "name",
            "chief_complaint",
            "subjective",
            "objective",
            "assessment",
            "plan",
            "is_active",
        ]


class PrescriptionFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label=_("Search"),
        widget=forms.TextInput(attrs={"placeholder": _("Patient or UHID")}),
    )
    doctor = forms.ModelChoiceField(
        queryset=Doctor.objects.filter(is_active=True).order_by("name_en"),
        required=False,
        empty_label=_("All doctors"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} {INPUT_CLASSES}".strip()
