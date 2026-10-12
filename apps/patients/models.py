"""Patient Core models (RULES Phase 3).

The :class:`Patient` entity is the center of the universe (RULES §1, Law of
Core Entity). Everything clinical or financial references it by UHID.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import SoftDeleteModel, TimeStampedModel


class Gender(models.TextChoices):
    MALE = "male", _("Male")
    FEMALE = "female", _("Female")
    OTHER = "other", _("Other")


class BloodGroup(models.TextChoices):
    A_POS = "a+", _("A+")
    A_NEG = "a-", _("A-")
    B_POS = "b+", _("B+")
    B_NEG = "b-", _("B-")
    AB_POS = "ab+", _("AB+")
    AB_NEG = "ab-", _("AB-")
    O_POS = "o+", _("O+")
    O_NEG = "o-", _("O-")
    UNKNOWN = "unknown", _("Unknown")


class PatientType(models.TextChoices):
    GENERAL = "general", _("General")
    VIP = "vip", _("VIP")
    CORPORATE = "corporate", _("Corporate")
    STAFF = "staff", _("Staff")


class MaritalStatus(models.TextChoices):
    SINGLE = "single", _("Single")
    MARRIED = "married", _("Married")
    DIVORCED = "divorced", _("Divorced")
    WIDOWED = "widowed", _("Widowed")
    UNKNOWN = "unknown", _("Unknown")


class Relation(models.TextChoices):
    SELF = "self", _("Self")
    SPOUSE = "spouse", _("Spouse")
    FATHER = "father", _("Father")
    MOTHER = "mother", _("Mother")
    SON = "son", _("Son")
    DAUGHTER = "daughter", _("Daughter")
    BROTHER = "brother", _("Brother")
    SISTER = "sister", _("Sister")
    OTHER = "other", _("Other")


class PatientSequence(models.Model):
    """Per-year monotonic counter backing UHID generation (row-locked)."""

    year = models.PositiveIntegerField(unique=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("patient sequence")
        verbose_name_plural = _("patient sequences")
        ordering = ["year"]

    def __str__(self) -> str:  # pragma: no cover - admin nicety
        return f"{self.year} → {self.last_number}"


class Patient(SoftDeleteModel):
    """A registered patient (RULES Phase 3)."""

    uhid = models.CharField(
        _("UHID"),
        max_length=20,
        unique=True,
        editable=False,
        db_index=True,
        help_text=_("Unique Hospital ID; immutable once assigned."),
    )
    # Demographics ---------------------------------------------------------
    full_name_en = models.CharField(
        _("full name (English)"), max_length=200, db_index=True
    )
    full_name_bn = models.CharField(
        _("full name (Bengali)"), max_length=200, blank=True
    )
    date_of_birth = models.DateField(_("date of birth"), null=True, blank=True)
    age_years = models.PositiveSmallIntegerField(
        _("age (years)"),
        null=True,
        blank=True,
        help_text=_("Use when the date of birth is unknown."),
    )
    gender = models.CharField(_("gender"), max_length=10, choices=Gender.choices)
    blood_group = models.CharField(
        _("blood group"),
        max_length=10,
        choices=BloodGroup.choices,
        default=BloodGroup.UNKNOWN,
    )
    marital_status = models.CharField(
        _("marital status"),
        max_length=10,
        choices=MaritalStatus.choices,
        default=MaritalStatus.UNKNOWN,
    )
    occupation = models.CharField(_("occupation"), max_length=120, blank=True)
    nationality = models.CharField(
        _("nationality"), max_length=80, default="Bangladeshi"
    )

    # Identity & contact ---------------------------------------------------
    nid = models.CharField(_("NID"), max_length=30, blank=True, db_index=True)
    phone = models.CharField(_("phone"), max_length=20, db_index=True)
    alt_phone = models.CharField(_("alternate phone"), max_length=20, blank=True)
    email = models.EmailField(_("email"), blank=True)
    address = models.TextField(_("present address"), blank=True)
    permanent_address = models.TextField(_("permanent address"), blank=True)
    city = models.CharField(_("city"), max_length=100, blank=True)
    postcode = models.CharField(_("postcode"), max_length=20, blank=True)

    # Guardian & emergency contact ----------------------------------------
    guardian_name = models.CharField(_("guardian name"), max_length=200, blank=True)
    guardian_relation = models.CharField(
        _("guardian relation"),
        max_length=10,
        choices=Relation.choices,
        blank=True,
    )
    emergency_contact_name = models.CharField(
        _("emergency contact name"), max_length=200, blank=True
    )
    emergency_contact_relation = models.CharField(
        _("emergency contact relation"),
        max_length=10,
        choices=Relation.choices,
        blank=True,
    )
    emergency_contact_phone = models.CharField(
        _("emergency contact phone"), max_length=20, blank=True
    )

    # Administrative -------------------------------------------------------
    patient_type = models.CharField(
        _("patient type"),
        max_length=20,
        choices=PatientType.choices,
        default=PatientType.GENERAL,
    )
    photo = models.ImageField(_("photo"), upload_to="patients/", null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="patients_registered",
        verbose_name=_("registered by"),
    )
    portal_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="patient_profile",
        verbose_name=_("portal account"),
        help_text=_("Portal account stub — reserved for Phase 15."),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("patient")
        verbose_name_plural = _("patients")
        ordering = ["-created_at"]
        permissions = [("merge_patient", _("Can merge duplicate patients"))]
        indexes = [
            models.Index(fields=["full_name_en"]),
            models.Index(fields=["phone"]),
        ]

    def __str__(self) -> str:
        return f"{self.uhid} · {self.full_name_en}"

    # -- derived -----------------------------------------------------------
    @property
    def age(self) -> int | None:
        """Age in completed years, from DOB when available."""
        if self.date_of_birth:
            today = timezone.localdate()
            years = today.year - self.date_of_birth.year
            if (today.month, today.day) < (
                self.date_of_birth.month,
                self.date_of_birth.day,
            ):
                years -= 1
            return years
        return self.age_years

    @property
    def display_name(self) -> str:
        return self.full_name_en or self.full_name_bn

    def clean(self) -> None:
        if not self.date_of_birth and self.age_years is None:
            raise ValidationError(
                {"age_years": _("Provide a date of birth or an age.")}
            )
        if self.date_of_birth and self.date_of_birth > timezone.localdate():
            raise ValidationError(
                {"date_of_birth": _("Date of birth cannot be in the future.")}
            )

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).all_objects.filter(pk=self.pk).only("uhid").first()
            if original and original.uhid != self.uhid:
                raise ValidationError(_("UHID is immutable and cannot be changed."))
        super().save(*args, **kwargs)


class DocumentCategory(models.TextChoices):
    REPORT = "report", _("Report")
    PRESCRIPTION = "prescription", _("Prescription")
    ID = "id", _("Identity document")
    CONSENT = "consent", _("Consent form")
    OTHER = "other", _("Other")


class PatientDocument(TimeStampedModel):
    """A scanned document attached to a patient (RULES Phase 3)."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name=_("patient"),
    )
    title = models.CharField(_("title"), max_length=200)
    category = models.CharField(
        _("category"),
        max_length=20,
        choices=DocumentCategory.choices,
        default=DocumentCategory.OTHER,
    )
    file = models.FileField(_("file"), upload_to="patients/documents/")
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="patient_documents_uploaded",
        verbose_name=_("uploaded by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("patient document")
        verbose_name_plural = _("patient documents")

    def __str__(self) -> str:
        return self.title
