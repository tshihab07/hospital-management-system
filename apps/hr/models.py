"""Doctor & Staff Management models (RULES Phase 5).

Covers staff full profiles, shift templates, weekly duty rosters, attendance
(manual + biometric), and the leave apply/approve workflow with balances.
Payroll itself is deferred to Phase 14; only the salary *structure* lives here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class EmploymentType(models.TextChoices):
    PERMANENT = "permanent", _("Permanent")
    CONTRACT = "contract", _("Contract")
    PROBATION = "probation", _("Probation")
    PART_TIME = "part_time", _("Part-time")
    INTERN = "intern", _("Intern")


class StaffStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    ON_LEAVE = "on_leave", _("On Leave")
    RESIGNED = "resigned", _("Resigned")
    TERMINATED = "terminated", _("Terminated")


class Shift(TimeStampedModel):
    """A reusable shift template (Morning/Evening/Night/General)."""

    name = models.CharField(_("name"), max_length=50, unique=True)
    code = models.CharField(_("code"), max_length=20, unique=True)
    start_time = models.TimeField(_("start time"))
    end_time = models.TimeField(_("end time"))
    is_night = models.BooleanField(
        _("night shift"),
        default=False,
        help_text=_("Tick when the shift crosses midnight."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("shift")
        verbose_name_plural = _("shifts")
        ordering = ["start_time"]

    def __str__(self) -> str:
        return f"{self.name} ({self.start_time:%H:%M}–{self.end_time:%H:%M})"

    def clean(self) -> None:
        if self.start_time and self.end_time and self.start_time == self.end_time:
            raise ValidationError(_("Start and end time cannot be equal."))


class Staff(TimeStampedModel):
    """A non-doctor employee (nurses, technicians, admin, support)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff_profile",
        verbose_name=_("user"),
    )
    employee_code = models.CharField(_("employee code"), max_length=30, unique=True)
    name_en = models.CharField(_("name (English)"), max_length=200)
    name_bn = models.CharField(_("name (Bengali)"), max_length=200, blank=True)
    department = models.ForeignKey(
        "masters.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff",
        verbose_name=_("department"),
    )
    designation = models.ForeignKey(
        "masters.Designation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff",
        verbose_name=_("designation"),
    )
    phone = models.CharField(_("phone"), max_length=20, blank=True)
    email = models.EmailField(_("email"), blank=True)
    joining_date = models.DateField(_("joining date"), null=True, blank=True)
    employment_type = models.CharField(
        _("employment type"),
        max_length=20,
        choices=EmploymentType.choices,
        default=EmploymentType.PERMANENT,
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=StaffStatus.choices,
        default=StaffStatus.ACTIVE,
        db_index=True,
    )
    shift = models.ForeignKey(
        Shift,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff",
        verbose_name=_("default shift"),
    )

    # Salary structure (gross is computed; payroll runs are Phase 14).
    basic_salary = models.DecimalField(
        _("basic salary"), max_digits=12, decimal_places=2, default=0
    )
    house_rent = models.DecimalField(
        _("house rent"), max_digits=12, decimal_places=2, default=0
    )
    medical_allowance = models.DecimalField(
        _("medical allowance"), max_digits=12, decimal_places=2, default=0
    )
    transport_allowance = models.DecimalField(
        _("transport allowance"), max_digits=12, decimal_places=2, default=0
    )
    other_allowance = models.DecimalField(
        _("other allowance"), max_digits=12, decimal_places=2, default=0
    )
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("active"), default=True, db_index=True)

    class Meta:
        verbose_name = _("staff")
        verbose_name_plural = _("staff")
        ordering = ["name_en"]
        indexes = [models.Index(fields=["employee_code", "status"])]

    def __str__(self) -> str:
        return f"{self.name_en} ({self.employee_code})"

    @property
    def display_name(self) -> str:
        return self.name_en or self.name_bn or self.employee_code

    @property
    def gross_salary(self) -> Decimal:
        return (
            self.basic_salary
            + self.house_rent
            + self.medical_allowance
            + self.transport_allowance
            + self.other_allowance
        )


class DutyRoster(TimeStampedModel):
    """One staff member's assigned shift on a given date."""

    staff = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name="roster",
        verbose_name=_("staff"),
    )
    shift = models.ForeignKey(
        Shift,
        on_delete=models.PROTECT,
        related_name="roster",
        verbose_name=_("shift"),
    )
    duty_date = models.DateField(_("duty date"), db_index=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    is_published = models.BooleanField(_("published"), default=False, db_index=True)
    published_at = models.DateTimeField(_("published at"), null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rosters_published",
        verbose_name=_("published by"),
    )

    class Meta:
        verbose_name = _("duty roster")
        verbose_name_plural = _("duty rosters")
        ordering = ["duty_date", "staff__name_en"]
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "duty_date"], name="uniq_roster_per_day"
            )
        ]

    def __str__(self) -> str:
        return f"{self.staff} · {self.duty_date} · {self.shift}"


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", _("Present")
    ABSENT = "absent", _("Absent")
    LATE = "late", _("Late")
    HALF_DAY = "half_day", _("Half Day")
    LEAVE = "leave", _("On Leave")
    HOLIDAY = "holiday", _("Holiday")
    WEEKEND = "weekend", _("Weekend")


