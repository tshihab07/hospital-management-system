"""Forms for patient registration and records."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES

from .models import (DocumentCategory, Gender, Patient, PatientDocument,
                     PatientType)


class PatientForm(forms.ModelForm):
    """Full registration / edit form. UHID is assigned by the system."""

    class Meta:
        model = Patient
        fields = [
            "full_name_en",
            "full_name_bn",
            "date_of_birth",
            "age_years",
            "gender",
            "blood_group",
            "marital_status",
            "occupation",
            "nationality",
            "nid",
            "phone",
            "alt_phone",
            "email",
            "address",
            "permanent_address",
            "city",
            "postcode",
            "guardian_name",
            "guardian_relation",
            "emergency_contact_name",
            "emergency_contact_relation",
            "emergency_contact_phone",
            "patient_type",
            "photo",
            "notes",
            "is_active",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 2}),
            "permanent_address": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # These carry model defaults, so they must not block a fast registration.
        for name in (
            "blood_group",
            "marital_status",
            "nationality",
            "patient_type",
            "occupation",
            "is_active",
        ):
            self.fields[name].required = False
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                continue
            existing = widget.attrs.get("class", "")
            if INPUT_CLASSES not in existing:
                widget.attrs["class"] = f"{existing} {INPUT_CLASSES}".strip()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("date_of_birth") and cleaned.get("age_years") is None:
            raise forms.ValidationError(
                _("Provide a date of birth or an age."),
                code="missing_age",
            )
        return cleaned


class PatientDocumentForm(forms.ModelForm):
    class Meta:
        model = PatientDocument
        fields = ["title", "category", "file", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            existing = widget.attrs.get("class", "")
            if INPUT_CLASSES not in existing:
                widget.attrs["class"] = f"{existing} {INPUT_CLASSES}".strip()


class PatientFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label=_("Search"),
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASSES, "placeholder": _("UHID, name, phone or NID")}
        ),
    )
    gender = forms.ChoiceField(
        required=False,
        label=_("Gender"),
        choices=[("", _("Any"))] + list(Gender.choices),
        widget=forms.Select(attrs={"class": INPUT_CLASSES}),
    )
    patient_type = forms.ChoiceField(
        required=False,
        label=_("Type"),
        choices=[("", _("Any"))] + list(PatientType.choices),
        widget=forms.Select(attrs={"class": INPUT_CLASSES}),
    )


class PatientMergeForm(forms.Form):
    """Admin tool to fold a duplicate patient into a primary record."""

    primary = forms.ModelChoiceField(
        queryset=Patient.objects.all(),
        label=_("Primary patient (kept)"),
        widget=forms.Select(attrs={"class": INPUT_CLASSES}),
    )
    duplicate = forms.ModelChoiceField(
        queryset=Patient.objects.all(),
        label=_("Duplicate patient (merged & removed)"),
        widget=forms.Select(attrs={"class": INPUT_CLASSES}),
    )

    def clean(self):
        cleaned = super().clean()
        primary = cleaned.get("primary")
        duplicate = cleaned.get("duplicate")
        if primary and duplicate and primary.pk == duplicate.pk:
            raise forms.ValidationError(_("Choose two different patients."))
        return cleaned
