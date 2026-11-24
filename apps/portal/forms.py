"""Forms for the Patient Portal (RULES Phase 15)."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import INPUT_CLASSES
from apps.billing.gateways import GATEWAY_MODES
from apps.opd.models import AppointmentType, AvailabilitySlot, Doctor
from apps.patients.models import Patient

from .models import MedicalRecordRequest, NotificationPreference

User = get_user_model()


class PortalFormMixin:
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


# ---------------------------------------------------------------------------
# Registration / verification
# ---------------------------------------------------------------------------
class PortalRegistrationForm(PortalFormMixin, forms.Form):
    """Create a portal account for an existing patient (UHID + phone match)."""

    uhid = forms.CharField(
        label=_("UHID"),
        max_length=20,
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
        help_text=_("The UHID printed on your hospital card."),
    )
    phone = forms.CharField(
        label=_("Registered phone"),
        max_length=20,
        widget=forms.TextInput(attrs={"autocomplete": "tel"}),
    )
    email = forms.EmailField(
        label=_("Email (optional)"),
        required=False,
        help_text=_("Used to send your one-time verification code."),
    )
    password1 = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label=_("Confirm password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

    def clean_uhid(self) -> str:
        return (self.cleaned_data.get("uhid") or "").strip()

    def clean_password2(self) -> str:
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("The two password fields did not match."))
        if p2:
            validate_password(p2, user=None)
        return p2


class PortalVerificationForm(PortalFormMixin, forms.Form):
    code = forms.CharField(
        label=_("Verification code"),
        max_length=6,
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}
        ),
    )

    def clean_code(self) -> str:
        return (self.cleaned_data.get("code") or "").strip()


class PortalLoginForm(PortalFormMixin, AuthenticationForm):
    """Patient-side login (username is the UHID)."""

    username = forms.CharField(
        label=_("UHID"),
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    error_messages = {
        "invalid_login": _("Invalid UHID or password."),
        "inactive": _("Please verify your account before signing in."),
    }


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
class PortalProfileForm(PortalFormMixin, forms.ModelForm):
    """Contact details a patient may maintain themselves."""

    class Meta:
        model = Patient
        fields = [
            "phone",
            "alt_phone",
            "email",
            "address",
            "permanent_address",
            "city",
            "postcode",
            "emergency_contact_name",
            "emergency_contact_relation",
            "emergency_contact_phone",
        ]


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
class AppointmentBookingForm(PortalFormMixin, forms.Form):
    doctor = forms.ModelChoiceField(
        label=_("Doctor"), queryset=Doctor.objects.filter(is_active=True)
    )
    appt_date = forms.DateField(
        label=_("Date"), widget=forms.DateInput(attrs={"type": "date"})
    )
    slot = forms.ModelChoiceField(
        label=_("Time block"),
        required=False,
        queryset=AvailabilitySlot.objects.none(),
    )
    visit_type = forms.ChoiceField(
        label=_("Visit type"),
        choices=AppointmentType.choices,
        initial=AppointmentType.NEW,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = Doctor.objects.filter(
            is_active=True
        ).order_by("name_en")
        doctor_id = None
        if self.is_bound:
            doctor_id = self.data.get("doctor")
        else:
            doctor_id = self.initial.get("doctor")
        if doctor_id:
            self.fields["slot"].queryset = AvailabilitySlot.objects.filter(
                doctor_id=doctor_id, is_active=True
            ).order_by("weekday", "start_time")

    def clean(self):
        cleaned = super().clean()
        slot = cleaned.get("slot")
        appt_date = cleaned.get("appt_date")
        doctor = cleaned.get("doctor")
        if slot and doctor and slot.doctor_id != doctor.pk:
            self.add_error("slot", _("This time block does not belong to that doctor."))
        if slot and appt_date and slot.weekday != appt_date.weekday():
            self.add_error(
                "slot", _("This time block is not available on the chosen date.")
            )
        return cleaned


class AppointmentRescheduleForm(AppointmentBookingForm):
    """Same rules; the doctor is fixed by the original appointment."""

    def __init__(self, *args, **kwargs):
        self.doctor = kwargs.pop("doctor", None)
        super().__init__(*args, **kwargs)
        if self.doctor is not None:
            self.fields["doctor"].initial = self.doctor
            self.fields["doctor"].widget = forms.HiddenInput()
            self.fields["doctor"].required = False
            self.fields["slot"].queryset = AvailabilitySlot.objects.filter(
                doctor=self.doctor, is_active=True
            ).order_by("weekday", "start_time")


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class PortalPaymentForm(PortalFormMixin, forms.Form):
    method = forms.ChoiceField(label=_("Payment method"), choices=[])
    amount = forms.DecimalField(
        label=_("Amount"), min_value=0, max_digits=12, decimal_places=2
    )

    def __init__(self, *args, **kwargs):
        self.bill = kwargs.pop("bill", None)
        super().__init__(*args, **kwargs)

        self.fields["method"].choices = [
            (mode, self._label(mode)) for mode in sorted(GATEWAY_MODES)
        ]
        if self.bill is not None:
            self.fields["amount"].initial = self.bill.due_amount
            self.fields["amount"].widget.attrs["max"] = str(self.bill.due_amount)

    @staticmethod
    def _label(mode: str) -> str:
        return {
            "card": _("Card"),
            "bkash": _("bKash"),
            "nagad": _("Nagad"),
            "rocket": _("Rocket"),
        }.get(mode, mode)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if self.bill is not None and amount > self.bill.due_amount:
            raise ValidationError(_("Amount exceeds the outstanding balance."))
        return amount


# ---------------------------------------------------------------------------
# Medical record requests & notifications
# ---------------------------------------------------------------------------
class MedicalRecordRequestForm(PortalFormMixin, forms.ModelForm):
    class Meta:
        model = MedicalRecordRequest
        fields = ["purpose", "records_from", "records_to"]
        widgets = {
            "records_from": forms.DateInput(attrs={"type": "date"}),
            "records_to": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("records_from")
        end = cleaned.get("records_to")
        if start and end and start > end:
            self.add_error("records_to", _("End date must be on or after the start."))
        return cleaned


class NotificationPreferenceForm(PortalFormMixin, forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = [
            "appointment_reminders",
            "lab_report_ready",
            "bill_due",
            "admission_updates",
            "email_enabled",
            "sms_enabled",
        ]
