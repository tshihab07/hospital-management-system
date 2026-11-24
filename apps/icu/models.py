"""ICU / CCU & Emergency data model (Phase 8).

Two related domains live here, matching the single ``icu`` app referenced by the
navigation and the ARCHITECTURE "ICU / CCU / Emergency" module:

* **Critical care** — hourly :class:`IcuRecord` charting (vitals, ventilator,
  intake/output), :class:`CriticalAlert` escalation for critical values,
  :class:`CriticalScore` (APACHE II / SOFA) and shift :class:`HandoverNote`.
* **Emergency** — :class:`EmergencyCase` casualty registration with triage,
  an ER queue board, and :class:`CodeBlueAlert` broadcast/resolution.

Clinical/financial records are never hard-deleted; emergency cases subclass
:class:`SoftDeleteModel` and links to admissions/patients use ``PROTECT``.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.ipd.models import Admission
from apps.opd.models import Doctor
from apps.patients.models import Patient
from core.models import SoftDeleteModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class VentilatorMode(models.TextChoices):
    NONE = "", _("None")
    ROOM_AIR = "room_air", _("Room air")
    HFNO = "hfno", _("HFNO")
    CPAP = "cpap", _("CPAP")
    PSV = "psv", _("PSV")
    SIMV = "simv", _("SIMV")
    AC = "ac", _("Assist-control")


class TriageLevel(models.TextChoices):
    RED = "red", _("Red — Immediate")
    ORANGE = "orange", _("Orange — Very urgent")
    YELLOW = "yellow", _("Yellow — Urgent")
    GREEN = "green", _("Green — Standard")
    BLUE = "blue", _("Blue — Non-urgent")


class EmergencyStatus(models.TextChoices):
    WAITING = "waiting", _("Waiting")
    IN_TREATMENT = "in_treatment", _("In treatment")
    ADMITTED = "admitted", _("Admitted")
    DISCHARGED = "discharged", _("Discharged")
    LEFT = "left", _("Left without being seen")
    DECEASED = "deceased", _("Deceased")


class CodeBlueStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    RESOLVED = "resolved", _("Resolved")


class ScoreType(models.TextChoices):
    APACHE_II = "apache_ii", _("APACHE II")
    SOFA = "sofa", _("SOFA")


class AlertStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    ACKNOWLEDGED = "acknowledged", _("Acknowledged")
    RESOLVED = "resolved", _("Resolved")


class AlertSeverity(models.TextChoices):
    HIGH = "high", _("High")
    MEDIUM = "medium", _("Medium")


class Unit(models.TextChoices):
    ICU = "icu", _("ICU / CCU")
    ER = "er", _("Emergency")


class UnitShift(models.TextChoices):
    DAY = "day", _("Day")
    NIGHT = "night", _("Night")


# Clinical thresholds used for critical-value detection. Kept as module
# constants so the rules are auditable and easy to tune per hospital policy.
CRITICAL_RULES: dict[str, tuple] = {
    "spo2": ("lt", 90, AlertSeverity.HIGH),
    "pulse": ("out", (50, 130), AlertSeverity.HIGH),
    "bp_systolic": ("out", (90, 180), AlertSeverity.HIGH),
    "bp_diastolic": ("out", (50, 110), AlertSeverity.MEDIUM),
    "temperature": ("out", (Decimal("35.0"), Decimal("39.5")), AlertSeverity.MEDIUM),
    "respiratory_rate": ("out", (8, 30), AlertSeverity.HIGH),
    "gcs": ("lt", 9, AlertSeverity.HIGH),
}


# ---------------------------------------------------------------------------
# Critical care charting
# ---------------------------------------------------------------------------
class IcuRecord(TimeStampedModel):
    """One ICU charting entry (typically hourly): vitals + ventilator + I/O."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        related_name="icu_records",
        verbose_name=_("admission"),
    )
    recorded_at = models.DateTimeField(
        _("recorded at"), default=timezone.now, db_index=True
    )

    temperature = models.DecimalField(
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
    gcs = models.PositiveSmallIntegerField(_("GCS"), null=True, blank=True)

    ventilator_mode = models.CharField(
        _("ventilator mode"),
        max_length=10,
        choices=VentilatorMode.choices,
        blank=True,
    )
    fio2 = models.DecimalField(
        _("FiO₂ (%)"), max_digits=4, decimal_places=1, null=True, blank=True
    )
    peep = models.PositiveSmallIntegerField(_("PEEP"), null=True, blank=True)
    tidal_volume = models.PositiveIntegerField(
        _("tidal volume (ml)"), null=True, blank=True
    )
    set_rate = models.PositiveSmallIntegerField(_("set rate"), null=True, blank=True)

    intake_ml = models.PositiveIntegerField(_("intake (ml)"), null=True, blank=True)
    output_ml = models.PositiveIntegerField(_("output (ml)"), null=True, blank=True)

    notes = models.TextField(_("notes"), blank=True)
    charted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="icu_records_charted",
        verbose_name=_("charted by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("ICU record")
        verbose_name_plural = _("ICU records")
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["admission", "recorded_at"])]

    def __str__(self) -> str:
        return f"{self.admission} @ {self.recorded_at:%d %b %H:%M}"

    @property
    def bp_display(self) -> str:
        if self.bp_systolic is None and self.bp_diastolic is None:
            return "—"
        return f"{self.bp_systolic or '—'}/{self.bp_diastolic or '—'}"

    @property
    def map_estimate(self) -> int | None:
        """Mean arterial pressure estimate from systolic/diastolic."""
        if self.bp_systolic is None or self.bp_diastolic is None:
            return None
        return round((self.bp_systolic + 2 * self.bp_diastolic) / 3)

    @property
    def fluid_balance(self) -> int:
        return (self.intake_ml or 0) - (self.output_ml or 0)

    @property
    def is_ventilated(self) -> bool:
        return bool(self.ventilator_mode)

    @property
    def critical_findings(self) -> list[dict]:
        """Return every clocked parameter that breaches a critical threshold."""
        findings: list[dict] = []
        for param, rule in CRITICAL_RULES.items():
            value = getattr(self, param)
            if value is None:
                continue
            kind, bound, severity = rule
            breached = False
            if kind == "lt":
                breached = value < bound
            elif kind == "out":
                low, high = bound
                breached = value < low or value > high
            if breached:
                findings.append(
                    {"parameter": param, "value": value, "severity": severity}
                )
        return findings


