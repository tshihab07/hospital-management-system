"""Service-level tests for the Patient Portal (RULES Phase 15)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from .. import services
from ..models import (
    MedicalRecordRequestStatus,
    NotificationPreference,
    PatientPortalLog,
    PortalAction,
    VerificationChannel,
)
from . import factories

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_register_creates_dormant_account_and_verification():
    patient = factories.make_patient()
    user, verification, _ = services.register_portal_account(
        uhid=patient.uhid,
        phone=patient.phone,
        email=patient.email,
        password="PortalPass123",
    )
    assert user.is_active is False
    assert user.username == patient.uhid
    patient.refresh_from_db()
    assert patient.portal_user_id == user.pk
    assert verification.is_verified is False
    assert verification.channel == VerificationChannel.EMAIL
    assert PatientPortalLog.objects.filter(
        patient=patient, action=PortalAction.REGISTER
    ).exists()


def test_register_rejects_wrong_phone():
    patient = factories.make_patient()
    with pytest.raises(ValueError):
        services.register_portal_account(
            uhid=patient.uhid,
            phone="01711111111",
            email="",
            password="PortalPass123",
        )


def test_register_rejects_unknown_uhid():
    with pytest.raises(ValueError):
        services.register_portal_account(
            uhid="NOPE-0001", phone="01700000000", email="", password="PortalPass123"
        )


def test_register_rejects_second_account():
    patient, _ = factories.make_portal_user()
    with pytest.raises(ValueError):
        services.register_portal_account(
            uhid=patient.uhid,
            phone=patient.phone,
            email="",
            password="PortalPass123",
        )


def test_register_falls_back_to_phone_channel_without_email():
    patient = factories.make_patient(email="")
    _user, verification, _ = services.register_portal_account(
        uhid=patient.uhid, phone=patient.phone, email="", password="PortalPass123"
    )
    assert verification.channel == VerificationChannel.PHONE


def test_verify_activates_account():
    patient = factories.make_patient()
    user, verification, _ = services.register_portal_account(
        uhid=patient.uhid,
        phone=patient.phone,
        email=patient.email,
        password="PortalPass123",
    )
    activated = services.verify_portal_account(
        verification=verification, code=verification.code
    )
    assert activated.pk == user.pk
    user.refresh_from_db()
    assert user.is_active is True
    assert PatientPortalLog.objects.filter(
        patient=patient, action=PortalAction.VERIFY
    ).exists()


def test_verify_rejects_wrong_code():
    patient = factories.make_patient()
    _user, verification, _ = services.register_portal_account(
        uhid=patient.uhid,
        phone=patient.phone,
        email=patient.email,
        password="PortalPass123",
    )
    with pytest.raises(ValueError):
        services.verify_portal_account(verification=verification, code="000000")
    verification.refresh_from_db()
    assert verification.attempts == 1
    assert verification.is_verified is False


def test_verify_rejects_expired_code():
    patient = factories.make_patient()
    _user, verification, _ = services.register_portal_account(
        uhid=patient.uhid,
        phone=patient.phone,
        email=patient.email,
        password="PortalPass123",
    )
    verification.expires_at = timezone.now() - timezone.timedelta(minutes=1)
    verification.save(update_fields=["expires_at"])
    with pytest.raises(ValueError):
        services.verify_portal_account(verification=verification, code=verification.code)


def test_update_profile_only_touches_contact_fields():
    patient, user = factories.make_portal_user()
    services.update_portal_profile(
        patient=patient,
        data={"phone": "01799999999", "full_name_en": "Hacked", "city": "Dhaka"},
        actor=user,
    )
    patient.refresh_from_db()
    assert patient.phone == "01799999999"
    assert patient.city == "Dhaka"
    assert patient.full_name_en != "Hacked"
    assert PatientPortalLog.objects.filter(
        patient=patient, action=PortalAction.PROFILE
    ).exists()


def test_notification_preferences_round_trip():
    patient, _ = factories.make_portal_user()
    services.save_notification_preference(
        patient=patient, data={"sms_enabled": True, "bill_due": False}
    )
    pref = NotificationPreference.objects.get(patient=patient)
    assert pref.sms_enabled is True
    assert pref.bill_due is False


def test_create_record_request_is_logged():
    patient, user = factories.make_portal_user()
    record = services.create_record_request(
        patient=patient,
        data={"purpose": "Insurance claim"},
        actor=user,
    )
    assert record.status == MedicalRecordRequestStatus.PENDING
    assert PatientPortalLog.objects.filter(
        patient=patient, action=PortalAction.RECORD_REQUEST
    ).exists()
