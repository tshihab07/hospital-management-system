"""Forms for the Operation Theatre module."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.hr.models import Staff
from apps.ipd.models import Admission, AdmissionStatus
from apps.opd.models import Doctor
from apps.patients.models import Patient

from .models import (AnesthesiaType, ImplantStatus, IntraOpNote, OTRoom,
                     OTRoomStatus, PostOpNote, PreOpChecklist, RoomType,
                     SurgeryPriority, SurgeryStatus, TeamRole)


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


def _doctor_qs():
    return Doctor.objects.filter(is_active=True).order_by("name_en")


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
class OTRoomForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = OTRoom
        fields = [
            "name",
            "room_no",
            "room_type",
            "floor",
            "equipment",
            "status",
            "is_active",
            "notes",
        ]
        widgets = {"equipment": forms.Textarea(attrs={"rows": 3})}


# ---------------------------------------------------------------------------
# Surgery
# ---------------------------------------------------------------------------
class SurgeryForm(StyledFormMixin, forms.Form):
    patient = _patient_field()
    surgeon = forms.ModelChoiceField(queryset=_doctor_qs(), label=_("Primary surgeon"))
    ot_room = forms.ModelChoiceField(
        queryset=OTRoom.objects.filter(is_active=True).order_by("name"),
        label=_("OT room"),
    )
    scheduled_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}), label=_("Date")
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}), label=_("Start time")
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}), label=_("End time")
    )
    procedure_name = forms.CharField(max_length=200, label=_("Procedure"))
    priority = forms.ChoiceField(
        choices=SurgeryPriority.choices, initial=SurgeryPriority.ELECTIVE
    )
    admission = forms.ModelChoiceField(
        queryset=Admission.objects.exclude(
            status__in=[AdmissionStatus.DISCHARGED, AdmissionStatus.CANCELLED]
        ).select_related("patient"),
        required=False,
        label=_("Linked admission"),
    )
    diagnosis = forms.CharField(max_length=255, required=False)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class SurgeryRescheduleForm(StyledFormMixin, forms.Form):
    scheduled_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}), label=_("New date")
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}), label=_("Start time")
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}), label=_("End time")
    )
    ot_room = forms.ModelChoiceField(
        queryset=OTRoom.objects.filter(is_active=True).order_by("name"),
        label=_("OT room"),
    )


class SurgeryFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label="")
    status = forms.ChoiceField(
        choices=[("", _("All statuses"))] + SurgeryStatus.choices,
        required=False,
        label="",
    )
    priority = forms.ChoiceField(
        choices=[("", _("All priorities"))] + SurgeryPriority.choices,
        required=False,
        label="",
    )
    room = forms.ModelChoiceField(
        queryset=OTRoom.objects.order_by("name"), required=False, label=""
    )
    date_from = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}), label=""
    )
    date_to = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}), label=""
    )


class CancelSurgeryForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), label=_("Reason")
    )


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
class TeamMemberForm(StyledFormMixin, forms.Form):
    role = forms.ChoiceField(choices=TeamRole.choices)
    doctor = forms.ModelChoiceField(
        queryset=_doctor_qs(), required=False, label=_("Doctor")
    )
    staff = forms.ModelChoiceField(
        queryset=Staff.objects.filter(is_active=True).order_by("name_en"),
        required=False,
        label=_("Staff"),
    )
    name = forms.CharField(max_length=150, required=False, label=_("Other name"))

    def clean(self):
        cleaned = super().clean()
        if (
            not cleaned.get("doctor")
            and not cleaned.get("staff")
            and not cleaned.get("name")
        ):
            raise forms.ValidationError(_("Provide a doctor, staff member, or name."))
        return cleaned


# ---------------------------------------------------------------------------
# Checklists / notes
# ---------------------------------------------------------------------------
class PreOpChecklistForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PreOpChecklist
        fields = list(PreOpChecklist.ITEMS) + ["notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class AnesthesiaForm(StyledFormMixin, forms.Form):
    anesthesia_type = forms.ChoiceField(choices=AnesthesiaType.choices)
    anesthetist = forms.ModelChoiceField(queryset=_doctor_qs(), required=False)
    asa_grade = forms.IntegerField(min_value=1, max_value=5, required=False)
    airway = forms.CharField(max_length=120, required=False)
    agents = forms.CharField(max_length=255, required=False)
    intubation_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}), required=False
    )
    extubation_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}), required=False
    )
    complications = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), required=False
    )
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class IntraOpNoteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = IntraOpNote
        fields = [
            "findings",
            "procedure_performed",
            "blood_loss_ml",
            "specimens",
            "drains",
            "closure",
            "notes",
        ]
        widgets = {
            "findings": forms.Textarea(attrs={"rows": 2}),
            "procedure_performed": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class PostOpNoteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PostOpNote
        fields = [
            "condition",
            "pain_score",
            "recovery_notes",
            "follow_up_plan",
            "notes",
        ]
        widgets = {
            "recovery_notes": forms.Textarea(attrs={"rows": 2}),
            "follow_up_plan": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


# ---------------------------------------------------------------------------
# Implants / consumables
# ---------------------------------------------------------------------------
class ImplantForm(StyledFormMixin, forms.Form):
    name = forms.CharField(max_length=150, label=_("Implant"))
    manufacturer = forms.CharField(max_length=150, required=False)
    serial_no = forms.CharField(max_length=100, required=False)
    lot_no = forms.CharField(max_length=100, required=False)
    quantity = forms.IntegerField(min_value=1, initial=1)
    unit_price = forms.DecimalField(max_digits=12, decimal_places=2, initial=0)
    status = forms.ChoiceField(
        choices=ImplantStatus.choices, initial=ImplantStatus.CONSUMED
    )
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class ConsumableForm(StyledFormMixin, forms.Form):
    item = forms.CharField(max_length=150)
    quantity = forms.IntegerField(min_value=1, initial=1)
    unit_price = forms.DecimalField(max_digits=12, decimal_places=2, initial=0)
    notes = forms.CharField(max_length=255, required=False)


class UtilizationFilterForm(StyledFormMixin, forms.Form):
    start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="")
    end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="")


class RoomFilterForm(StyledFormMixin, forms.Form):
    room_type = forms.ChoiceField(
        choices=[("", _("All types"))] + RoomType.choices, required=False, label=""
    )
    status = forms.ChoiceField(
        choices=[("", _("All statuses"))] + OTRoomStatus.choices,
        required=False,
        label="",
    )
