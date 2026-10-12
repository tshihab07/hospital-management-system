"""Forms for the OPD module."""

from __future__ import annotations

from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.patients.models import Patient

from .models import (AppointmentStatus, AppointmentType, AvailabilitySlot,
                     Doctor, Weekday)

WEEKDAYS = [("", _("All days"))] + list(Weekday.choices)


class StyledFormMixin:
    """Applies IHMS input styling to every widget automatically."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                continue
            existing = widget.attrs.get("class", "")
            if INPUT_CLASSES not in existing:
                widget.attrs["class"] = f"{existing} {INPUT_CLASSES}".strip()
            if isinstance(widget, forms.Textarea) and "rows" not in widget.attrs:
                widget.attrs["rows"] = 3


class DoctorForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Doctor
        fields = [
            "user",
            "department",
            "name_en",
            "name_bn",
            "phone",
            "email",
            "qualification",
            "specialization",
            "bmdc_no",
            "consultation_fee",
            "followup_fee",
            "revenue_share_pct",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].required = False
        self.fields["bmdc_no"].required = False


class AvailabilitySlotForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = AvailabilitySlot
        fields = ["weekday", "start_time", "end_time", "max_patients", "is_active"]
        widgets = {
            "weekday": forms.Select(attrs={"class": INPUT_CLASSES}),
            "start_time": forms.TimeInput(
                attrs={"type": "time", "class": INPUT_CLASSES}
            ),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": INPUT_CLASSES}),
        }

    def __init__(self, *args, doctor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.doctor = doctor

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.doctor is not None:
            instance.doctor = self.doctor
        if commit:
            instance.save()
        return instance


class AppointmentBookingForm(StyledFormMixin, forms.Form):
    patient = forms.ModelChoiceField(
        label=_("Patient"),
        queryset=Patient.objects.filter(is_deleted=False)
        .select_related()
        .order_by("full_name_en"),
    )
    doctor = forms.ModelChoiceField(
        label=_("Doctor"),
        queryset=Doctor.objects.filter(is_active=True).order_by("name_en"),
    )
    appt_date = forms.DateField(
        label=_("Appointment date"),
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASSES}),
    )
    slot = forms.IntegerField(
        label=_("Time block"),
        widget=forms.RadioSelect,
        required=False,
        help_text=_("Pick a block with free seats."),
    )
    visit_type = forms.ChoiceField(
        label=_("Visit type"),
        choices=AppointmentType.choices,
        initial=AppointmentType.NEW,
        widget=forms.Select(attrs={"class": INPUT_CLASSES}),
    )
    notes = forms.CharField(
        label=_("Notes"),
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASSES}),
    )

    def clean(self):
        cleaned = super().clean()
        appt_date = cleaned.get("appt_date")
        if appt_date and appt_date < date.today():
            self.add_error("appt_date", _("Cannot book an appointment in the past."))
        return cleaned


class SlotPreviewForm(StyledFormMixin, forms.Form):
    """Small GET form to preview a doctor's free blocks for a date."""

    doctor = forms.ModelChoiceField(
        label=_("Doctor"),
        queryset=Doctor.objects.filter(is_active=True).order_by("name_en"),
    )
    appt_date = forms.DateField(
        label=_("Date"),
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASSES}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doctor"].required = False
        self.fields["appt_date"].required = False


class AppointmentFilterForm(StyledFormMixin, forms.Form):
    appt_date = forms.DateField(
        label=_("Date"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASSES}),
    )
    doctor = forms.ModelChoiceField(
        label=_("Doctor"),
        queryset=Doctor.objects.filter(is_active=True).order_by("name_en"),
        required=False,
    )
    status = forms.ChoiceField(
        label=_("Status"),
        choices=[("", _("All statuses"))] + list(AppointmentStatus.choices),
        required=False,
    )
    q = forms.CharField(
        label=_("Search"),
        required=False,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASSES, "placeholder": _("UHID, name or phone")}
        ),
    )


class RescheduleForm(StyledFormMixin, forms.Form):
    appt_date = forms.DateField(
        label=_("New date"),
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASSES}),
    )
    slot = forms.IntegerField(
        label=_("New time block"),
        required=False,
        widget=forms.RadioSelect,
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("appt_date") and cleaned["appt_date"] < date.today():
            self.add_error("appt_date", _("Cannot book an appointment in the past."))
        return cleaned