class CriticalAlert(TimeStampedModel):
    """An alert raised when an ICU chart clocks a critical value."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        related_name="critical_alerts",
        verbose_name=_("admission"),
    )
    icu_record = models.ForeignKey(
        IcuRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts",
        verbose_name=_("ICU record"),
    )
    parameter = models.CharField(_("parameter"), max_length=30)
    value = models.CharField(_("value"), max_length=30)
    severity = models.CharField(
        _("severity"), max_length=10, choices=AlertSeverity.choices
    )
    message = models.CharField(_("message"), max_length=255)
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=AlertStatus.choices,
        default=AlertStatus.ACTIVE,
    )
    notified_to = models.CharField(_("notified to"), max_length=255, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="icu_alerts_acknowledged",
        verbose_name=_("acknowledged by"),
    )
    acknowledged_at = models.DateTimeField(_("acknowledged at"), null=True, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("critical alert")
        verbose_name_plural = _("critical alerts")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "severity"])]

    def __str__(self) -> str:
        return f"{self.parameter}={self.value} ({self.get_severity_display()})"


class CriticalScore(TimeStampedModel):
    """A calculated ICU severity score (APACHE II / SOFA)."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.PROTECT,
        related_name="critical_scores",
        verbose_name=_("admission"),
    )
    score_type = models.CharField(
        _("score type"), max_length=10, choices=ScoreType.choices
    )
    score_value = models.PositiveSmallIntegerField(_("score value"))
    breakdown = models.JSONField(_("breakdown"), default=dict, blank=True)
    calculated_at = models.DateTimeField(_("calculated at"), default=timezone.now)
    calculated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="icu_scores_calculated",
        verbose_name=_("calculated by"),
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("critical score")
        verbose_name_plural = _("critical scores")
        ordering = ["-calculated_at"]

    def __str__(self) -> str:
        return f"{self.get_score_type_display()} = {self.score_value}"


