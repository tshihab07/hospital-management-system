"""Domain models for the IPD — Admission & Bed Management module (RULES Phase 7).

The module covers the inpatient flow: an :class:`Admission` is created from an
admission advice (bed ``None``, status ``requested``) and becomes active once a
bed is allocated. The :class:`Bed` carries a physical status plus a partial
unique constraint that **cannot double-book a bed**, and the patient may only
have one active episode at a time.

Around the admission live bed/ward transfers, daily charge accrual (bed +
nursing + doctor visit), shift-wise nursing notes, a Medication Administration
Record (MAR), intake/output charting, the discharge-clearance workflow and a
PDF-able discharge summary. IP numbers follow ``IP-YYYY-NNNNN`` via the
row-locked :class:`AdmissionSequence` counter (mirrors the UHID generator).

Every concrete model inherits :class:`~core.models.TimeStampedModel`; the
admission is soft-deletable so clinical/financial episodes are never lost
(RULES §2.3.3). Money fields are ``DecimalField(12, 2)`` (RULES §1.2.3) and
clinical/financial relations use ``on_delete=PROTECT`` (RULES §2.3.2).
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.emr.models import Route
from apps.opd.models import Doctor
from apps.patients.models import Patient
from core.models import SoftDeleteModel, TimeStampedModel

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class WardType(models.TextChoices):
    GENERAL = "general", _("General ward")
    CABIN = "cabin", _("Cabin")
    ICU = "icu", _("ICU")
    CCU = "ccu", _("CCU")
    HDU = "hdu", _("HDU")


class BedStatus(models.TextChoices):
    AVAILABLE = "available", _("Available")
    OCCUPIED = "occupied", _("Occupied")
    MAINTENANCE = "maintenance", _("Maintenance")


class AdmissionType(models.TextChoices):
    ROUTINE = "routine", _("Routine")
    EMERGENCY = "emergency", _("Emergency")


class AdmissionStatus(models.TextChoices):
    REQUESTED = "requested", _("Admission requested")
    ADMITTED = "admitted", _("Admitted")
    DISCHARGE_REQUESTED = "discharge_requested", _("Discharge requested")
    DISCHARGED = "discharged", _("Discharged")
    CANCELLED = "cancelled", _("Cancelled")


class NursingShift(models.TextChoices):
    DAY = "day", _("Day")
    NIGHT = "night", _("Night")


class MarAction(models.TextChoices):
    GIVEN = "given", _("Given")
    OMITTED = "omitted", _("Omitted")
    REFUSED = "refused", _("Refused")


class FluidType(models.TextChoices):
    INTAKE = "intake", _("Intake")
    OUTPUT = "output", _("Output")


class FluidCategory(models.TextChoices):
    # Intake
    ORAL = "oral", _("Oral")
    IV = "iv", _("IV")
    NG = "ng", _("NG tube")
    BLOOD = "blood", _("Blood product")
    # Output
    URINE = "urine", _("Urine")
    STOOL = "stool", _("Stool")
    DRAIN = "drain", _("Drain")
    VOMIT = "vomit", _("Vomit")


class ClearanceDepartment(models.TextChoices):
    LAB = "lab", _("Laboratory")
    PHARMACY = "pharmacy", _("Pharmacy")
    BILLING = "billing", _("Billing")
    INVENTORY = "inventory", _("Inventory")


class DischargeType(models.TextChoices):
    ROUTINE = "routine", _("Routine discharge")
    LAMA = "lama", _("Left against medical advice (LAMA)")
    DEATH = "death", _("Death")
    TRANSFER_OUT = "transfer_out", _("Transferred out")


# ---------------------------------------------------------------------------
# Ward & bed master data
# ---------------------------------------------------------------------------


class Ward(TimeStampedModel):
    """A nursing unit (general ward, cabin, ICU, CCU, HDU...)."""

    name = models.CharField(_("name"), max_length=100)
    ward_type = models.CharField(
        _("type"), max_length=15, choices=WardType.choices, default=WardType.GENERAL
    )
    floor = models.CharField(_("floor"), max_length=50, blank=True)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("ward")
        verbose_name_plural = _("wards")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Bed(TimeStampedModel):
    """A single bed inside a ward, with its physical status and daily rate."""

    ward = models.ForeignKey(
        Ward,
        on_delete=models.PROTECT,
        related_name="beds",
        verbose_name=_("ward"),
    )
    bed_no = models.CharField(_("bed number"), max_length=20)
    bed_type = models.CharField(
        _("bed type"), max_length=15, choices=WardType.choices, default=WardType.GENERAL
    )
    daily_rate = models.DecimalField(
        _("daily rate"), max_digits=12, decimal_places=2, default=0
    )
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=BedStatus.choices,
        default=BedStatus.AVAILABLE,
        db_index=True,
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("bed")
        verbose_name_plural = _("beds")
        ordering = ["ward__name", "bed_no"]
        constraints = [
            models.UniqueConstraint(fields=["ward", "bed_no"], name="uniq_ward_bed_no")
        ]

    def __str__(self) -> str:
        return f"{self.ward.name} · {self.bed_no}"

    @property
    def is_occupied(self) -> bool:
        return self.status == BedStatus.OCCUPIED


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------


class AdmissionSequence(TimeStampedModel):
    """Per-year monotonic counter used to mint ``IP-YYYY-NNNNN`` numbers."""

    year = models.PositiveSmallIntegerField(_("year"), unique=True)
    last_number = models.PositiveIntegerField(_("last number"), default=0)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("admission sequence")
        verbose_name_plural = _("admission sequences")

    def __str__(self) -> str:
        return f"{self.year} → {self.last_number}"


class Admission(SoftDeleteModel):
    """One inpatient episode from admission advice to discharge.

    ``bed`` is ``None`` while the admission is only *requested*; allocating a
    bed mints the ``ip_number`` and moves the episode to ``admitted``.
    """

    ip_number = models.CharField(
        _("IP number"), max_length=20, unique=True, null=True, blank=True
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
        verbose_name=_("patient"),
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="ipd_admissions",
        verbose_name=_("admitting doctor"),
    )
    encounter = models.ForeignKey(
        "emr.Encounter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admissions",
        verbose_name=_("encounter"),
    )
    admission_type = models.CharField(
        _("type"),
        max_length=15,
        choices=AdmissionType.choices,
        default=AdmissionType.ROUTINE,
    )
    reason = models.TextField(_("admission advice / reason"))
    admission_note = models.TextField(_("admission note"), blank=True)
    bed = models.ForeignKey(
        Bed,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admissions",
        verbose_name=_("current bed"),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=AdmissionStatus.choices,
        default=AdmissionStatus.REQUESTED,
        db_index=True,
    )
    admitted_at = models.DateTimeField(_("admitted at"), null=True, blank=True)
    discharged_at = models.DateTimeField(_("discharged at"), null=True, blank=True)
    discharge_reason = models.CharField(
        _("discharge reason"), max_length=255, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ipd_admissions_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("admission")
        verbose_name_plural = _("admissions")
        ordering = ["-admitted_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["bed"],
                condition=Q(bed__isnull=False)
                & ~Q(
                    status__in=[AdmissionStatus.DISCHARGED, AdmissionStatus.CANCELLED]
                ),
                name="uniq_bed_active_admission",
            ),
            models.UniqueConstraint(
                fields=["patient"],
                condition=~Q(
                    status__in=[AdmissionStatus.DISCHARGED, AdmissionStatus.CANCELLED]
                ),
                name="uniq_patient_active_admission",
            ),
        ]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["doctor", "status"]),
        ]

    def __str__(self) -> str:
        return self.ip_number or f"Adm#{self.pk}"

    @property
    def is_active_admission(self) -> bool:
        return self.status not in {
            AdmissionStatus.DISCHARGED,
            AdmissionStatus.CANCELLED,
        }

    @property
    def current_ward(self) -> Ward | None:
        return self.bed.ward if self.bed_id else None

    @property
    def length_of_stay_days(self) -> int:
        end = self.discharged_at or timezone.now()
        start = self.admitted_at or self.created_at
        return max((end.date() - start.date()).days, 0) + 1

    @property
    def has_pending_clearances(self) -> bool:
        return bool(self.pending_clearance_departments)

    @property
    def pending_clearance_departments(self) -> set[str]:
        required = {
            ClearanceDepartment.LAB,
            ClearanceDepartment.PHARMACY,
            ClearanceDepartment.BILLING,
        }
        cleared = {c.department for c in self.clearances.all() if c.is_cleared}
        return required - cleared


# ---------------------------------------------------------------------------
# Bed & ward transfers
# ---------------------------------------------------------------------------


class BedTransfer(TimeStampedModel):
    """A logged bed move (within a ward or across wards), with its snapshot."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        related_name="bed_transfers",
        verbose_name=_("admission"),
    )
    from_bed = models.ForeignKey(
        Bed,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfers_out",
        verbose_name=_("from bed"),
    )
    to_bed = models.ForeignKey(
        Bed,
        on_delete=models.PROTECT,
        related_name="transfers_in",
        verbose_name=_("to bed"),
    )
    from_ward = models.CharField(_("from ward"), max_length=100, blank=True)
    to_ward = models.CharField(_("to ward"), max_length=100, blank=True)
    reason = models.CharField(_("reason"), max_length=255, blank=True)
    transferred_at = models.DateTimeField(_("transferred at"), default=timezone.now)
    transferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ipd_bed_transfers",
        verbose_name=_("transferred by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("bed transfer")
        verbose_name_plural = _("bed transfers")
        ordering = ["-transferred_at"]

    def __str__(self) -> str:
        return f"{self.from_bed or '—'} → {self.to_bed}"


# ---------------------------------------------------------------------------
# Daily charge accrual
# ---------------------------------------------------------------------------


class ChargeStatus(models.TextChoices):
    ACCRUED = "accrued", _("Accrued")
    POSTED = "posted", _("Posted to bill")


class DailyCharge(TimeStampedModel):
    """One day of bed + nursing + doctor-visit charges for an admission."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        related_name="daily_charges",
        verbose_name=_("admission"),
    )
    charge_date = models.DateField(_("charge date"), db_index=True)
    bed_charge = models.DecimalField(
        _("bed charge"), max_digits=12, decimal_places=2, default=0
    )
    nursing_charge = models.DecimalField(
        _("nursing charge"), max_digits=12, decimal_places=2, default=0
    )
    doctor_visit_charge = models.DecimalField(
        _("doctor visit charge"), max_digits=12, decimal_places=2, default=0
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=ChargeStatus.choices,
        default=ChargeStatus.ACCRUED,
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("daily charge")
        verbose_name_plural = _("daily charges")
        ordering = ["-charge_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["admission", "charge_date"], name="uniq_daily_charge"
            )
        ]

    def __str__(self) -> str:
        return f"{self.admission} · {self.charge_date}"

    @property
    def total(self):
        """Sum of the day's charges (robust to the SQLite RETURNING quirk)."""
        values = (self.bed_charge, self.nursing_charge, self.doctor_visit_charge)
        return sum((Decimal(str(v)) for v in values), Decimal("0"))


# ---------------------------------------------------------------------------
# Nursing documentation
# ---------------------------------------------------------------------------


class NursingNote(TimeStampedModel):
    """A shift-wise nursing note charted against an admission."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        related_name="nursing_notes",
        verbose_name=_("admission"),
    )
    shift = models.CharField(
        _("shift"), max_length=5, choices=NursingShift.choices, default=NursingShift.DAY
    )
    note = models.TextField(_("note"))
    nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ipd_nursing_notes",
        verbose_name=_("nurse"),
    )
    noted_at = models.DateTimeField(_("noted at"), default=timezone.now)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("nursing note")
        verbose_name_plural = _("nursing notes")
        ordering = ["-noted_at"]

    def __str__(self) -> str:
        return f"Note #{self.pk} · {self.get_shift_display()}"

    @property
    def recorded_by(self):
        """Display name of the nurse who charted the note."""
        return self.nurse


class MedicationAdministration(TimeStampedModel):
    """A medication dose confirmed on the MAR by the administering nurse."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        related_name="medications",
        verbose_name=_("admission"),
    )
    prescription_item = models.ForeignKey(
        "emr.PrescriptionItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="administrations",
        verbose_name=_("prescription line"),
    )
    drug = models.ForeignKey(
        "masters.Drug",
        on_delete=models.PROTECT,
        related_name="administrations",
        verbose_name=_("drug"),
    )
    dose = models.CharField(_("dose"), max_length=100)
    route = models.CharField(
        _("route"), max_length=15, choices=Route.choices, default=Route.ORAL
    )
    scheduled_for = models.DateTimeField(_("scheduled for"), default=timezone.now)
    action = models.CharField(
        _("action"),
        max_length=10,
        choices=MarAction.choices,
        default=MarAction.GIVEN,
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    given_at = models.DateTimeField(_("given at"), default=timezone.now)
    given_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ipd_mar_given",
        verbose_name=_("given by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("medication administration")
        verbose_name_plural = _("medication administrations")
        ordering = ["-given_at"]

    def __str__(self) -> str:
        return f"{self.drug} · {self.dose} · {self.get_action_display()}"


class IntakeOutput(TimeStampedModel):
    """A single intake or output fluid reading for an admission."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        related_name="intake_output",
        verbose_name=_("admission"),
    )
    fluid_type = models.CharField(
        _("fluid type"), max_length=8, choices=FluidType.choices
    )
    category = models.CharField(
        _("category"), max_length=20, choices=FluidCategory.choices
    )
    volume_ml = models.PositiveIntegerField(_("volume (ml)"))
    shift = models.CharField(
        _("shift"), max_length=5, choices=NursingShift.choices, default=NursingShift.DAY
    )
    recorded_at = models.DateTimeField(_("recorded at"), default=timezone.now)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ipd_intake_output",
        verbose_name=_("recorded by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("intake / output reading")
        verbose_name_plural = _("intake / output chart")
        ordering = ["-recorded_at"]

    def __str__(self) -> str:
        return f"{self.get_fluid_type_display()} {self.volume_ml}ml"


# ---------------------------------------------------------------------------
# Discharge workflow
# ---------------------------------------------------------------------------


class DischargeClearance(TimeStampedModel):
    """A departmental no-dues/clearance record required before discharge."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        related_name="clearances",
        verbose_name=_("admission"),
    )
    department = models.CharField(
        _("department"), max_length=15, choices=ClearanceDepartment.choices
    )
    is_cleared = models.BooleanField(_("cleared"), default=False)
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ipd_clearances_issued",
        verbose_name=_("cleared by"),
    )
    cleared_at = models.DateTimeField(_("cleared at"), null=True, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("discharge clearance")
        verbose_name_plural = _("discharge clearances")
        ordering = ["department"]
        constraints = [
            models.UniqueConstraint(
                fields=["admission", "department"], name="uniq_discharge_clearance"
            )
        ]

    def __str__(self) -> str:
        return f"{self.admission} · {self.get_department_display()}"


class DischargeSummary(TimeStampedModel):
    """Final clinical summary generated at discharge (PDF-able)."""

    admission = models.OneToOneField(
        Admission,
        on_delete=models.CASCADE,
        related_name="discharge_summary",
        verbose_name=_("admission"),
    )
    discharged_at = models.DateTimeField(_("discharged at"), default=timezone.now)
    discharge_type = models.CharField(
        _("discharge type"),
        max_length=15,
        choices=DischargeType.choices,
        default=DischargeType.ROUTINE,
    )
    diagnosis_summary = models.TextField(_("diagnosis / summary"))
    treatment_given = models.TextField(_("treatment given"))
    follow_up = models.TextField(_("follow-up plan"))
    discharge_advice = models.TextField(_("discharge advice"), blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ipd_discharge_summaries",
        verbose_name=_("generated by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("discharge summary")
        verbose_name_plural = _("discharge summaries")

    def __str__(self) -> str:
        return f"Summary · {self.admission}"
