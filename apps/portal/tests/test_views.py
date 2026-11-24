"""View / isolation tests for the Patient Portal (RULES Phase 15)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.billing import services as billing_services
from apps.billing.models import BillStatus
from apps.emr.models import LabOrder
from apps.lab.models import LabReport
from apps.opd.models import Appointment, AppointmentStatus, AvailabilitySlot, Doctor

from .. import services
from ..models import (
    MedicalRecordRequest,
    NotificationPreference,
    PatientPortalLog,
    PortalAction,
)
from . import factories

pytestmark = pytest.mark.django_db


def _next_weekday(weekday: int = 0) -> dt.date:
    today = dt.date.today()
    return today + dt.timedelta(days=(weekday - today.weekday()) % 7 or 7)


def _doctor(**overrides) -> Doctor:
    data = {
        "name_en": "Dr. Portal",
        "specialization": "Medicine",
        "consultation_fee": "500.00",
        "followup_fee": "250.00",
    }
    data.update(overrides)
    return Doctor.objects.create(**data)


def _slot(doctor, *, weekday=0):
    return AvailabilitySlot.objects.create(
        doctor=doctor,
        weekday=weekday,
        start_time=dt.time(9, 0),
        end_time=dt.time(13, 0),
        max_patients=10,
    )


def _charged_bill(patient, amount="1000.00"):
    bill = billing_services.create_bill(patient)
    billing_services.post_charge(
        bill,
        item_type="consultation",
        description="Consultation",
        quantity=1,
        unit_price=amount,
        tax_rate="0",
    )
    billing_services.issue_bill(bill)
    return bill


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def test_dashboard_requires_login(client):
    response = client.get(reverse("portal:dashboard"))
    assert response.status_code == 302
    assert reverse("portal:login") in response.url


def test_staff_user_without_patient_is_denied(client):
    staff = factories.make_staff_user()
    client.force_login(staff)
    response = client.get(reverse("portal:dashboard"))
    assert response.status_code == 403


def test_dashboard_ok_for_patient(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    response = client.get(reverse("portal:dashboard"))
    assert response.status_code == 200
    assert patient.uhid.encode() in response.content


# ---------------------------------------------------------------------------
# Registration / verification flow
# ---------------------------------------------------------------------------
def test_register_and_verify_flow(client):
    patient = factories.make_patient()
    response = client.post(
        reverse("portal:register"),
        {
            "uhid": patient.uhid,
            "phone": patient.phone,
            "email": patient.email,
            "password1": "PortalPass123",
            "password2": "PortalPass123",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("portal:verify")

    client.get(reverse("portal:login"))  # ensure no breakage
    response = client.post(reverse("portal:verify"), {"code": "000000"})
    assert response.status_code == 200  # wrong code re-renders

    patient.refresh_from_db()
    verification = services.latest_pending_verification(patient.portal_user)
    response = client.post(reverse("portal:verify"), {"code": verification.code})
    assert response.status_code == 302
    assert response.url == reverse("portal:login")

    patient.portal_user.refresh_from_db()
    assert patient.portal_user.is_active is True

    # The account can now sign in through the portal login form.
    response = client.post(
        reverse("portal:login"),
        {"username": patient.uhid, "password": "PortalPass123"},
    )
    assert response.status_code == 302
    assert response.url == reverse("portal:dashboard")


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
def test_booking_creates_appointment_and_log(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    doctor = _doctor()
    monday = _next_weekday(0)
    slot = _slot(doctor, weekday=monday.weekday())
    response = client.post(
        reverse("portal:appointment_book"),
        {
            "doctor": doctor.pk,
            "appt_date": monday.isoformat(),
            "slot": slot.pk,
            "visit_type": "new",
        },
    )
    assert response.status_code == 302
    appointment = Appointment.objects.get(patient=patient)
    assert appointment.doctor_id == doctor.pk
    assert PatientPortalLog.objects.filter(
        patient=patient, action=PortalAction.BOOK
    ).exists()


def test_cancel_appointment(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    doctor = _doctor()
    monday = _next_weekday(0)
    appointment = services.book_portal_appointment(
        patient=patient, doctor=doctor, appt_date=monday, slot=None, actor=user
    )
    response = client.post(
        reverse("portal:appointment_cancel", args=[appointment.pk]),
        {"reason": "Unwell"},
    )
    assert response.status_code == 302
    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.CANCELLED


def test_reschedule_appointment(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    doctor = _doctor()
    monday = _next_weekday(0)
    tuesday = monday + dt.timedelta(days=1)
    slot = _slot(doctor, weekday=tuesday.weekday())
    appointment = services.book_portal_appointment(
        patient=patient, doctor=doctor, appt_date=monday, slot=None, actor=user
    )
    response = client.post(
        reverse("portal:appointment_reschedule", args=[appointment.pk]),
        {"appt_date": tuesday.isoformat(), "slot": slot.pk, "visit_type": "new"},
    )
    assert response.status_code == 302
    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.CANCELLED
    assert Appointment.objects.filter(
        patient=patient, appt_date=tuesday, status=AppointmentStatus.SCHEDULED
    ).exists()


def test_cannot_cancel_another_patients_appointment(client):
    patient_a, user_a = factories.make_portal_user()
    patient_b, _ = factories.make_portal_user()
    client.force_login(user_a)
    doctor = _doctor()
    appointment = services.book_portal_appointment(
        patient=patient_b, doctor=doctor, appt_date=_next_weekday(0), slot=None
    )
    response = client.post(
        reverse("portal:appointment_cancel", args=[appointment.pk])
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Lab reports
# ---------------------------------------------------------------------------
def _released_report(patient, *, released=True):
    doctor = _doctor()
    from apps.emr.models import Encounter, EncounterType

    encounter = Encounter.objects.create(
        patient=patient, doctor=doctor, encounter_type=EncounterType.OUTPATIENT
    )
    order = LabOrder.objects.create(encounter=encounter, patient=patient, doctor=doctor)
    return LabReport.objects.create(
        order=order, report_no=f"RPT-{order.pk}", is_released=released
    )


def test_lab_report_pdf_available_when_released(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    report = _released_report(patient)
    response = client.get(reverse("portal:lab_report_pdf", args=[report.pk]))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert PatientPortalLog.objects.filter(
        patient=patient, action=PortalAction.DOWNLOAD
    ).exists()


def test_unreleased_lab_report_is_denied(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    report = _released_report(patient, released=False)
    response = client.get(reverse("portal:lab_report_pdf", args=[report.pk]))
    assert response.status_code == 403


def test_cannot_download_another_patients_report(client):
    patient_a, user_a = factories.make_portal_user()
    patient_b, _ = factories.make_portal_user()
    client.force_login(user_a)
    report = _released_report(patient_b)
    response = client.get(reverse("portal:lab_report_pdf", args=[report.pk]))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Bills & payment
# ---------------------------------------------------------------------------
def test_bill_list_and_detail(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    bill = _charged_bill(patient)
    assert (
        client.get(reverse("portal:bills")).status_code == 200
    )
    response = client.get(reverse("portal:bill_detail", args=[bill.pk]))
    assert response.status_code == 200
    assert bill.bill_no.encode() in response.content


def test_cannot_view_another_patients_bill(client):
    patient_a, user_a = factories.make_portal_user()
    patient_b, _ = factories.make_portal_user()
    client.force_login(user_a)
    bill = _charged_bill(patient_b)
    response = client.get(reverse("portal:bill_detail", args=[bill.pk]))
    assert response.status_code == 403


def test_online_payment_updates_ledger(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    bill = _charged_bill(patient, amount="700.00")
    response = client.post(
        reverse("portal:bill_pay", args=[bill.pk]),
        {"method": "bkash", "amount": "700.00"},
    )
    assert response.status_code == 302
    # Follow to the sandbox confirmation page and pay.
    confirm_url = response.url
    assert client.get(confirm_url).status_code == 200
    response = client.post(confirm_url, {"result": "success"})
    assert response.status_code == 302
    bill.refresh_from_db()
    assert bill.status == BillStatus.PAID
    assert bill.paid_amount == Decimal("700.00")
    assert PatientPortalLog.objects.filter(
        patient=patient, action=PortalAction.PAYMENT
    ).exists()


# ---------------------------------------------------------------------------
# Profile / notifications / records
# ---------------------------------------------------------------------------
def test_profile_update(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    response = client.post(
        reverse("portal:profile"),
        {
            "phone": "01712345678",
            "alt_phone": "",
            "email": "new@example.com",
            "address": "12 Road",
            "permanent_address": "",
            "city": "Dhaka",
            "postcode": "1200",
            "emergency_contact_name": "",
            "emergency_contact_relation": "",
            "emergency_contact_phone": "",
        },
    )
    assert response.status_code == 302
    patient.refresh_from_db()
    assert patient.phone == "01712345678"
    assert patient.city == "Dhaka"


def test_notification_preferences_saved(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    response = client.post(
        reverse("portal:notifications"),
        {
            "appointment_reminders": "on",
            "email_enabled": "on",
            "sms_enabled": "on",
        },
    )
    assert response.status_code == 302
    pref = NotificationPreference.objects.get(patient=patient)
    assert pref.sms_enabled is True
    assert pref.bill_due is False


def test_record_request_created(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    response = client.post(
        reverse("portal:record_requests"),
        {"purpose": "Insurance", "records_from": "", "records_to": ""},
    )
    assert response.status_code == 302
    assert MedicalRecordRequest.objects.filter(patient=patient).count() == 1


# ---------------------------------------------------------------------------
# Language toggle (RULES Phase 15 exit criterion)
# ---------------------------------------------------------------------------
def test_language_toggle_switches_to_bengali(client):
    patient, user = factories.make_portal_user()
    client.force_login(user)
    response = client.post(
        reverse("set_language"), {"language": "bn", "next": reverse("portal:dashboard")}
    )
    assert response.status_code == 302
    response = client.get(reverse("portal:dashboard"))
    assert response.status_code == 200
    assert response.wsgi_request.LANGUAGE_CODE == "bn"
