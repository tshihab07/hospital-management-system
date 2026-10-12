"""OPD & Appointments models (RULES Phase 4).

Doctors offer :class:`AvailabilitySlot` time blocks; appointments are booked
against a block and receive an automatic per-day token via a row-locked
:class:`DoctorDailyToken` counter.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class Weekday(models.IntegerChoices):
    MONDAY = 0, _("Monday")
    TUESDAY = 1, _("Tuesday")
    WEDNESDAY = 2, _("Wednesday")
    THURSDAY = 3, _("Thursday")
    FRIDAY = 4, _("Friday")
    SATURDAY = 5, _("Saturday")
    SUNDAY = 6, _("Sunday")


class Doctor(TimeStampedModel):
    """Basic doctor master (full HR profile arrives in Phase 5)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="doctor_profile",
        verbose_name=_("user"),
    )
    department = models.ForeignKey(
        "masters.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="doctors",
        verbose_name=_("department"),
    )
    name_en = models.CharField(_("name (English)"), max_length=200)
    name_bn = models.CharField(_("name (Bengali)"), max_length=200, blank=True)
    phone = models.CharField(_("phone"), max_length=20, blank=True)
    email = models.EmailField(_("email"), blank=True)
    qualification = models.CharField(_("qualification"), max_length=200, blank=True)
    specialization = models.CharField(_("specialization"), max_length=200, blank=True)
    bmdc_no = models.CharField(
        _("BMDC number"), max_length=50, blank=True, null=True, unique=True
    )
    employee_code = models.CharField(
        _("employee code"), max_length=30, blank=True, null=True, unique=True
    )
    joining_date = models.DateField(_("joining date"), null=True, blank=True)
    signature = models.ImageField(
        _("digital signature"), upload_to="doctors/signatures/", blank=True, null=True
    )
    consultation_fee = models.DecimalField(
        _("consultation fee"), max_digits=12, decimal_places=2, default=0
    )
    followup_fee = models.DecimalField(
        _("follow-up fee"), max_digits=12, decimal_places=2, default=0
    )
    revenue_share_pct = models.DecimalField(
        _("revenue share (%)"), max_digits=5, decimal_places=2, default=0
    )
    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("doctor")
        verbose_name_plural = _("doctors")
        ordering = ["name_en"]

    def __str__(self) -> str:
        return self.name_en

    @property
    def display_name(self) -> str:
        parts = [self.name_en, self.specialization]
        return ", ".join(p for p in parts if p)


class AvailabilitySlot(TimeStampedModel):
    """A reusable weekly time block a doctor accepts patients in."""

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="availability",
        verbose_name=_("doctor"),
    )
    weekday = models.PositiveSmallIntegerField(_("weekday"), choices=Weekday.choices)
    start_time = models.TimeField(_("start time"))
    end_time = models.TimeField(_("end time"))
    max_patients = models.PositiveSmallIntegerField(
        _("max patients per block"), default=10
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("availability slot")
        verbose_name_plural = _("availability slots")
        ordering = ["weekday", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "weekday", "start_time"], name="uniq_slot_per_day"
            )
        ]

    def __str__(self) -> str:
        return f"{self.doctor} {self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}"

    def clean(self) -> None:
        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise ValidationError(_("End time must be after start time."))

    @property
    def label(self) -> str:
        return f"{self.start_time:%H:%M} – {self.end_time:%H:%M}"


class AppointmentStatus(models.TextChoices):
    SCHEDULED = "scheduled", _("Scheduled")
    ARRIVED = "arrived", _("Arrived")
    IN_CONSULTATION = "in_consultation", _("In Consultation")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")
    NO_SHOW = "no_show", _("No Show")


class AppointmentType(models.TextChoices):
    NEW = "new", _("New Patient")
    FOLLOWUP = "followup", _("Follow-up")


class Appointment(TimeStampedModel):
    """A booked consultation."""

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name=_("doctor"),
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="appointments",
        verbose_name=_("patient"),
    )
    slot = models.ForeignKey(
        AvailabilitySlot,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appointments",
        verbose_name=_("time block"),
    )
    appt_date = models.DateField(_("appointment date"), db_index=True)
    slot_time = models.TimeField(_("slot time"), null=True, blank=True)
    token_no = models.PositiveIntegerField(
        _("token number"), db_index=True, help_text=_("Per doctor, per day.")
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.SCHEDULED,
        db_index=True,
    )
    visit_type = models.CharField(
        _("visit type"),
        max_length=10,
        choices=AppointmentType.choices,
        default=AppointmentType.NEW,
    )
    consultation_fee = models.DecimalField(
        _("consultation fee"), max_digits=12, decimal_places=2, default=0
    )
    notes = models.CharField(_("notes"), max_length=255, blank=True)

    # lifecycle -----------------------------------------------------------
    arrived_at = models.DateTimeField(_("arrived at"), null=True, blank=True)
    started_at = models.DateTimeField(
        _("consultation started at"), null=True, blank=True
    )
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)
    cancelled_at = models.DateTimeField(_("cancelled at"), null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appointments_cancelled",
        verbose_name=_("cancelled by"),
    )
    cancel_reason = models.CharField(
        _("cancellation reason"), max_length=255, blank=True
    )
    rescheduled_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rescheduled_to",
        verbose_name=_("rescheduled from"),
    )

    # reminders -----------------------------------------------------------
    reminder_24h_sent = models.BooleanField(_("24h reminder sent"), default=False)
    reminder_1h_sent = models.BooleanField(_("1h reminder sent"), default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appointments_created",
        verbose_name=_("created by"),
    )

    class Meta:
        verbose_name = _("appointment")
        verbose_name_plural = _("appointments")
        ordering = ["appt_date", "doctor", "token_no"]
        indexes = [
            models.Index(fields=["appt_date", "doctor", "status"]),
            models.Index(fields=["patient", "appt_date"]),
        ]

    def __str__(self) -> str:
        return (
            f"#{self.token_no} {self.doctor} · {self.appt_date:%d/%m/%Y} "
            f"({self.patient.uhid})"
        )

    @property
    def is_active(self) -> bool:
        return self.status not in {
            AppointmentStatus.CANCELLED,
            AppointmentStatus.NO_SHOW,
        }

    @property
    def for_today(self) -> bool:
        return self.appt_date == timezone.localdate()


class DoctorDailyToken(TimeStampedModel):
    """Row-locked per-day token counter for a doctor (like UHID)."""

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="daily_tokens",
        verbose_name=_("doctor"),
    )
    token_date = models.DateField(_("date"), db_index=True)
    last_token = models.PositiveIntegerField(_("last token"), default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "token_date"], name="uniq_token_per_day"
            )
        ]
        verbose_name = _("doctor daily token")
        verbose_name_plural = _("doctor daily tokens")

    def __str__(self) -> str:  # pragma: no cover - admin nicety
        return f"{self.doctor} {self.token_date} #{self.last_token}"
