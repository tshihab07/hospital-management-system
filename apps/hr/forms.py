"""Forms for the HR module."""

from __future__ import annotations

from datetime import date

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.masters.models import Department, Designation

from .models import (Attendance, AttendanceSource, AttendanceStatus,
                     LeaveRequest, LeaveStatus, LeaveType, Shift, Staff,
                     StaffStatus)

WEEKDAY_CHOICES = [
    (0, _("Monday")),
    (1, _("Tuesday")),
    (2, _("Wednesday")),
    (3, _("Thursday")),
    (4, _("Friday")),
    (5, _("Saturday")),
    (6, _("Sunday")),
]


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


class ShiftForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Shift
        fields = ["name", "code", "start_time", "end_time", "is_night", "is_active"]
        widgets = {
            "start_time": forms.TimeInput(
                attrs={"type": "time", "class": INPUT_CLASSES}
            ),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": INPUT_CLASSES}),
        }


class StaffForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Staff
        fields = [
            "employee_code",
            "name_en",
            "name_bn",
            "department",
            "designation",
            "user",
            "phone",
            "email",
            "joining_date",
            "employment_type",
            "status",
            "shift",
            "basic_salary",
            "house_rent",
            "medical_allowance",
            "transport_allowance",
            "other_allowance",
            "notes",
            "is_active",
        ]
        widgets = {
            "joining_date": forms.DateInput(
                attrs={"type": "date", "class": INPUT_CLASSES}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("user", "department", "designation", "shift", "joining_date"):
            self.fields[name].required = False


class StaffFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(
        label=_("Search"),
        required=False,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASSES, "placeholder": _("Name, code or phone")}
        ),
    )
    department = forms.ModelChoiceField(
        label=_("Department"),
        queryset=Department.objects.all().order_by("name"),
        required=False,
    )
    designation = forms.ModelChoiceField(
        label=_("Designation"),
        queryset=Designation.objects.all().order_by("name"),
        required=False,
    )
    status = forms.ChoiceField(
        label=_("Status"),
        choices=[("", _("All statuses"))] + list(StaffStatus.choices),
        required=False,
    )


class AttendanceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Attendance
        fields = [
            "staff",
            "att_date",
            "status",
            "check_in",
            "check_out",
            "source",
            "device_id",
            "remarks",
        ]
        widgets = {
            "att_date": forms.DateInput(attrs={"type": "date", "class": INPUT_CLASSES}),
            "check_in": forms.TimeInput(attrs={"type": "time", "class": INPUT_CLASSES}),
            "check_out": forms.TimeInput(
                attrs={"type": "time", "class": INPUT_CLASSES}
            ),
        }


class AttendanceFilterForm(StyledFormMixin, forms.Form):
    staff = forms.ModelChoiceField(
        label=_("Staff"),
        queryset=Staff.objects.all().order_by("name_en"),
        required=False,
    )
    date_from = forms.DateField(
        label=_("From"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASSES}),
    )
    date_to = forms.DateField(
        label=_("To"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASSES}),
    )
    source = forms.ChoiceField(
        label=_("Source"),
        choices=[("", _("All sources"))] + list(AttendanceSource.choices),
        required=False,
    )


class AttendanceImportForm(StyledFormMixin, forms.Form):
    file = forms.FileField(
        label=_("CSV file"),
        help_text=_("Columns: employee_code, date, check_in, check_out, status"),
    )
    device_id = forms.CharField(label=_("Device id"), required=False, max_length=60)


class RosterGenerateForm(StyledFormMixin, forms.Form):
    staff = forms.ModelChoiceField(
        label=_("Staff"),
        queryset=Staff.objects.filter(is_active=True).order_by("name_en"),
    )
    shift = forms.ModelChoiceField(
        label=_("Shift"),
        queryset=Shift.objects.filter(is_active=True).order_by("start_time"),
    )
    week_start = forms.DateField(
        label=_("Week starting"),
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASSES}),
    )
    weekdays = forms.MultipleChoiceField(
        label=_("Days"),
        choices=WEEKDAY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        initial=[0, 1, 2, 3, 4, 5],
    )
    notes = forms.CharField(
        label=_("Notes"),
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASSES}),
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("weekdays"):
            self.add_error("weekdays", _("Select at least one day."))
        return cleaned


class LeaveTypeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = [
            "name",
            "code",
            "max_days_per_year",
            "is_paid",
            "requires_document",
            "is_active",
        ]


class LeaveRequestForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["staff", "leave_type", "start_date", "end_date", "reason"]
        widgets = {
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": INPUT_CLASSES}
            ),
            "end_date": forms.DateInput(attrs={"type": "date", "class": INPUT_CLASSES}),
        }

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("End date cannot be before the start date."))
        return cleaned


class LeaveFilterForm(StyledFormMixin, forms.Form):
    staff = forms.ModelChoiceField(
        label=_("Staff"),
        queryset=Staff.objects.all().order_by("name_en"),
        required=False,
    )
    status = forms.ChoiceField(
        label=_("Status"),
        choices=[("", _("All statuses"))] + list(LeaveStatus.choices),
        required=False,
    )


class PerformanceFilterForm(StyledFormMixin, forms.Form):
    year = forms.IntegerField(label=_("Year"), min_value=2000, max_value=2100)
    month = forms.TypedChoiceField(
        label=_("Month"),
        coerce=int,
        choices=[(m, date(2000, m, 1).strftime("%B")) for m in range(1, 13)],
    )
