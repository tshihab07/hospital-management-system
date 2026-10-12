"""Organisation masters: departments, designations, wards and beds."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import MasterModel, NamedMaster


class DepartmentType(models.TextChoices):
    OPD = "opd", "OPD"
    IPD = "ipd", "IPD"
    ICU = "icu", "ICU / CCU"
    OT = "ot", "Operation Theatre"
    LAB = "lab", "Laboratory"
    RADIOLOGY = "radiology", "Radiology"
    PHARMACY = "pharmacy", "Pharmacy"
    EMERGENCY = "emergency", "Emergency"
    ADMIN = "admin", "Administration"
    OTHER = "other", "Other"


class Department(NamedMaster):
    """A clinical or administrative department (RULES Phase 2)."""

    code = models.CharField(_("code"), max_length=30, unique=True)
    type = models.CharField(
        _("type"),
        max_length=20,
        choices=DepartmentType.choices,
        default=DepartmentType.OTHER,
    )
    head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="departments_headed",
        verbose_name=_("head"),
    )
    description = models.TextField(_("description"), blank=True)

    class Meta(NamedMaster.Meta):
        verbose_name = _("department")
        verbose_name_plural = _("departments")


class DesignationCategory(models.TextChoices):
    CLINICAL = "clinical", "Clinical"
    NURSING = "nursing", "Nursing"
    TECHNICAL = "technical", "Technical"
    ADMIN = "admin", "Administrative"
    SUPPORT = "support", "Support"


class Designation(NamedMaster):
    """A job title / designation (RULES Phase 2)."""

    code = models.CharField(_("code"), max_length=30, unique=True)
    category = models.CharField(
        _("category"),
        max_length=20,
        choices=DesignationCategory.choices,
        default=DesignationCategory.CLINICAL,
    )
    description = models.TextField(_("description"), blank=True)

    class Meta(NamedMaster.Meta):
        verbose_name = _("designation")
        verbose_name_plural = _("designations")


class WardType(models.TextChoices):
    GENERAL = "general", "General"
    CABIN = "cabin", "Cabin"
    ICU = "icu", "ICU"
    CCU = "ccu", "CCU"
    HDU = "hdu", "HDU"
    NICU = "nicu", "NICU"
    EMERGENCY = "emergency", "Emergency"
    OTHER = "other", "Other"


class Ward(NamedMaster):
    """A physical ward that contains beds."""

    code = models.CharField(_("code"), max_length=30, unique=True)
    type = models.CharField(
        _("type"), max_length=20, choices=WardType.choices, default=WardType.GENERAL
    )
    floor = models.IntegerField(_("floor"), default=0)
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wards",
        verbose_name=_("department"),
    )
    description = models.TextField(_("description"), blank=True)

    class Meta(NamedMaster.Meta):
        verbose_name = _("ward")
        verbose_name_plural = _("wards")


class BedType(NamedMaster):
    """A bed category with its default daily charge."""

    daily_rate = models.DecimalField(
        _("daily rate"), max_digits=12, decimal_places=2, default=0
    )
    description = models.TextField(_("description"), blank=True)

    class Meta(NamedMaster.Meta):
        verbose_name = _("bed type")
        verbose_name_plural = _("bed types")


class BedStatus(models.TextChoices):
    AVAILABLE = "available", "Available"
    OCCUPIED = "occupied", "Occupied"
    RESERVED = "reserved", "Reserved"
    MAINTENANCE = "maintenance", "Maintenance"


class Bed(MasterModel):
    """A single bed inside a ward (RULES Phase 2)."""

    ward = models.ForeignKey(
        Ward, on_delete=models.CASCADE, related_name="beds", verbose_name=_("ward")
    )
    bed_no = models.CharField(_("bed number"), max_length=30)
    bed_type = models.ForeignKey(
        BedType,
        on_delete=models.PROTECT,
        related_name="beds",
        verbose_name=_("bed type"),
    )
    daily_rate = models.DecimalField(
        _("daily rate override"),
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Leave blank to use the bed type's default daily rate."),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=BedStatus.choices,
        default=BedStatus.AVAILABLE,
    )

    class Meta(MasterModel.Meta):
        verbose_name = _("bed")
        verbose_name_plural = _("beds")
        ordering = ["ward__name", "bed_no"]
        constraints = [
            models.UniqueConstraint(fields=["ward", "bed_no"], name="uniq_bed_per_ward")
        ]

    def __str__(self) -> str:
        return f"{self.ward.name} · {self.bed_no}"
