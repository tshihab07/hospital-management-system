"""Configuration masters: tax, payment methods, notifications, hospital profile."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import MasterModel, NamedMaster


class TaxCategory(models.TextChoices):
    VAT = "vat", "VAT"
    AIT = "ait", "Advance Income Tax"
    INCOME_TAX = "income_tax", "Income Tax"
    SERVICE_CHARGE = "service_charge", "Service Charge"
    OTHER = "other", "Other"


class TaxConfig(NamedMaster):
    """NBR-compliant tax / VAT rate per category (RULES Phase 2)."""

    category = models.CharField(
        _("category"),
        max_length=30,
        choices=TaxCategory.choices,
        default=TaxCategory.VAT,
    )
    rate = models.DecimalField(
        _("rate (%)"),
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text=_("Percentage applied to the taxable amount."),
    )
    description = models.TextField(_("description"), blank=True)

    class Meta(NamedMaster.Meta):
        verbose_name = _("tax configuration")
        verbose_name_plural = _("tax configurations")


class PaymentKind(models.TextChoices):
    CASH = "cash", "Cash"
    CARD = "card", "Card"
    MOBILE = "mobile_banking", "Mobile Banking"
    BANK = "bank_transfer", "Bank Transfer"
    OTHER = "other", "Other"


class PaymentMethod(NamedMaster):
    """Accepted payment channels (RULES Phase 2)."""

    code = models.CharField(_("code"), max_length=30, unique=True)
    kind = models.CharField(
        _("kind"), max_length=20, choices=PaymentKind.choices, default=PaymentKind.CASH
    )
    charge_pct = models.DecimalField(
        _("charge (%)"), max_digits=5, decimal_places=2, default=0
    )

    class Meta(NamedMaster.Meta):
        verbose_name = _("payment method")
        verbose_name_plural = _("payment methods")


class NotificationChannel(models.TextChoices):
    SMS = "sms", "SMS"
    EMAIL = "email", "Email"


class NotificationTemplate(MasterModel):
    """Bilingual SMS / email template (RULES Phase 2)."""

    name = models.CharField(_("name"), max_length=150)
    code = models.CharField(_("code"), max_length=50, unique=True)
    channel = models.CharField(
        _("channel"),
        max_length=10,
        choices=NotificationChannel.choices,
        default=NotificationChannel.SMS,
    )
    subject_en = models.CharField(_("subject (English)"), max_length=200, blank=True)
    subject_bn = models.CharField(_("subject (Bengali)"), max_length=200, blank=True)
    body_en = models.TextField(_("body (English)"))
    body_bn = models.TextField(_("body (Bengali)"), blank=True)

    class Meta(MasterModel.Meta):
        verbose_name = _("notification template")
        verbose_name_plural = _("notification templates")

    def __str__(self) -> str:
        return f"{self.get_channel_display()} · {self.name}"


class HospitalProfile(MasterModel):
    """Singleton hospital branding & statutory information (RULES Phase 2)."""

    name_en = models.CharField(_("name (English)"), max_length=200)
    name_bn = models.CharField(_("name (Bengali)"), max_length=200, blank=True)
    address = models.TextField(_("address"), blank=True)
    city = models.CharField(_("city"), max_length=100, blank=True)
    postcode = models.CharField(_("postcode"), max_length=20, blank=True)
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    email = models.EmailField(_("email"), blank=True)
    website = models.URLField(_("website"), blank=True)
    logo = models.ImageField(_("logo"), upload_to="hospital/", null=True, blank=True)
    uhid_prefix = models.CharField(_("UHID prefix"), max_length=10, default="DHK")
    ip_prefix = models.CharField(_("IP number prefix"), max_length=10, default="IP")
    vat_reg_no = models.CharField(_("VAT registration no."), max_length=50, blank=True)
    bin_no = models.CharField(_("BIN no."), max_length=50, blank=True)
    trade_license = models.CharField(_("trade license no."), max_length=50, blank=True)
    footer_note = models.CharField(_("footer note"), max_length=255, blank=True)

    class Meta(MasterModel.Meta):
        verbose_name = _("hospital profile")
        verbose_name_plural = _("hospital profiles")
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name_en

    @classmethod
    def load(cls) -> "HospitalProfile":
        """Return the singleton profile, creating a default if none exists."""
        profile = cls.objects.order_by("pk").first()
        if profile is None:
            profile = cls.objects.create(name_en="Integrated Hospital")
        return profile