class HandoverNote(TimeStampedModel):
    """A shift handover note for the ICU or ER."""

    unit = models.CharField(_("unit"), max_length=5, choices=Unit.choices)
    shift = models.CharField(_("shift"), max_length=5, choices=UnitShift.choices)
    handover_date = models.DateField(_("handover date"), default=timezone.localdate)
    admission = models.ForeignKey(
        Admission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handovers",
        verbose_name=_("admission"),
    )
    emergency_case = models.ForeignKey(
        "EmergencyCase",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handovers",
        verbose_name=_("emergency case"),
    )
    summary = models.TextField(_("summary"))
    pending_tasks = models.TextField(_("pending tasks"), blank=True)
    handed_over_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="icu_handovers_given",
        verbose_name=_("handed over by"),
    )
    handover_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="icu_handovers_received",
        verbose_name=_("handover to"),
    )
    acknowledged = models.BooleanField(_("acknowledged"), default=False)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("handover note")
        verbose_name_plural = _("handover notes")
        ordering = ["-handover_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.get_unit_display()} · {self.get_shift_display()} · {self.handover_date}"


# ---------------------------------------------------------------------------
# Emergency department
# ---------------------------------------------------------------------------
class EmergencySequence(TimeStampedModel):
    """Per-year counter used to mint ``ER-YYYY-NNNNN`` case numbers."""

    year = models.PositiveSmallIntegerField(_("year"), unique=True)
    last_number = models.PositiveIntegerField(_("last number"), default=0)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("emergency sequence")
        verbose_name_plural = _("emergency sequences")

    def __str__(self) -> str:
        return f"{self.year} → {self.last_number}"


class EmergencyCase(SoftDeleteModel):
    """An emergency/casualty case from arrival through triage and disposition."""

    TRIAGE_RANK = {
        TriageLevel.RED: 0,
        TriageLevel.ORANGE: 1,
        TriageLevel.YELLOW: 2,
        TriageLevel.GREEN: 3,
        TriageLevel.BLUE: 4,
    }

    case_no = models.CharField(
        _("case number"), max_length=20, unique=True, null=True, blank=True
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="emergency_cases",
        verbose_name=_("patient"),
    )
    arrival_time = models.DateTimeField(
        _("arrival time"), default=timezone.now, db_index=True
    )
    complaint = models.TextField(_("complaint"))
    triage_level = models.CharField(
        _("triage level"),
        max_length=10,
        choices=TriageLevel.choices,
        default=TriageLevel.YELLOW,
        db_index=True,
    )
    status = models.CharField(
        _("status"),
        max_length=15,
        choices=EmergencyStatus.choices,
        default=EmergencyStatus.WAITING,
        db_index=True,
    )
    attending_doctor = models.ForeignKey(
        Doctor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emergency_cases",
        verbose_name=_("attending doctor"),
    )

    # Initial triage vitals -------------------------------------------------
    temperature = models.DecimalField(
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

    notes = models.TextField(_("notes"), blank=True)
    converted_admission = models.ForeignKey(
        Admission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emergency_case",
        verbose_name=_("converted admission"),
    )
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emergency_cases_registered",
        verbose_name=_("registered by"),
    )
    discharged_at = models.DateTimeField(_("discharged at"), null=True, blank=True)

    class Meta(SoftDeleteModel.Meta):
        verbose_name = _("emergency case")
        verbose_name_plural = _("emergency cases")
        ordering = ["-arrival_time"]
        indexes = [
            models.Index(fields=["status", "arrival_time"]),
            models.Index(fields=["triage_level", "arrival_time"]),
        ]

    def __str__(self) -> str:
        return f"{self.case_no or 'ER#' + str(self.pk)} · {self.patient}"

    @property
    def triage_rank(self) -> int:
        return self.TRIAGE_RANK.get(self.triage_level, 9)

    @property
    def is_open(self) -> bool:
        return self.status in {EmergencyStatus.WAITING, EmergencyStatus.IN_TREATMENT}

    @property
    def wait_minutes(self) -> int:
        end = self.discharged_at or timezone.now()
        return max(int((end - self.arrival_time).total_seconds() // 60), 0)


class CodeBlueAlert(TimeStampedModel):
    """A Code Blue broadcast raised to on-duty staff."""

    location = models.CharField(_("location"), max_length=120)
    admission = models.ForeignKey(
        Admission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="code_blues",
        verbose_name=_("admission"),
    )
    emergency_case = models.ForeignKey(
        EmergencyCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="code_blues",
        verbose_name=_("emergency case"),
    )
    called_at = models.DateTimeField(_("called at"), default=timezone.now)
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=CodeBlueStatus.choices,
        default=CodeBlueStatus.ACTIVE,
    )
    called_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="code_blues_called",
        verbose_name=_("called by"),
    )
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="code_blues_resolved",
        verbose_name=_("resolved by"),
    )
    notified_count = models.PositiveSmallIntegerField(_("notified count"), default=0)
    notes = models.TextField(_("notes"), blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("code blue alert")
        verbose_name_plural = _("code blue alerts")
        ordering = ["-called_at"]
        indexes = [models.Index(fields=["status", "called_at"])]
        permissions = [("resolve_codebluealert", _("Can resolve Code Blue alerts"))]

    def __str__(self) -> str:
        return f"Code Blue · {self.location} · {self.get_status_display()}"
