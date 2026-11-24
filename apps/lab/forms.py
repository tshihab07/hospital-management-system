"""Forms for the Laboratory & Radiology module."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.emr.models import OrderPriority, OrderStatus
from apps.opd.models import Doctor

from .models import RadiologyStatus, ResultFlag, SampleStatus


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


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
class LabOrderFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label="")
    status = forms.ChoiceField(
        choices=[("", _("All statuses"))] + OrderStatus.choices,
        required=False,
        label="",
    )
    priority = forms.ChoiceField(
        choices=[("", _("All priorities"))] + OrderPriority.choices,
        required=False,
        label="",
    )


class SampleFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label="")
    status = forms.ChoiceField(
        choices=[("", _("All statuses"))] + SampleStatus.choices,
        required=False,
        label="",
    )


class ResultFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label="")
    status = forms.ChoiceField(
        choices=[
            ("", _("All")),
            ("pending", _("Pending verification")),
            ("verified", _("Verified")),
        ],
        required=False,
        label="",
    )
    flagged = forms.BooleanField(required=False, label=_("Abnormal only"))


class RadiologyFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label="")
    status = forms.ChoiceField(
        choices=[("", _("All statuses"))] + RadiologyStatus.choices,
        required=False,
        label="",
    )


# ---------------------------------------------------------------------------
# Lab workflow
# ---------------------------------------------------------------------------
class CollectSampleForm(StyledFormMixin, forms.Form):
    sample_type = forms.CharField(
        max_length=100, required=False, label=_("Sample type")
    )
    notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), required=False, label=_("Notes")
    )


class RejectSampleForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), label=_("Rejection reason")
    )


class ResultEntryForm(StyledFormMixin, forms.Form):
    value = forms.CharField(max_length=120, label=_("Value"))
    flag = forms.ChoiceField(
        choices=[("", _("Auto"))] + ResultFlag.choices, required=False, label=_("Flag")
    )
    remarks = forms.CharField(max_length=255, required=False, label=_("Remarks"))


class AddendumForm(StyledFormMixin, forms.Form):
    text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), label=_("Addendum")
    )


class ReportRemarksForm(StyledFormMixin, forms.Form):
    remarks = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), required=False, label=_("Remarks")
    )


# ---------------------------------------------------------------------------
# Radiology workflow
# ---------------------------------------------------------------------------
class RadiologyScheduleForm(StyledFormMixin, forms.Form):
    scheduled_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        label=_("Schedule for"),
    )


class RadiologyReportForm(StyledFormMixin, forms.Form):
    findings = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}), required=False, label=_("Findings")
    )
    impression = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), required=False, label=_("Impression")
    )
    radiologist = forms.ModelChoiceField(
        queryset=Doctor.objects.filter(is_active=True).order_by("name_en"),
        required=False,
        label=_("Radiologist"),
    )
    attachment = forms.FileField(required=False, label=_("Report file (PDF/image)"))
    notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), required=False, label=_("Notes")
    )
