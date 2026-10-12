"""Clinical masters: drugs, lab/radiology tests, procedures and diagnoses."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import CodedMaster, MasterModel


class DrugForm(models.TextChoices):
    TABLET = "tablet", "Tablet"
    CAPSULE = "capsule", "Capsule"
    SYRUP = "syrup", "Syrup"
    SUSPENSION = "suspension", "Suspension"
    INJECTION = "injection", "Injection"
    INFUSION = "infusion", "Infusion"
    CREAM = "cream", "Cream"
    OINTMENT = "ointment", "Ointment"
    DROPS = "drops", "Drops"
    INHALER = "inhaler", "Inhaler"
    SUPPOSITORY = "suppository", "Suppository"
    OTHER = "other", "Other"


class Drug(MasterModel):
    """Drug / medicine master (RULES Phase 2)."""

    generic_name = models.CharField(_("generic name"), max_length=200, db_index=True)
    brand_name = models.CharField(_("brand name"), max_length=200, blank=True)
    form = models.CharField(
        _("form"), max_length=20, choices=DrugForm.choices, default=DrugForm.TABLET
    )
    strength = models.CharField(_("strength"), max_length=100, blank=True)
    unit = models.CharField(_("unit"), max_length=50, blank=True)
    unit_price = models.DecimalField(
        _("unit price"), max_digits=12, decimal_places=2, default=0
    )
    reorder_level = models.PositiveIntegerField(_("reorder level"), default=0)
    description = models.TextField(_("description"), blank=True)

    class Meta(MasterModel.Meta):
        verbose_name = _("drug")
        verbose_name_plural = _("drugs")
        ordering = ["generic_name", "brand_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["generic_name", "brand_name", "form", "strength"],
                name="uniq_drug_variant",
            )
        ]

    def __str__(self) -> str:
        parts = [self.generic_name, self.brand_name, self.strength]
        return " ".join(p for p in parts if p).strip() or f"Drug #{self.pk}"


class LabTest(CodedMaster):
    """Laboratory test master (RULES Phase 2)."""

    category = models.CharField(_("category"), max_length=100, blank=True)
    price = models.DecimalField(_("price"), max_digits=12, decimal_places=2, default=0)
    reference_range = models.CharField(_("reference range"), max_length=200, blank=True)
    unit = models.CharField(_("unit"), max_length=50, blank=True)
    sample_type = models.CharField(_("sample type"), max_length=100, blank=True)

    class Meta(CodedMaster.Meta):
        verbose_name = _("lab test")
        verbose_name_plural = _("lab tests")


class RadiologyModality(models.TextChoices):
    XRAY = "xray", "X-Ray"
    USG = "usg", "Ultrasound (USG)"
    CT = "ct", "CT Scan"
    MRI = "mri", "MRI"
    OTHER = "other", "Other"


class RadiologyTest(CodedMaster):
    """Radiology / imaging test master (RULES Phase 2)."""

    modality = models.CharField(
        _("modality"),
        max_length=20,
        choices=RadiologyModality.choices,
        default=RadiologyModality.XRAY,
    )
    price = models.DecimalField(_("price"), max_digits=12, decimal_places=2, default=0)
    preparation = models.TextField(_("preparation"), blank=True)

    class Meta(CodedMaster.Meta):
        verbose_name = _("radiology test")
        verbose_name_plural = _("radiology tests")


class Procedure(CodedMaster):
    """Surgical / minor procedure master (RULES Phase 2)."""

    category = models.CharField(_("category"), max_length=100, blank=True)
    price = models.DecimalField(_("price"), max_digits=12, decimal_places=2, default=0)
    description = models.TextField(_("description"), blank=True)

    class Meta(CodedMaster.Meta):
        verbose_name = _("procedure")
        verbose_name_plural = _("procedures")


class Diagnosis(CodedMaster):
    """ICD-10 diagnosis master (searchable)."""

    category = models.CharField(_("category / chapter"), max_length=200, blank=True)

    class Meta(CodedMaster.Meta):
        verbose_name = _("diagnosis")
        verbose_name_plural = _("diagnoses")

    def __str__(self) -> str:
        return f"{self.code} · {self.name}"
