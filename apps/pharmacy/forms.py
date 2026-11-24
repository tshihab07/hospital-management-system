"""Forms for the Pharmacy & Inventory module."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.masters.models import Drug

from .models import PharmacyStore, StoreType, Vendor


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


def _stores(central_only: bool = False):
    qs = PharmacyStore.objects.filter(is_active=True)
    if central_only:
        qs = qs.filter(store_type=StoreType.CENTRAL)
    return qs.order_by("name")


def _drugs():
    return Drug.objects.order_by("generic_name")


class StoreForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PharmacyStore
        fields = ["name", "code", "store_type", "location", "is_active", "notes"]


class VendorForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["name", "contact_person", "phone", "email", "address", "is_active"]


class StockBatchForm(StyledFormMixin, forms.Form):
    store = forms.ModelChoiceField(
        queryset=PharmacyStore.objects.none(), label=_("Store")
    )
    drug = forms.ModelChoiceField(queryset=Drug.objects.none(), label=_("Drug"))
    batch_no = forms.CharField(max_length=60, label=_("Batch no."))
    expiry_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Expiry date"),
    )
    quantity = forms.IntegerField(min_value=0, initial=0, label=_("Quantity"))
    purchase_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        initial=0,
        label=_("Purchase price"),
    )
    mrp = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False, initial=0, label=_("MRP")
    )
    notes = forms.CharField(max_length=255, required=False, label=_("Notes"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["store"].queryset = _stores()
        self.fields["drug"].queryset = _drugs()


class StockAdjustForm(StyledFormMixin, forms.Form):
    new_quantity = forms.IntegerField(min_value=0, label=_("New quantity"))
    reason = forms.CharField(max_length=255, label=_("Reason"))


class ReturnToVendorForm(StyledFormMixin, forms.Form):
    quantity = forms.IntegerField(min_value=1, label=_("Quantity"))
    notes = forms.CharField(max_length=255, required=False, label=_("Notes"))


class TransferForm(StyledFormMixin, forms.Form):
    from_store = forms.ModelChoiceField(
        queryset=PharmacyStore.objects.none(), label=_("From store")
    )
    to_store = forms.ModelChoiceField(
        queryset=PharmacyStore.objects.none(), label=_("To store")
    )
    drug = forms.ModelChoiceField(queryset=Drug.objects.none(), label=_("Drug"))
    quantity = forms.IntegerField(min_value=1, label=_("Quantity"))
    notes = forms.CharField(max_length=255, required=False, label=_("Notes"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from_store"].queryset = _stores()
        self.fields["to_store"].queryset = _stores()
        self.fields["drug"].queryset = _drugs()


class DispenseForm(StyledFormMixin, forms.Form):
    store = forms.ModelChoiceField(
        queryset=PharmacyStore.objects.none(), label=_("Dispense from store")
    )
    notes = forms.CharField(max_length=255, required=False, label=_("Notes"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["store"].queryset = _stores()


class RequisitionForm(StyledFormMixin, forms.Form):
    store = forms.ModelChoiceField(
        queryset=PharmacyStore.objects.none(), label=_("Store")
    )
    needed_by = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Needed by"),
    )
    notes = forms.CharField(required=False, label=_("Notes"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["store"].queryset = _stores()


class PurchaseOrderForm(StyledFormMixin, forms.Form):
    vendor = forms.ModelChoiceField(queryset=Vendor.objects.none(), label=_("Vendor"))
    store = forms.ModelChoiceField(
        queryset=PharmacyStore.objects.none(), label=_("Store")
    )
    notes = forms.CharField(required=False, label=_("Notes"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vendor"].queryset = Vendor.objects.filter(is_active=True).order_by(
            "name"
        )
        self.fields["store"].queryset = _stores()


class PurchaseOrderItemRowForm(StyledFormMixin, forms.Form):
    drug = forms.ModelChoiceField(queryset=Drug.objects.none(), label=_("Drug"))
    quantity = forms.IntegerField(min_value=1, initial=1, label=_("Qty"))
    unit_price = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        initial=0,
        label=_("Unit price"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drug"].queryset = _drugs()


class GRNForm(StyledFormMixin, forms.Form):
    received_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Received date"),
    )
    notes = forms.CharField(required=False, label=_("Notes"))


class GRNItemRowForm(StyledFormMixin, forms.Form):
    drug = forms.ModelChoiceField(queryset=Drug.objects.none(), label=_("Drug"))
    batch_no = forms.CharField(max_length=60, label=_("Batch no."))
    expiry_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Expiry"),
    )
    quantity = forms.IntegerField(min_value=0, initial=0, label=_("Qty"))
    purchase_price = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False, initial=0, label=_("Cost")
    )
    mrp = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False, initial=0, label=_("MRP")
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drug"].queryset = _drugs()
