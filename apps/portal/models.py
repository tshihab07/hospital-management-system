"""Patient Portal models (RULES Phase 15).

The portal is a thin, self-service layer over the clinical and financial
modules. It deliberately reuses :class:`apps.patients.models.Patient` and the
project ``User`` model (RULES anti-pattern: *"Building portal auth before RBAC
| Duplicated auth logic"*). Only portal-specific state lives here:

* :class:`PatientPortalLog` — append-only access log (ARCHITECTURE table
  ``PATIENT_PORTAL_LOG``) for compliance/audit.
* :class:`NotificationPreference` — patient-controlled notification channels.
* :class:`MedicalRecordRequest` — a patient-initiated request for records.
* :class:`PortalVerification` — one-time code verifying ownership of an
  email/phone before a portal account is activated.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.patients.models import Patient
from core.models import TimeStampedModel


# ---------------------------------------------------------------------------
# Access log
# ---------------------------------------------------------------------------
class PortalAction(models.TextChoices):
    LOGIN = "login", _("Login")
    LOGIN_FAILED = "login_failed", _("Login failed")
    LOGOUT = "logout", _("Logout")
    REGISTER = "register", _("Register")
    VERIFY = "verify", _("Verify account")
    VIEW = "view", _("View record")
    DOWNLOAD = "download", _("Download report")
    BOOK = "book", _("Book appointment")
    CANCEL = "cancel", _("Cancel appointment")
    RESCHEDULE = "reschedule", _("Reschedule appointment")
    PAYMENT = "payment", _("Payment")
    PROFILE = "profile", _("Update profile")
    RECORD_REQUEST = "record_request", _("Request medical records")
    NOTIFICATIONS = "notifications", _("Update notification preferences")


class PatientPortalLog(models.Model):
    """One row per meaningful patient-portal activity (append-only)."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="portal_logs",
        verbose_name=_("patient"),
    )
    action = models.CharField(
        _("action"), max_length=32, choices=PortalAction.choices, db_index=True
    )
    detail = models.CharField(_("detail"), max_length=255, blank=True)
    path = models.CharField(_("path"), max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.CharField(_("user agent"), max_length=255, blank=True)
    timestamp = models.DateTimeField(_("timestamp"), default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = _("patient portal log")
        verbose_name_plural = _("patient portal logs")
        indexes = [models.Index(fields=["patient", "-timestamp"])]

    def __str__(self) -> str:
        return f"{self.patient_id} · {self.action}"


# ---------------------------------------------------------------------------
# Notification preferences
# ---------------------------------------------------------------------------
class NotificationPreference(TimeStampedModel):
    """Patient-selected notification topics and delivery channels."""

    patient = models.OneToOneField(
        Patient,
        on_delete=models.CASCADE,
        related_name="notification_preference",
        verbose_name=_("patient"),
    )
    appointment_reminders = models.BooleanField(
        _("appointment reminders"), default=True
    )
    lab_report_ready = models.BooleanField(_("lab report ready"), default=True)
    bill_due = models.BooleanField(_("bill due"), default=True)
    admission_updates = models.BooleanField(_("admission & discharge"), default=True)
    email_enabled = models.BooleanField(_("email"), default=True)
    sms_enabled = models.BooleanField(_("SMS"), default=False)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("notification preference")
        verbose_name_plural = _("notification preferences")

    def __str__(self) -> str:
        return f"Notifications · {self.patient_id}"


# ---------------------------------------------------------------------------
# Medical record requests
# ---------------------------------------------------------------------------
class MedicalRecordRequestStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    PROCESSING = "processing", _("Processing")
    COMPLETED = "completed", _("Completed")
    REJECTED = "rejected", _("Rejected")


class MedicalRecordRequest(TimeStampedModel):
    """A patient's request for a copy of their medical records."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="record_requests",
        verbose_name=_("patient"),
    )
    purpose = models.TextField(_("purpose"))
    records_from = models.DateField(_("records from"), null=True, blank=True)
    records_to = models.DateField(_("records to"), null=True, blank=True)
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=MedicalRecordRequestStatus.choices,
        default=MedicalRecordRequestStatus.PENDING,
        db_index=True,
    )
    response_notes = models.TextField(_("response notes"), blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="portal_record_requests_handled",
        verbose_name=_("handled by"),
    )
    handled_at = models.DateTimeField(_("handled at"), null=True, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("medical record request")
        verbose_name_plural = _("medical record requests")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Records · {self.patient_id} · {self.get_status_display()}"


# ---------------------------------------------------------------------------
# Account verification
# ---------------------------------------------------------------------------
class VerificationChannel(models.TextChoices):
    EMAIL = "email", _("Email")
    PHONE = "phone", _("Phone")


class PortalVerification(TimeStampedModel):
    """A one-time verification code for a freshly-created portal account."""

    TTL_MINUTES = 15

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="portal_verifications",
        verbose_name=_("patient"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portal_verifications",
        verbose_name=_("account"),
    )
    channel = models.CharField(
        _("channel"),
        max_length=10,
        choices=VerificationChannel.choices,
        default=VerificationChannel.EMAIL,
    )
    destination = models.CharField(_("destination"), max_length=200, blank=True)
    code = models.CharField(_("code"), max_length=6)
    attempts = models.PositiveSmallIntegerField(_("attempts"), default=0)
    is_verified = models.BooleanField(_("verified"), default=False, db_index=True)
    verified_at = models.DateTimeField(_("verified at"), null=True, blank=True)
    expires_at = models.DateTimeField(_("expires at"), null=True, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = _("portal verification")
        verbose_name_plural = _("portal verifications")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Verification · {self.user_id}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and timezone.now() >= self.expires_at
