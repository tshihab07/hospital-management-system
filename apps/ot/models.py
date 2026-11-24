"""Domain models for the Operation Theatre (OT) module (RULES Phase 9).

The module covers the surgical pathway: an :class:`OTRoom` master, a
:class:`Surgery` scheduled into a room and time slot (with row-locked conflict
detection in the service layer), the surgical team, a mandatory pre-op
checklist, anaesthesia/intra-op/post-op documentation, plus serialized
:class:`Implant` and :class:`SurgeryConsumable` capture for charging.

Every concrete model inherits :class:`~core.models.TimeStampedModel`; the
surgery is soft-deletable so clinical records are never lost (RULES §2.3.3).
Money fields are ``DecimalField(12, 2)`` (RULES §1.2.3) and clinical relations
use ``on_delete=PROTECT`` (RULES §2.3.2).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.hr.models import Staff
from apps.ipd.models import Admission
from apps.opd.models import Doctor
from apps.patients.models import Patient
from core.models import SoftDeleteModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class OTRoomStatus(models.TextChoices):
    AVAILABLE = "available", _("Available")
    OCCUPIED = "occupied", _("Occupied")
    CLEANING = "cleaning", _("Cleaning")
    MAINTENANCE = "maintenance", _("Maintenance")


class RoomType(models.TextChoices):
    MAJOR = "major", _("Major OT")
    MINOR = "minor", _("Minor OT")
    CARDIAC = "cardiac", _("Cardiac OT")
    ORTHO = "ortho", _("Orthopaedic OT")
    DAYCARE = "daycare", _("Day-care OT")


class SurgeryPriority(models.TextChoices):
    ELECTIVE = "elective", _("Elective")
    URGENT = "urgent", _("Urgent")
    EMERGENCY = "emergency", _("Emergency")


class SurgeryStatus(models.TextChoices):
    SCHEDULED = "scheduled", _("Scheduled")
    CONFIRMED = "confirmed", _("Confirmed")
    IN_PROGRESS = "in_progress", _("In progress")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")
    POSTPONED = "postponed", _("Postponed")


class AnesthesiaType(models.TextChoices):
    GENERAL = "general", _("General")
    SPINAL = "spinal", _("Spinal")
    EPIDURAL = "epidural", _("Epidural")
    REGIONAL = "regional", _("Regional block")
    LOCAL = "local", _("Local")
    SEDATION = "sedation", _("Sedation")


class PatientCondition(models.TextChoices):
    STABLE = "stable", _("Stable")
    CRITICAL = "critical", _("Critical")
    ICU = "icu", _("Shifted to ICU")
    WARD = "ward", _("Shifted to ward")


class ImplantStatus(models.TextChoices):
    IN_STOCK = "in_stock", _("In stock")
    CONSUMED = "consumed", _("Consumed")
    RETURNED = "returned", _("Returned")


class TeamRole(models.TextChoices):
    SURGEON = "surgeon", _("Surgeon")
    ASSISTANT = "assistant", _("Assistant surgeon")
    ANESTHETIST = "anesthetist", _("Anaesthetist")
    SCRUB_NURSE = "scrub_nurse", _("Scrub nurse")
    CIRCULATING = "circulating", _("Circulating nurse")
    TECHNICIAN = "technician", _("Technician")
    OTHER = "other", _("Other")


#: A surgery occupying a room blocks it while in any of these states.
ACTIVE_SURGERY_STATUSES = (
    SurgeryStatus.SCHEDULED,
    SurgeryStatus.CONFIRMED,
    SurgeryStatus.IN_PROGRESS,
)


# ---------------------------------------------------------------------------
# Room master
# ---------------------------------------------------------------------------
class OTRoom(TimeStampedModel):
    """An operating theatre with its equipment and live status."""

    name = models.CharField(_("name"), max_length=100, unique=True)
    room_no = models.CharField(_("room number"), max_length=20, blank=True)
    room_type = models.CharField(
        _("room type"), max_length=10, choices=RoomType.choices, default=RoomType.MAJOR
    )
    floor = models.CharField(_("floor"), max_length=20, blank=True)
    equipment = models.TextField(_("equipment"), blank=True)
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=OTRoomStatus.choices,
        default=OTRoomStatus.AVAILABLE,
        db_index=True,
    )
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("OT room")
        verbose_name_plural = _("OT rooms")
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name}" + (f" ({self.room_no})" if self.room_no else "")


# ---------------------------------------------------------------------------
# Surgery
# ---------------------------------------------------------------------------
class SurgerySequence(TimeStampedModel):
    """Per-year counter used to mint ``OT-YYYY-NNNNN`` surgery numbers."""

    year = models.PositiveSmallIntegerField(_("year"), unique=True)
    last_number = models.PositiveIntegerField(_("last number"), default=0)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("surgery sequence")
        verbose_name_plural = _("surgery sequences")

    def __str__(self) -> str:
        return f"{self.year} → {self.last_number}"


class Surgery(SoftDeleteModel):
    """A scheduled or performed surgical procedure."""

    surgery_no = models.CharField(
        _("surgery number"), max_length=20, unique=True, null=True, blank=True
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="surgeries",
        verbose_name=_("patient"),
    )
    surgeon = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="surgeries_performed",
        verbose_name=_("primary surgeon"),
    )
    ot_room = models.ForeignKey(
        OTRoom,
        on_delete=models.PROTECT,
        related_name="surgeries",
        verbose_name=_("OT room"),
    )
    admission = models.ForeignKey(
        Admission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surgeries",
        verbose_name=_("admission"),
    )
    scheduled_date = models.DateField(_("scheduled date"), db_index=True)
    start_time = models.TimeField(_("start time"))
    end_time = models.TimeField(_("end time"))
    procedure_name = models.CharField(_("procedure"), max_length=200)
    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=SurgeryPriority.choices,
        default=SurgeryPriority.ELECTIVE,
        db_index=True,
    )
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=SurgeryStatus.choices,
        default=SurgeryStatus.SCHEDULED,
        db_index=True,
    )
    diagnosis = models.CharField(_("diagnosis"), max_length=255, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    cancellation_reason = models.TextField(_("cancellation reason"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="surgeries_created",
        verbose_name=_("created by"),
    )
    started_at = models.DateTimeField(_("started at"), null=True, blank=True)
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("surgery")
        verbose_name_plural = _("surgeries")
        ordering = ["-scheduled_date", "start_time"]
        indexes = [
            models.Index(fields=["scheduled_date", "ot_room"]),
            models.Index(fields=["status", "scheduled_date"]),
        ]
        permissions = [
            ("schedule_surgery", _("Can schedule surgeries")),
            ("cancel_surgery", _("Can cancel surgeries")),
        ]

    def __str__(self) -> str:
        return f"{self.surgery_no or 'OT#' + str(self.pk)} · {self.procedure_name}"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_SURGERY_STATUSES

    @property
    def duration_minutes(self) -> int:
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        return max(end - start, 0)

    @property
    def is_today(self) -> bool:
        return self.scheduled_date == timezone.localdate()


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
class SurgicalTeamMember(TimeStampedModel):
    """One member of the surgical team (doctor or staff)."""

    surgery = models.ForeignKey(
        Surgery,
        on_delete=models.CASCADE,
        related_name="team",
        verbose_name=_("surgery"),
    )
    role = models.CharField(_("role"), max_length=15, choices=TeamRole.choices)
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="surgical_roles",
        verbose_name=_("doctor"),
    )
    staff = models.ForeignKey(
        Staff,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="surgical_roles",
        verbose_name=_("staff"),
    )
    name = models.CharField(_("name"), max_length=150, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("surgical team member")
        verbose_name_plural = _("surgical team members")
        ordering = ["role", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["surgery", "role", "doctor"], name="uniq_team_role_doctor"
            )
        ]

    def __str__(self) -> str:
        who = self.doctor or self.staff or self.name
        return f"{self.get_role_display()}: {who}"

    @property
    def display_name(self) -> str:
        if self.doctor:
            return self.doctor.name_en
        if self.staff:
            return self.staff.name_en
        return self.name or "—"


# ---------------------------------------------------------------------------
# Checklists / notes
# ---------------------------------------------------------------------------
class PreOpChecklist(TimeStampedModel):
    """Mandatory pre-operative checklist (must be complete before surgery)."""

    surgery = models.OneToOneField(
        Surgery,
        on_delete=models.CASCADE,
        related_name="preop_checklist",
        verbose_name=_("surgery"),
    )
    consent_signed = models.BooleanField(_("informed consent signed"), default=False)
    npo_confirmed = models.BooleanField(_("NPO / fasting confirmed"), default=False)
    site_marked = models.BooleanField(_("surgical site marked"), default=False)
    allergies_reviewed = models.BooleanField(_("allergies reviewed"), default=False)
    vitals_stable = models.BooleanField(_("vitals stable"), default=False)
    blood_arranged = models.BooleanField(_("blood / products arranged"), default=False)
    iv_access = models.BooleanField(_("IV access secured"), default=False)
    imaging_available = models.BooleanField(_("imaging available"), default=False)
    notes = models.TextField(_("notes"), blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="preop_checklists",
        verbose_name=_("verified by"),
    )
    verified_at = models.DateTimeField(_("verified at"), null=True, blank=True)

    ITEMS = (
        "consent_signed",
        "npo_confirmed",
        "site_marked",
        "allergies_reviewed",
        "vitals_stable",
        "blood_arranged",
        "iv_access",
        "imaging_available",
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("pre-op checklist")
        verbose_name_plural = _("pre-op checklists")

    def __str__(self) -> str:
        return f"Pre-op · {self.surgery}"

    @property
    def missing_items(self) -> list[str]:
        return [item for item in self.ITEMS if not getattr(self, item)]

    @property
    def is_complete(self) -> bool:
        return not self.missing_items


class AnesthesiaRecord(TimeStampedModel):
    """Anaesthesia documentation for a surgery."""

    surgery = models.OneToOneField(
        Surgery,
        on_delete=models.CASCADE,
        related_name="anesthesia",
        verbose_name=_("surgery"),
    )
    anesthesia_type = models.CharField(
        _("type"), max_length=10, choices=AnesthesiaType.choices
    )
    anesthetist = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="anesthesia_given",
        verbose_name=_("anaesthetist"),
    )
    asa_grade = models.PositiveSmallIntegerField(_("ASA grade"), null=True, blank=True)
    airway = models.CharField(_("airway"), max_length=120, blank=True)
    agents = models.CharField(_("agents"), max_length=255, blank=True)
    intubation_time = models.TimeField(_("intubation time"), null=True, blank=True)
    extubation_time = models.TimeField(_("extubation time"), null=True, blank=True)
    complications = models.TextField(_("complications"), blank=True)
    notes = models.TextField(_("notes"), blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anesthesia_records",
        verbose_name=_("recorded by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("anaesthesia record")
        verbose_name_plural = _("anaesthesia records")

    def __str__(self) -> str:
        return f"Anaesthesia · {self.surgery}"


class IntraOpNote(TimeStampedModel):
    """Intra-operative procedure note."""

    surgery = models.OneToOneField(
        Surgery,
        on_delete=models.CASCADE,
        related_name="intraop_note",
        verbose_name=_("surgery"),
    )
    findings = models.TextField(_("findings"), blank=True)
    procedure_performed = models.TextField(_("procedure performed"), blank=True)
    blood_loss_ml = models.PositiveIntegerField(
        _("blood loss (ml)"), null=True, blank=True
    )
    specimens = models.CharField(_("specimens sent"), max_length=255, blank=True)
    drains = models.CharField(_("drains"), max_length=255, blank=True)
    closure = models.CharField(_("closure"), max_length=255, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intraop_notes",
        verbose_name=_("recorded by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("intra-op note")
        verbose_name_plural = _("intra-op notes")

    def __str__(self) -> str:
        return f"Intra-op · {self.surgery}"


class PostOpNote(TimeStampedModel):
    """Post-operative recovery note."""

    surgery = models.OneToOneField(
        Surgery,
        on_delete=models.CASCADE,
        related_name="postop_note",
        verbose_name=_("surgery"),
    )
    condition = models.CharField(
        _("condition"),
        max_length=10,
        choices=PatientCondition.choices,
        default=PatientCondition.STABLE,
    )
    pain_score = models.PositiveSmallIntegerField(
        _("pain score"), null=True, blank=True
    )
    recovery_notes = models.TextField(_("recovery notes"), blank=True)
    follow_up_plan = models.TextField(_("follow-up plan"), blank=True)
    notes = models.TextField(_("notes"), blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="postop_notes",
        verbose_name=_("recorded by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("post-op note")
        verbose_name_plural = _("post-op notes")

    def __str__(self) -> str:
        return f"Post-op · {self.surgery}"


# ---------------------------------------------------------------------------
# Implants / consumables
# ---------------------------------------------------------------------------
class Implant(SoftDeleteModel):
    """A serialized implant tracked to a patient."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="implants",
        verbose_name=_("patient"),
    )
    surgery = models.ForeignKey(
        Surgery,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="implants",
        verbose_name=_("surgery"),
    )
    name = models.CharField(_("implant"), max_length=150)
    manufacturer = models.CharField(_("manufacturer"), max_length=150, blank=True)
    serial_no = models.CharField(_("serial number"), max_length=100, blank=True)
    lot_no = models.CharField(_("lot number"), max_length=100, blank=True)
    quantity = models.PositiveIntegerField(_("quantity"), default=1)
    unit_price = models.DecimalField(
        _("unit price"), max_digits=12, decimal_places=2, default=0
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=ImplantStatus.choices,
        default=ImplantStatus.CONSUMED,
        db_index=True,
    )
    consumed_at = models.DateTimeField(_("consumed at"), default=timezone.now)
    is_billed = models.BooleanField(_("billed"), default=False, db_index=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("implant")
        verbose_name_plural = _("implants")
        ordering = ["-consumed_at"]
        indexes = [models.Index(fields=["patient", "status"])]

    def __str__(self) -> str:
        return f"{self.name} · {self.patient}"

    @property
    def total(self):
        from decimal import Decimal

        return Decimal(str(self.unit_price)) * self.quantity


class SurgeryConsumable(TimeStampedModel):
    """A consumable used during a surgery (auto-billed to the patient)."""

    surgery = models.ForeignKey(
        Surgery,
        on_delete=models.CASCADE,
        related_name="consumables",
        verbose_name=_("surgery"),
    )
    item = models.CharField(_("item"), max_length=150)
    quantity = models.PositiveIntegerField(_("quantity"), default=1)
    unit_price = models.DecimalField(
        _("unit price"), max_digits=12, decimal_places=2, default=0
    )
    is_billed = models.BooleanField(_("billed"), default=False, db_index=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("surgery consumable")
        verbose_name_plural = _("surgery consumables")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.item} × {self.quantity}"

    @property
    def total(self):
        from decimal import Decimal

        return Decimal(str(self.unit_price)) * self.quantity
