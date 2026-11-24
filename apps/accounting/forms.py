"""Forms for the Accounting & Financial Reports module."""

from __future__ import annotations

from django import forms
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.patients.models import Patient  # noqa: F401  (kept for parity/future filters)

from .models import Account, AccountType, Expense, JournalEntry, VendorPayment


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


def _postable_accounts():
    return Account.objects.filter(is_active=True, is_group=False).order_by("code")


class DateRangeForm(StyledFormMixin, forms.Form):
    """Shared date-window filter used by most financial reports."""

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


class AsOfForm(StyledFormMixin, forms.Form):
    as_of = forms.DateField(
        label=_("As of"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )


class AccountForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            "code",
            "name",
            "name_bn",
            "account_type",
            "normal_balance",
            "parent",
            "is_group",
            "is_active",
            "opening_balance",
            "description",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = Account.objects.filter(
            is_active=True, is_group=True
        ).order_by("code")
        self.fields["parent"].required = False
        self.fields["normal_balance"].required = False


class JournalLineForm(StyledFormMixin, forms.Form):
    account = forms.ModelChoiceField(
        label=_("Account"), queryset=_postable_accounts(), required=False
    )
    description = forms.CharField(
        label=_("Description"), max_length=255, required=False
    )
    debit = forms.DecimalField(
        label=_("Debit"), min_value=0, max_digits=14, decimal_places=2, required=False
    )
    credit = forms.DecimalField(
        label=_("Credit"), min_value=0, max_digits=14, decimal_places=2, required=False
    )

    def clean(self):
        data = super().clean()
        account = data.get("account")
        debit = data.get("debit")
        credit = data.get("credit")
        if not account and not debit and not credit:
            return data
        if not account:
            raise forms.ValidationError(_("Select an account for this line."))
        if debit and credit:
            raise forms.ValidationError(
                _("A line cannot have both a debit and a credit amount.")
            )
        if not debit and not credit:
            raise forms.ValidationError(
                _("Enter a debit or a credit amount for this line.")
            )
        return data


JournalLineFormSet = formset_factory(JournalLineForm, extra=6, can_delete=True)


class JournalEntryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = JournalEntry
        fields = ["date", "memo", "reference"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class ExpenseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            "date",
            "category",
            "paid_from",
            "amount",
            "description",
            "vendor",
            "reference",
        ]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Account.objects.filter(
            is_active=True, is_group=False, account_type=AccountType.EXPENSE
        ).order_by("code")
        self.fields["paid_from"].queryset = Account.objects.filter(
            is_active=True,
            is_group=False,
            account_type__in=[AccountType.ASSET, AccountType.LIABILITY],
        ).order_by("code")
        self.fields["vendor"].required = False


class VendorPaymentForm(StyledFormMixin, forms.ModelForm):
    amount = forms.DecimalField(
        label=_("Amount"), min_value=0, max_digits=14, decimal_places=2
    )
    method = forms.ChoiceField(
        label=_("Method"),
        choices=[
            ("cash", _("Cash")),
            ("bank", _("Bank transfer")),
            ("card", _("Card")),
            ("bkash", _("bKash")),
            ("nagad", _("Nagad")),
            ("rocket", _("Rocket")),
        ],
    )

    class Meta:
        model = VendorPayment
        fields = ["date", "vendor", "amount", "method", "grn", "reference", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["grn"].required = False
        self.fields["vendor"].queryset = self.fields["vendor"].queryset.order_by("name")
