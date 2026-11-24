"""Forms for the Reports & Analytics module (RULES Phase 16)."""

from __future__ import annotations

import re

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES

from .models import ReportSchedule

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class StyledFormMixin:
    """Apply IHMS input styling to every widget automatically."""

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


class ReportFilterForm(StyledFormMixin, forms.Form):
    """Shared date-window filter used by every report view."""

    start = forms.DateField(
        label=_("From"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    end = forms.DateField(
        label=_("To"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end and start > end:
            raise forms.ValidationError(
                _("The start date must be before the end date.")
            )
        return data


class ReportScheduleForm(StyledFormMixin, forms.ModelForm):
    """Create/edit a recurring report schedule.

    The recipient list is validated as a free-text block of comma or newline
    separated email addresses.
    """

    class Meta:
        model = ReportSchedule
        fields = [
            "name",
            "report_type",
            "frequency",
            "report_format",
            "recipients",
            "is_active",
        ]
        widgets = {
            "parameters": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipients"].widget = forms.Textarea(
            attrs={
                "class": INPUT_CLASSES,
                "rows": 3,
                "placeholder": "finance@hospital.test, admin@hospital.test",
            }
        )
        self.fields["next_run"] = forms.DateTimeField(
            label=_("First run"),
            required=False,
            widget=forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": INPUT_CLASSES}
            ),
        )

    def clean_recipients(self) -> str:
        raw = self.cleaned_data.get("recipients", "") or ""
        addresses = [
            addr.strip()
            for addr in raw.replace(",", "\n").splitlines()
            if addr.strip()
        ]
        invalid = [addr for addr in addresses if not EMAIL_RE.match(addr)]
        if invalid:
            raise forms.ValidationError(
                _("Invalid email address(es): %(bad)s") % {"bad": ", ".join(invalid)}
            )
        return "\n".join(addresses)

    def clean(self):
        data = super().clean()
        if (
            data.get("is_active")
            and not data.get("recipients")
            and not self.instance.pk
        ):
            raise forms.ValidationError(
                _("Add at least one recipient for an active schedule.")
            )
        return data

    def save(self, commit: bool = True) -> ReportSchedule:
        schedule = super().save(commit=False)
        if self.cleaned_data.get("next_run"):
            schedule.next_run = self.cleaned_data["next_run"]
        elif schedule.next_run is None:
            schedule.next_run = timezone.now()
        if commit:
            schedule.save()
            self.save_m2m()
        return schedule