class AttendanceSource(models.TextChoices):
    MANUAL = "manual", _("Manual")
    BIOMETRIC = "biometric", _("Biometric")


class Attendance(TimeStampedModel):
    """Daily attendance record (manual or imported from a biometric device)."""

    staff = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name="attendance",
        verbose_name=_("staff"),
    )
    att_date = models.DateField(_("date"), db_index=True)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT,
    )
    check_in = models.TimeField(_("check-in"), null=True, blank=True)
    check_out = models.TimeField(_("check-out"), null=True, blank=True)
    source = models.CharField(
        _("source"),
        max_length=20,
        choices=AttendanceSource.choices,
        default=AttendanceSource.MANUAL,
    )
    device_id = models.CharField(_("device id"), max_length=60, blank=True)
    remarks = models.CharField(_("remarks"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("attendance")
        verbose_name_plural = _("attendance")
        ordering = ["-att_date", "staff__name_en"]
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "att_date"], name="uniq_attendance_per_day"
            )
        ]

    def __str__(self) -> str:
        return f"{self.staff} · {self.att_date} · {self.get_status_display()}"

    @property
    def worked_hours(self) -> Decimal | None:
        """Hours between check-in and check-out (handles overnight shifts)."""
        if not self.check_in or not self.check_out:
            return None
        start = datetime.combine(self.att_date, self.check_in)
        end = datetime.combine(self.att_date, self.check_out)
        if end < start:
            end += timedelta(days=1)
        return (Decimal((end - start).total_seconds()) / Decimal(3600)).quantize(
            Decimal("0.01")
        )


class LeaveType(TimeStampedModel):
    """A category of leave (Casual, Sick, Earned, ...)."""

    name = models.CharField(_("name"), max_length=60, unique=True)
    code = models.CharField(_("code"), max_length=20, unique=True)
    max_days_per_year = models.PositiveSmallIntegerField(
        _("max days per year"), default=0
    )
    is_paid = models.BooleanField(_("paid"), default=True)
    requires_document = models.BooleanField(_("requires document"), default=False)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("leave type")
        verbose_name_plural = _("leave types")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LeaveStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    CANCELLED = "cancelled", _("Cancelled")


class LeaveRequest(TimeStampedModel):
    """A staff leave application with an approval workflow."""

    staff = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name="leave_requests",
        verbose_name=_("staff"),
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.PROTECT,
        related_name="requests",
        verbose_name=_("leave type"),
    )
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    days = models.PositiveSmallIntegerField(_("days"), default=1)
    reason = models.TextField(_("reason"), blank=True)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=LeaveStatus.choices,
        default=LeaveStatus.PENDING,
        db_index=True,
    )
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leave_applied",
        verbose_name=_("applied by"),
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leave_decided",
        verbose_name=_("decided by"),
    )
    decided_at = models.DateTimeField(_("decided at"), null=True, blank=True)
    decision_note = models.CharField(_("decision note"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("leave request")
        verbose_name_plural = _("leave requests")
        ordering = ["-start_date", "-id"]
        indexes = [models.Index(fields=["staff", "status"])]

    def __str__(self) -> str:
        return f"{self.staff} · {self.leave_type} · {self.start_date}–{self.end_date}"

    @property
    def is_pending(self) -> bool:
        return self.status == LeaveStatus.PENDING

    def clean(self) -> None:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(_("End date cannot be before the start date."))

    def save(self, *args, **kwargs):
        if self.start_date and self.end_date:
            self.days = (self.end_date - self.start_date).days + 1
        super().save(*args, **kwargs)


class LeaveBalance(TimeStampedModel):
    """Per-staff, per-type, per-year leave entitlement and usage."""

    staff = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name="leave_balances",
        verbose_name=_("staff"),
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name="balances",
        verbose_name=_("leave type"),
    )
    year = models.PositiveSmallIntegerField(_("year"))
    entitled_days = models.PositiveSmallIntegerField(_("entitled days"), default=0)
    used_days = models.PositiveSmallIntegerField(_("used days"), default=0)

    class Meta:
        verbose_name = _("leave balance")
        verbose_name_plural = _("leave balances")
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "leave_type", "year"], name="uniq_balance_per_year"
            )
        ]

    def __str__(self) -> str:
        return f"{self.staff} · {self.leave_type} · {self.year}"

    @property
    def remaining_days(self) -> int:
        return max(0, self.entitled_days - self.used_days)
