"""Domain models for the EMR & CPOE (Clinical Core) module (RULES Phase 6).

The clinical record is centred on :class:`Encounter` — one clinical visit for a
patient with a doctor. Around it live the SOAP note, visit diagnoses, vitals,
CPOE orders (prescriptions, lab/radiology/procedure) and attachments. The
problem list and allergy register are patient-level longitudinal records.

Every concrete model inherits :class:`~core.models.TimeStampedModel`; clinical
records also inherit :class:`~core.models.SoftDeleteModel` so they are never
hard-deleted (RULES §2.3.3).
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.masters.models import (Diagnosis, Drug, LabTest, Procedure,
                                 RadiologyTest)
from apps.opd.models import Appointment, Doctor
from apps.patients.models import Patient
from core.models import SoftDeleteModel, TimeStampedModel

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EncounterType(models.TextChoices):
    OUTPATIENT = "outpatient", _("Outpatient")
    FOLLOWUP = "followup", _("Follow-up")
    EMERGENCY = "emergency", _("Emergency")
    INPATIENT = "inpatient", _("Inpatient")


class EncounterStatus(models.TextChoices):
    OPEN = "open", _("Open")
    CLOSED = "closed", _("Closed")


class AllergyType(models.TextChoices):
    DRUG = "drug", _("Drug")
    FOOD = "food", _("Food")
    OTHER = "other", _("Other")


class AllergySeverity(models.TextChoices):
    MILD = "mild", _("Mild")
    MODERATE = "moderate", _("Moderate")
    SEVERE = "severe", _("Severe")
    LIFE_THREATENING = "life_threatening", _("Life-threatening")


class PrescriptionStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ISSUED = "issued", _("Issued")
    CANCELLED = "cancelled", _("Cancelled")


class Route(models.TextChoices):
    ORAL = "oral", _("Oral")
    IV = "iv", _("Intravenous")
    IM = "im", _("Intramuscular")
    SC = "sc", _("Subcutaneous")
    TOPICAL = "topical", _("Topical")
    INHALATION = "inhalation", _("Inhalation")
    RECTAL = "rectal", _("Rectal")
    OTHER = "other", _("Other")


class OrderStatus(models.TextChoices):
    ORDERED = "ordered", _("Ordered")
    IN_PROGRESS = "in_progress", _("In progress")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class OrderPriority(models.TextChoices):
    ROUTINE = "routine", _("Routine")
    URGENT = "urgent", _("Urgent")
    STAT = "stat", _("STAT")


class AttachmentCategory(models.TextChoices):
    IMAGE = "image", _("Image")
    REPORT = "report", _("Report")
    OTHER = "other", _("Other")


class InteractionSeverity(models.TextChoices):
    MINOR = "minor", _("Minor")
    MODERATE = "moderate", _("Moderate")
    MAJOR = "major", _("Major")
    CONTRAINDICATED = "contraindicated", _("Contraindicated")


# ---------------------------------------------------------------------------
# Encounter & clinical documentation
# ---------------------------------------------------------------------------
class Encounter(SoftDeleteModel):
    """One clinical visit (a consultation episode) for a patient."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="encounters",
        verbose_name=_("patient"),
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="encounters",
        verbose_name=_("doctor"),
    )
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="encounters",
        verbose_name=_("appointment"),
    )
    encounter_date = models.DateField(
        _("encounter date"), default=timezone.localdate, db_index=True
    )
    encounter_type = models.CharField(
        _("type"),
        max_length=20,
        choices=EncounterType.choices,
        default=EncounterType.OUTPATIENT,
    )
    chief_complaint = models.TextField(_("chief complaint"), blank=True)
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=EncounterStatus.choices,
        default=EncounterStatus.OPEN,
        db_index=True,
    )
    closed_at = models.DateTimeField(_("closed at"), null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emr_encounters_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("encounter")
        verbose_name_plural = _("encounters")
        ordering = ["-encounter_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["appointment"],
                condition=Q(appointment__isnull=False),
                name="uniq_encounter_per_appointment",
            )
        ]
        indexes = [
            models.Index(fields=["patient", "encounter_date"]),
            models.Index(fields=["doctor", "encounter_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient_id}@{self.encounter_date}"

    @property
    def is_open(self) -> bool:
        return self.status == EncounterStatus.OPEN


class SoapNote(TimeStampedModel):
    """Structured SOAP documentation attached one-to-one to an encounter."""

    encounter = models.OneToOneField(
        Encounter,
        on_delete=models.CASCADE,
        related_name="soap",
        verbose_name=_("encounter"),
    )
    template = models.ForeignKey(
        "SoapTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
        verbose_name=_("template"),
    )
    subjective = models.TextField(_("subjective"), blank=True)
    objective = models.TextField(_("objective"), blank=True)
    assessment = models.TextField(_("assessment"), blank=True)
    plan = models.TextField(_("plan"), blank=True)
    authored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="soap_notes_authored",
        verbose_name=_("authored by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("SOAP note")
        verbose_name_plural = _("SOAP notes")

    def __str__(self) -> str:
        return f"SOAP #{self.encounter_id}"


class SoapTemplate(TimeStampedModel):
    """A pre-built SOAP note template for fast, consistent documentation."""

    name = models.CharField(_("name"), max_length=150, unique=True)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    chief_complaint = models.TextField(_("chief complaint"), blank=True)
    subjective = models.TextField(_("subjective"), blank=True)
    objective = models.TextField(_("objective"), blank=True)
    assessment = models.TextField(_("assessment"), blank=True)
    plan = models.TextField(_("plan"), blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("SOAP template")
        verbose_name_plural = _("SOAP templates")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class VisitDiagnosis(TimeStampedModel):
    """A diagnosis recorded against a single encounter."""

    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="diagnoses",
        verbose_name=_("encounter"),
    )
    diagnosis = models.ForeignKey(
        Diagnosis,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visit_diagnoses",
        verbose_name=_("coded diagnosis"),
    )
    description = models.CharField(_("description"), max_length=255, blank=True)
    is_primary = models.BooleanField(_("primary"), default=False)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("visit diagnosis")
        verbose_name_plural = _("visit diagnoses")
        ordering = ["-is_primary", "id"]

    def __str__(self) -> str:
        return self.description or (self.diagnosis.name if self.diagnosis else "")

    def clean(self) -> None:
        if not self.description and not self.diagnosis_id:
            raise ValidationError(_("Provide a coded diagnosis or a description."))


class Vital(TimeStampedModel):
    """A vitals measurement recorded during an encounter."""

    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="vitals",
        verbose_name=_("encounter"),
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="vitals",
        verbose_name=_("patient"),
    )
    recorded_at = models.DateTimeField(_("recorded at"), default=timezone.now)
    temperature_c = models.DecimalField(
        _("temperature (°C)"), max_digits=4, decimal_places=1, null=True, blank=True
    )
    pulse = models.PositiveSmallIntegerField(_("pulse (bpm)"), null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(
        _("respiratory rate"), null=True, blank=True
    )
    bp_systolic = models.PositiveSmallIntegerField(
        _("BP systolic"), null=True, blank=True
    )
    bp_diastolic = models.PositiveSmallIntegerField(
        _("BP diastolic"), null=True, blank=True
    )
    spo2 = models.PositiveSmallIntegerField(_("SpO₂ (%)"), null=True, blank=True)
    height_cm = models.DecimalField(
        _("height (cm)"), max_digits=5, decimal_places=2, null=True, blank=True
    )
    weight_kg = models.DecimalField(
        _("weight (kg)"), max_digits=5, decimal_places=2, null=True, blank=True
    )
    pain_score = models.PositiveSmallIntegerField(
        _("pain score (0-10)"), null=True, blank=True
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vitals_recorded",
        verbose_name=_("recorded by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("vital sign")
        verbose_name_plural = _("vital signs")
        ordering = ["-recorded_at", "-id"]
        indexes = [models.Index(fields=["patient", "-recorded_at"])]

    def __str__(self) -> str:
        return f"Vitals #{self.pk} ({self.patient_id})"

    @property
    def bmi(self):
        """Body-mass index derived from height/weight, or ``None``."""
        if not self.height_cm or not self.weight_kg:
            return None
        height_m = float(self.height_cm) / 100
        if height_m <= 0:
            return None
        return round(float(self.weight_kg) / (height_m**2), 1)

    @property
    def bp_display(self) -> str:
        if self.bp_systolic and self.bp_diastolic:
            return f"{self.bp_systolic}/{self.bp_diastolic}"
        return "—"


# ---------------------------------------------------------------------------
# Longitudinal patient records: problem list & allergy register
# ---------------------------------------------------------------------------
class ProblemListEntry(TimeStampedModel):
    """A patient-level problem (chronic condition) tracked across visits."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="problems",
        verbose_name=_("patient"),
    )
    diagnosis = models.ForeignKey(
        Diagnosis,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="problems",
        verbose_name=_("coded diagnosis"),
    )
    description = models.CharField(_("problem"), max_length=255)
    onset_date = models.DateField(_("onset date"), null=True, blank=True)
    resolved_date = models.DateField(_("resolved date"), null=True, blank=True)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("problem list entry")
        verbose_name_plural = _("problem list")
        ordering = ["-is_active", "-onset_date", "id"]

    def __str__(self) -> str:
        return self.description

    @property
    def is_resolved(self) -> bool:
        return not self.is_active


class Allergy(TimeStampedModel):
    """An entry in a patient's allergy register (drug, food or other)."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="allergies",
        verbose_name=_("patient"),
    )
    allergen = models.CharField(_("allergen"), max_length=150)
    allergy_type = models.CharField(
        _("type"),
        max_length=10,
        choices=AllergyType.choices,
        default=AllergyType.DRUG,
    )
    reaction = models.CharField(_("reaction"), max_length=255, blank=True)
    severity = models.CharField(
        _("severity"),
        max_length=20,
        choices=AllergySeverity.choices,
        default=AllergySeverity.MODERATE,
    )
    noted_on = models.DateField(_("noted on"), null=True, blank=True)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("allergy")
        verbose_name_plural = _("allergies")
        ordering = ["allergen"]

    def __str__(self) -> str:
        return self.allergen


# ---------------------------------------------------------------------------
# CPOE: prescriptions
# ---------------------------------------------------------------------------
class Prescription(SoftDeleteModel):
    """A prescription (set of drug orders) issued during an encounter."""

    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="prescriptions",
        verbose_name=_("encounter"),
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="prescriptions",
        verbose_name=_("patient"),
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="prescriptions",
        verbose_name=_("doctor"),
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=PrescriptionStatus.choices,
        default=PrescriptionStatus.ISSUED,
        db_index=True,
    )
    issued_at = models.DateTimeField(_("issued at"), default=timezone.now)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescriptions_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("prescription")
        verbose_name_plural = _("prescriptions")
        ordering = ["-issued_at", "-id"]
        indexes = [models.Index(fields=["patient", "-issued_at"])]

    def __str__(self) -> str:
        return f"Rx #{self.pk} ({self.patient_id})"

    @property
    def is_issued(self) -> bool:
        return self.status == PrescriptionStatus.ISSUED


class PrescriptionItem(TimeStampedModel):
    """A single drug line on a prescription."""

    prescription = models.ForeignKey(
        Prescription,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("prescription"),
    )
    drug = models.ForeignKey(
        Drug,
        on_delete=models.PROTECT,
        related_name="prescription_items",
        verbose_name=_("drug"),
    )
    dose = models.CharField(_("dose"), max_length=100)
    route = models.CharField(
        _("route"), max_length=15, choices=Route.choices, default=Route.ORAL
    )
    frequency = models.CharField(_("frequency"), max_length=100)
    duration_days = models.PositiveSmallIntegerField(_("duration (days)"), default=1)
    quantity = models.PositiveSmallIntegerField(_("quantity"), default=1)
    is_prn = models.BooleanField(_("PRN"), default=False)
    instructions = models.CharField(_("instructions"), max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("prescription item")
        verbose_name_plural = _("prescription items")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.drug} — {self.dose}"


# ---------------------------------------------------------------------------
# CPOE: diagnostic & procedure orders
# ---------------------------------------------------------------------------
class LabOrder(SoftDeleteModel):
    """A laboratory order placed during an encounter."""

    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="lab_orders",
        verbose_name=_("encounter"),
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="lab_orders",
        verbose_name=_("patient"),
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="lab_orders",
        verbose_name=_("doctor"),
    )
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=OrderStatus.choices,
        default=OrderStatus.ORDERED,
        db_index=True,
    )
    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=OrderPriority.choices,
        default=OrderPriority.ROUTINE,
    )
    ordered_at = models.DateTimeField(_("ordered at"), default=timezone.now)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lab_orders_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("lab order")
        verbose_name_plural = _("lab orders")
        ordering = ["-ordered_at", "-id"]

    def __str__(self) -> str:
        return f"Lab #{self.pk}"

    @property
    def is_pending(self) -> bool:
        return self.status in {OrderStatus.ORDERED, OrderStatus.IN_PROGRESS}


class LabOrderItem(TimeStampedModel):
    order = models.ForeignKey(
        LabOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("order"),
    )
    test = models.ForeignKey(
        LabTest,
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name=_("test"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("lab order item")
        verbose_name_plural = _("lab order items")
        ordering = ["id"]

    def __str__(self) -> str:
        return str(self.test)


class RadiologyOrder(SoftDeleteModel):
    """A radiology/imaging order placed during an encounter."""

    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="radiology_orders",
        verbose_name=_("encounter"),
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="radiology_orders",
        verbose_name=_("patient"),
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="radiology_orders",
        verbose_name=_("doctor"),
    )
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=OrderStatus.choices,
        default=OrderStatus.ORDERED,
        db_index=True,
    )
    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=OrderPriority.choices,
        default=OrderPriority.ROUTINE,
    )
    clinical_indication = models.TextField(_("clinical indication"), blank=True)
    ordered_at = models.DateTimeField(_("ordered at"), default=timezone.now)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="radiology_orders_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("radiology order")
        verbose_name_plural = _("radiology orders")
        ordering = ["-ordered_at", "-id"]

    def __str__(self) -> str:
        return f"Radiology #{self.pk}"

    @property
    def is_pending(self) -> bool:
        return self.status in {OrderStatus.ORDERED, OrderStatus.IN_PROGRESS}


