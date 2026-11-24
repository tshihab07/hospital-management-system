"""Forms for the Billing & Payments module."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.patients.models import Patient

from .gateways import GATEWAY_MODES
from .models import Advance, Bill, CreditNote, Payment, Refund, ServicePackage


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


def _patients():
    return Patient.objects.order_by("full_name_en")


class BillForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Bill
        fields = ["patient", "admission", "bill_type", "vat_rate", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = _patients()
        self.fields["admission"].required = False


class PaymentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["method", "amount", "txn_ref", "gateway_ref", "notes"]

    def __init__(self, *args, **kwargs):
        self.bill = kwargs.pop("bill", None)
        super().__init__(*args, **kwargs)
        if self.bill is not None:
            self.fields["amount"].initial = self.bill.due_amount
            self.fields["amount"].widget.attrs["max"] = str(self.bill.due_amount)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if self.bill is not None and amount > self.bill.due_amount:
            raise forms.ValidationError(_("Amount exceeds the outstanding balance."))
        return amount


class OnlinePaymentForm(StyledFormMixin, forms.Form):
    """Initiate an online (gateway) payment for a bill."""

    method = forms.ChoiceField(label=_("Channel"), choices=[])
    amount = forms.DecimalField(
        label=_("Amount"), min_value=0, max_digits=12, decimal_places=2
    )

    def __init__(self, *args, **kwargs):
        from .models import PaymentMode

        self.bill = kwargs.pop("bill", None)
        super().__init__(*args, **kwargs)
        self.fields["method"].choices = [
            (m, PaymentMode(m).label) for m in sorted(GATEWAY_MODES)
        ]
        if self.bill is not None:
            self.fields["amount"].initial = self.bill.due_amount

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if self.bill is not None and amount > self.bill.due_amount:
            raise forms.ValidationError(_("Amount exceeds the outstanding balance."))
        return amount


class CreditNoteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CreditNote
        fields = ["amount", "reason"]

    def __init__(self, *args, **kwargs):
        self.bill = kwargs.pop("bill", None)
        super().__init__(*args, **kwargs)
        if self.bill is not None:
            self.fields["amount"].widget.attrs["max"] = str(self.bill.total)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if self.bill is not None and amount > self.bill.total:
            raise forms.ValidationError(_("Amount exceeds the bill total."))
        return amount


class PackageBillForm(StyledFormMixin, forms.Form):
    """Generate a PACKAGE invoice from a bundled rate card."""

    patient = forms.ModelChoiceField(label=_("Patient"), queryset=Patient.objects.none())
    package = forms.ModelChoiceField(
        label=_("Package"), queryset=ServicePackage.objects.none()
    )
    vat_rate = forms.DecimalField(
        label=_("VAT rate (%)"), min_value=0, max_digits=5, decimal_places=2, required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = _patients()
        self.fields["package"].queryset = ServicePackage.objects.filter(is_active=True)


class DiscountForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(label=_("Discount amount"), min_value=0, max_digits=12)
    reason = forms.CharField(label=_("Reason"), max_length=255, required=False)


class AdvanceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Advance
        fields = ["patient", "admission", "amount", "method", "txn_ref", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = _patients()
        self.fields["admission"].required = False


class RefundForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Refund
        fields = ["bill", "payment", "amount", "method", "reason", "txn_ref"]

    def __init__(self, *args, **kwargs):
        bill = kwargs.pop("bill", None)
        super().__init__(*args, **kwargs)
        self.fields["bill"].required = False
        self.fields["payment"].required = False
        if bill is not None:
            self.fields["bill"].initial = bill
            self.fields["payment"].queryset = bill.payments.all()
            self.fields["bill"].widget = forms.HiddenInput()
