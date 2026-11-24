"""Write operations for the Patient Portal (RULES Phase 15).

All mutations are atomic and audited. Portal accounts reuse the project
``User`` model (linked back to the patient via ``Patient.portal_user``) so the
existing authentication and password-validation machinery applies unchanged.

Verification codes are delivered by email when the patient has one on file.
SMS is not part of v1 (see ``docs/MISTAKES.md`` deferrals), so the phone
channel runs in **sandbox** mode: the code is logged and surfaced to the user,
mirroring the sandbox payment gateway.
"""

from __future__ import annotations

import logging
import re
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.patients import services as patient_services
from apps.patients.models import Patient
from core.audit import AuditAction, log_action, model_to_dict_safe
from core.threadlocals import get_client_ip

from .models import (
    MedicalRecordRequest,
    NotificationPreference,
    PatientPortalLog,
    PortalAction,
    PortalVerification,
    VerificationChannel,
)

logger = logging.getLogger(__name__)
User = get_user_model()

#: Maximum wrong codes before a verification is invalidated.
MAX_VERIFICATION_ATTEMPTS = 5

#: Fields a patient may change about themselves through the portal.
PROFILE_FIELDS = (
    "phone",
    "alt_phone",
    "email",
    "address",
    "permanent_address",
    "city",
    "postcode",
    "emergency_contact_name",
    "emergency_contact_relation",
    "emergency_contact_phone",
)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------
def log_portal_action(patient, action: str, *, request=None, detail: str = "") -> None:
    """Record a patient-portal activity row (ARCHITECTURE: PATIENT_PORTAL_LOG)."""
    meta = getattr(request, "META", {}) if request is not None else {}
    PatientPortalLog.objects.create(
        patient=patient,
        action=action,
        detail=detail[:255],
        path=(getattr(request, "path", "") or "")[:255],
        ip_address=get_client_ip(request),
        user_agent=(meta.get("HTTP_USER_AGENT", "") or "")[:255],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _phones_match(a: str, b: str) -> bool:
    da, db = _digits(a), _digits(b)
    if not da or not db:
        return False
    return da == db or da[-10:] == db[-10:]


def _sandbox_enabled() -> bool:
    return bool(settings.IHMS.get("PORTAL_VERIFICATION_SANDBOX", True))


def _dispatch_code(verification: PortalVerification) -> str:
    """Deliver the code; return a sandbox hint, or ``""`` when really sent."""
    if verification.channel == VerificationChannel.EMAIL and verification.destination:
        send_mail(
            subject=_("Your IHMS patient portal verification code"),
            message=_(
                "Your verification code is %(code)s. It expires in "
                "%(mins)s minutes."
            )
            % {"code": verification.code, "mins": PortalVerification.TTL_MINUTES},
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[verification.destination],
            fail_silently=True,
        )
        return ""
    # Phone channel (sandbox): no SMS provider in v1.
    logger.info(
        "Portal verification code for patient %s: %s",
        verification.patient_id,
        verification.code,
    )
    return verification.code if _sandbox_enabled() else ""


def _issue_verification(
    patient: Patient, user, request=None
) -> tuple[PortalVerification, str]:
    """Create and deliver a one-time code.

    Returns ``(verification, sandbox_code)`` where ``sandbox_code`` is the
    displayed code when no real delivery channel is configured, else ``""``.
    """
    email = (user.email or patient.email or "").strip()
    if email:
        channel, destination = VerificationChannel.EMAIL, email
    else:
        channel, destination = VerificationChannel.PHONE, patient.phone
    verification = PortalVerification.objects.create(
        patient=patient,
        user=user,
        channel=channel,
        destination=destination,
        code=f"{secrets.randbelow(1_000_000):06d}",
        expires_at=timezone.now()
        + timezone.timedelta(minutes=PortalVerification.TTL_MINUTES),
    )
    return verification, _dispatch_code(verification)


# ---------------------------------------------------------------------------
# Registration & verification
# ---------------------------------------------------------------------------
@transaction.atomic
def register_portal_account(
    *,
    uhid: str,
    phone: str,
    email: str = "",
    password: str,
    request=None,
) -> tuple[object, PortalVerification, str]:
    """Create a dormant portal account for an existing patient.

    The account starts ``is_active=False`` and is only activated once the
    one-time code is confirmed, so an unverified sign-up can never log in.
    """
    patient = (
        Patient.objects.select_for_update()
        .filter(uhid__iexact=(uhid or "").strip())
        .first()
    )
    if patient is None:
        raise ValueError(_("No patient found with that UHID."))
    if patient.portal_user_id:
        raise ValueError(_("This patient already has a portal account."))
    if not _phones_match(patient.phone, phone):
        raise ValueError(_("The phone number does not match our records."))
    if User.objects.filter(username__iexact=patient.uhid).exists():
        raise ValueError(_("A portal account already exists for this UHID."))

    user = User(
        username=patient.uhid,
        email=(email or patient.email or "").strip(),
        phone=patient.phone,
        full_name_en=patient.full_name_en,
        full_name_bn=patient.full_name_bn,
        is_active=False,
        is_staff=False,
    )
    user.set_password(password)
    user.full_clean(exclude=["password"])
    user.save()

    patient.portal_user = user
    patient.save(update_fields=["portal_user", "updated_at"])

    verification, sandbox_code = _issue_verification(patient, user, request=request)
    log_action(
        AuditAction.CREATE,
        instance=user,
        changes={"portal": True, "patient": patient.uhid},
        user=None,
        request=request,
    )
    log_portal_action(
        patient, PortalAction.REGISTER, request=request, detail=patient.uhid
    )
    return user, verification, sandbox_code


def latest_pending_verification(user) -> PortalVerification | None:
    return (
        PortalVerification.objects.filter(user=user, is_verified=False)
        .order_by("-created_at")
        .first()
    )


def verify_portal_account(
    *, verification: PortalVerification, code: str, request=None
) -> object:
    """Confirm a code and activate the portal account.

    Raises ``ValueError`` for an expired/invalid code so the view can show a
    friendly message. Failed attempts are persisted with an atomic ``UPDATE``
    *outside* any transaction that would roll them back, so brute-force
    protection actually counts wrong codes.
    """
    if verification.is_verified:
        raise ValueError(_("This account is already verified."))
    if verification.is_expired:
        raise ValueError(_("The verification code has expired. Request a new one."))
    if verification.attempts >= MAX_VERIFICATION_ATTEMPTS:
        raise ValueError(_("Too many incorrect attempts. Request a new code."))

    if (code or "").strip() != verification.code:
        PortalVerification.objects.filter(pk=verification.pk).update(
            attempts=F("attempts") + 1
        )
        raise ValueError(_("Incorrect verification code."))

    with transaction.atomic():
        verification.attempts += 1
        verification.is_verified = True
        verification.verified_at = timezone.now()
        verification.save(
            update_fields=["is_verified", "verified_at", "attempts", "updated_at"]
        )

        user = verification.user
        user.is_active = True
        user.save(update_fields=["is_active", "updated_at"])

        log_action(
            AuditAction.UPDATE,
            instance=user,
            changes={"is_active": {"to": True}, "verified": True},
            user=user,
            request=request,
        )
        log_portal_action(
            verification.patient,
            PortalAction.VERIFY,
            request=request,
            detail=user.username,
        )
    return user


@transaction.atomic
def resend_portal_verification(*, user, request=None) -> tuple[PortalVerification, str]:
    patient = getattr(user, "patient_profile", None)
    if patient is None:
        raise ValueError(_("No patient profile is linked to this account."))
    if user.is_active:
        raise ValueError(_("This account is already verified."))
    return _issue_verification(patient, user, request=request)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
@transaction.atomic
def update_portal_profile(*, patient: Patient, data: dict, actor=None, request=None):
    allowed = {k: v for k, v in data.items() if k in PROFILE_FIELDS}
    updated = patient_services.update_patient(
        instance=patient, data=allowed, actor=actor, request=request
    )
    log_portal_action(patient, PortalAction.PROFILE, request=request)
    return updated


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@transaction.atomic
def save_notification_preference(*, patient: Patient, data: dict, request=None):
    preference, _ = NotificationPreference.objects.get_or_create(patient=patient)
    for field in (
        "appointment_reminders",
        "lab_report_ready",
        "bill_due",
        "admission_updates",
        "email_enabled",
        "sms_enabled",
    ):
        if field in data:
            setattr(preference, field, bool(data[field]))
    preference.save()
    log_portal_action(patient, PortalAction.NOTIFICATIONS, request=request)
    return preference


# ---------------------------------------------------------------------------
# Medical record requests
# ---------------------------------------------------------------------------
@transaction.atomic
def create_record_request(*, patient: Patient, data: dict, actor=None, request=None):
    record = MedicalRecordRequest.objects.create(patient=patient, **data)
    log_action(
        AuditAction.CREATE,
        instance=record,
        changes=model_to_dict_safe(record),
        user=actor,
        request=request,
    )
    log_portal_action(
        patient, PortalAction.RECORD_REQUEST, request=request, detail=str(record.pk)
    )
    return record


# ---------------------------------------------------------------------------
# Appointments (delegating to the OPD service, then logging portal activity)
# ---------------------------------------------------------------------------
def book_portal_appointment(
    *,
    patient: Patient,
    doctor,
    appt_date,
    slot=None,
    visit_type: str = "new",
    actor=None,
    request=None,
):
    from apps.opd import services as opd_services

    appointment = opd_services.book_appointment(
        patient=patient,
        doctor=doctor,
        appt_date=appt_date,
        slot=slot,
        visit_type=visit_type,
        actor=actor,
        request=request,
    )
    log_portal_action(
        patient,
        PortalAction.BOOK,
        request=request,
        detail=f"{appointment.pk} · {doctor.name_en} · {appt_date}",
    )
    return appointment


def cancel_portal_appointment(*, appointment, reason: str = "", actor=None, request=None):
    from apps.opd import services as opd_services

    updated = opd_services.cancel_appointment(
        instance=appointment, reason=reason, actor=actor, request=request
    )
    log_portal_action(
        appointment.patient,
        PortalAction.CANCEL,
        request=request,
        detail=f"{appointment.pk}",
    )
    return updated


def reschedule_portal_appointment(
    *, appointment, appt_date, slot=None, actor=None, request=None
):
    from apps.opd import services as opd_services

    created = opd_services.reschedule_appointment(
        instance=appointment,
        appt_date=appt_date,
        slot=slot,
        actor=actor,
        request=request,
    )
    log_portal_action(
        appointment.patient,
        PortalAction.RESCHEDULE,
        request=request,
        detail=f"{appointment.pk} → {created.pk}",
    )
    return created


# ---------------------------------------------------------------------------
# Online payments (reuse the billing gateway so the ledger is updated)
# ---------------------------------------------------------------------------
def initiate_portal_payment(*, bill, method: str, amount, patient, actor=None, request=None):
    from apps.billing import services as billing_services

    payment = billing_services.initiate_online_payment(
        bill, method=method, amount=amount, actor=actor, request=request
    )
    log_portal_action(
        patient,
        PortalAction.PAYMENT,
        request=request,
        detail=f"{bill.bill_no} · {method} · {amount}",
    )
    return payment


def confirm_portal_payment(*, payment, success: bool, gateway_ref: str = "", actor=None, request=None):
    from apps.billing import services as billing_services

    result = billing_services.confirm_online_payment(
        payment, success=success, gateway_ref=gateway_ref, actor=actor, request=request
    )
    log_portal_action(
        payment.bill.patient,
        PortalAction.PAYMENT,
        request=request,
        detail=f"{payment.bill.bill_no} · {'success' if success else 'cancelled'}",
    )
    return result