class RadiologyOrderItem(TimeStampedModel):
    order = models.ForeignKey(
        RadiologyOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("order"),
    )
    test = models.ForeignKey(
        RadiologyTest,
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name=_("test"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("radiology order item")
        verbose_name_plural = _("radiology order items")
        ordering = ["id"]

    def __str__(self) -> str:
        return str(self.test)


class ProcedureOrder(SoftDeleteModel):
    """A procedure order placed during an encounter."""

    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="procedure_orders",
        verbose_name=_("encounter"),
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="procedure_orders",
        verbose_name=_("patient"),
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="procedure_orders",
        verbose_name=_("doctor"),
    )
    procedure = models.ForeignKey(
        Procedure,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name=_("procedure"),
    )
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=OrderStatus.choices,
        default=OrderStatus.ORDERED,
        db_index=True,
    )
    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=OrderPriority.choices,
        default=OrderPriority.ROUTINE,
    )
    scheduled_for = models.DateField(_("scheduled for"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    ordered_at = models.DateTimeField(_("ordered at"), default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="procedure_orders_created",
        verbose_name=_("created by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("procedure order")
        verbose_name_plural = _("procedure orders")
        ordering = ["-ordered_at", "-id"]

    def __str__(self) -> str:
        return f"Procedure #{self.pk}"

    @property
    def is_pending(self) -> bool:
        return self.status in {OrderStatus.ORDERED, OrderStatus.IN_PROGRESS}


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
class ClinicalAttachment(SoftDeleteModel):
    """An uploaded clinical file (image, external report, etc.)."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="clinical_attachments",
        verbose_name=_("patient"),
    )
    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name=_("encounter"),
    )
    title = models.CharField(_("title"), max_length=200)
    category = models.CharField(
        _("category"),
        max_length=10,
        choices=AttachmentCategory.choices,
        default=AttachmentCategory.IMAGE,
    )
    file = models.FileField(_("file"), upload_to="clinical/")
    description = models.TextField(_("description"), blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinical_attachments_uploaded",
        verbose_name=_("uploaded by"),
    )

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("clinical attachment")
        verbose_name_plural = _("clinical attachments")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


# ---------------------------------------------------------------------------
# Drug-interaction rules engine
# ---------------------------------------------------------------------------
class DrugInteractionRule(TimeStampedModel):
    """A basic pairwise drug-interaction rule used by the CPOE rules engine."""

    drug_a = models.ForeignKey(
        Drug,
        on_delete=models.CASCADE,
        related_name="interactions_as_a",
        verbose_name=_("drug A"),
    )
    drug_b = models.ForeignKey(
        Drug,
        on_delete=models.CASCADE,
        related_name="interactions_as_b",
        verbose_name=_("drug B"),
    )
    severity = models.CharField(
        _("severity"),
        max_length=20,
        choices=InteractionSeverity.choices,
        default=InteractionSeverity.MODERATE,
    )
    description = models.TextField(_("description"), blank=True)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("drug interaction rule")
        verbose_name_plural = _("drug interaction rules")
        ordering = ["drug_a__generic_name", "drug_b__generic_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["drug_a", "drug_b"], name="uniq_drug_interaction_pair"
            )
        ]

    def __str__(self) -> str:
        return f"{self.drug_a} ⨯ {self.drug_b}"

    def clean(self) -> None:
        if self.drug_a_id and self.drug_a_id == self.drug_b_id:
            raise ValidationError(_("A drug cannot interact with itself."))

    def matches(self, drug_ids: set[int]) -> bool:
        """Return ``True`` when both drugs are present in ``drug_ids``."""
        return {self.drug_a_id, self.drug_b_id} <= drug_ids
