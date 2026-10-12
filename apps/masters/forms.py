"""ModelForms for every master, plus the CSV import form."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES

from .models import (Bed, BedType, Department, Designation, Diagnosis, Drug,
                     HospitalProfile, LabTest, NotificationTemplate,
                     PaymentMethod, Procedure, RadiologyTest, TaxConfig, Ward)


class StyledModelForm(forms.ModelForm):
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


class DepartmentForm(StyledModelForm):
    class Meta:
        model = Department
        fields = ["name", "code", "type", "head", "description", "is_active"]


class DesignationForm(StyledModelForm):
    class Meta:
        model = Designation
        fields = ["name", "code", "category", "description", "is_active"]


class WardForm(StyledModelForm):
    class Meta:
        model = Ward
        fields = [
            "name",
            "code",
            "type",
            "floor",
            "department",
            "description",
            "is_active",
        ]


class BedTypeForm(StyledModelForm):
    class Meta:
        model = BedType
        fields = ["name", "daily_rate", "description", "is_active"]


class BedForm(StyledModelForm):
    class Meta:
        model = Bed
        fields = ["ward", "bed_no", "bed_type", "daily_rate", "status", "is_active"]


class DrugForm(StyledModelForm):
    class Meta:
        model = Drug
        fields = [
            "generic_name",
            "brand_name",
            "form",
            "strength",
            "unit",
            "unit_price",
            "reorder_level",
            "description",
            "is_active",
        ]


class LabTestForm(StyledModelForm):
    class Meta:
        model = LabTest
        fields = [
            "code",
            "name",
            "category",
            "price",
            "reference_range",
            "unit",
            "sample_type",
            "is_active",
        ]


class RadiologyTestForm(StyledModelForm):
    class Meta:
        model = RadiologyTest
        fields = ["code", "name", "modality", "price", "preparation", "is_active"]


class ProcedureForm(StyledModelForm):
    class Meta:
        model = Procedure
        fields = ["code", "name", "category", "price", "description", "is_active"]


class DiagnosisForm(StyledModelForm):
    class Meta:
        model = Diagnosis
        fields = ["code", "name", "category", "is_active"]


class TaxConfigForm(StyledModelForm):
    class Meta:
        model = TaxConfig
        fields = ["name", "category", "rate", "description", "is_active"]


class PaymentMethodForm(StyledModelForm):
    class Meta:
        model = PaymentMethod
        fields = ["name", "code", "kind", "charge_pct", "is_active"]


class NotificationTemplateForm(StyledModelForm):
    class Meta:
        model = NotificationTemplate
        fields = [
            "name",
            "code",
            "channel",
            "subject_en",
            "subject_bn",
            "body_en",
            "body_bn",
            "is_active",
        ]


class HospitalProfileForm(StyledModelForm):
    class Meta:
        model = HospitalProfile
        fields = [
            "name_en",
            "name_bn",
            "address",
            "city",
            "postcode",
            "phone",
            "email",
            "website",
            "logo",
            "uhid_prefix",
            "ip_prefix",
            "vat_reg_no",
            "bin_no",
            "trade_license",
            "footer_note",
        ]


class CsvImportForm(forms.Form):
    """Upload a CSV file to bulk-create master records."""

    csv_file = forms.FileField(
        label=_("CSV file"),
        help_text=_("First row must be the header matching the template columns."),
        widget=forms.ClearableFileInput(
            attrs={"class": INPUT_CLASSES, "accept": ".csv"}
        ),
    )
    skip_errors = forms.BooleanField(
        label=_("Skip invalid rows instead of aborting"),
        required=False,
        initial=True,
    )
