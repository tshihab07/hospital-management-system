"""Forms for the Payroll module."""

from __future__ import annotations

import calendar

from django import forms
from django.forms import formset_factory
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.hr.models import Staff

from .models import (
    AdjustmentKind,
    PaymentMethod,
    PayrollRun,
    PayrollSetting,
    SalaryAdjustment,
    TaxBracket,
    TaxSlab,
)

MONTH_CHOICES = [(i, calendar.month_name[i]) for i in range(1, 13)]


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


class PayrollRunForm(StyledFormMixin, forms.Form):
    """Generate a monthly payroll run."""

    year = forms.IntegerField(label=_("Year"), min_value=2000, max_value=2100)
    month = forms.ChoiceField(label=_("Month"), choices=MONTH_CHOICES)
    payment_date = forms.DateField(
        label=_("Payment date"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    payment_method = forms.ChoiceField(
        label=_("Payment method"),
        choices=PaymentMethod.choices,
        initial=PaymentMethod.BANK,
    )
    notes = forms.CharField(
        label=_("Notes"), required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["year"].initial = timezone.localdate().year
        self.fields["month"].initial = timezone.localdate().month

    def clean(self):
        data = super().clean()
        year, month = data.get("year"), data.get("month")
        if year and month:
            existing = (
                PayrollRun.objects.filter(year=year, month=int(month))
                .exclude(status="cancelled")
                .first()
            )
            if existing is not None and not existing.is_editable:
                raise forms.ValidationError(
                    _("A locked payroll run already exists for this month.")
                )
        return data


class PayrollSettingForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PayrollSetting
        fields = [
            "provident_fund_rate",
            "employer_pf_rate",
            "pf_wage_basis",
            "working_days_per_month",
            "absence_wage_basis",
            "late_marks_per_absence",
            "half_day_factor",
            "standard_deduction_ratio",
            "standard_deduction_cap",
            "annual_months",
            "minimum_tax",
            "house_rent_exemption_enabled",
            "bank_routing_default",
            "beftn_company_name",
            "beftn_company_account",
            "beftn_bank_code",
            "notes",
        ]


class TaxSlabForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TaxSlab
        fields = [
            "assessment_year",
            "category",
            "tax_free_threshold",
            "minimum_tax",
            "source",
            "is_active",
            "notes",
        ]


class TaxBracketForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TaxBracket
        fields = ["band_amount", "rate", "label"]


TaxBracketFormSet = formset_factory(TaxBracketForm, extra=6, can_delete=True)


class SalaryAdjustmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SalaryAdjustment
        fields = ["staff", "year", "month", "kind", "amount", "reason"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = Staff.objects.filter(is_active=True).order_by(
            "name_en"
        )
        today = timezone.localdate()
        self.fields["year"].initial = today.year
        self.fields["month"].initial = today.month
        self.fields["kind"].choices = AdjustmentKind.choices
