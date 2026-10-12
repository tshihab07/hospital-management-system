"""Service-layer tests: token allocation, booking, lifecycle and reminders."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.opd import services
from apps.opd.models import (AppointmentStatus, AppointmentType,
                             AvailabilitySlot, Doctor, DoctorDailyToken)
from apps.patients.models import Patient
from core.audit import AuditAction, AuditLog

pytestmark = pytest.mark.django_db


def _next_weekday(weekday: int = 0) -> dt.date:
    """Return the next strictly-future date falling on ``weekday`` (0=Mon)."""
    today = dt.date.today()
    return today + dt.timedelta(days=(weekday - today.weekday()) % 7 or 7)


def _doctor(**overrides) -> Doctor:
    data = {
        "name_en": "Dr. Test",
        "specialization": "Medicine",
        "consultation_fee": "500.00",
        "followup_fee": "250.00",
    }
    data.update(overrides)
    return Doctor.objects.create(**data)


def _slot(doctor, *, weekday=0, start=dt.time(9, 0), end=dt.time(13, 0), cap=10):
    return AvailabilitySlot.objects.create(
        doctor=doctor,
        weekday=weekday,
        start_time=start,
        end_time=end,
        max_patients=cap,
    )


def _patient(**overrides) -> Patient:
    from apps.patients import services as patient_services

    data = {
        "full_name_en": "Test Patient",
        "gender": "male",
        "date_of_birth": dt.date(1990, 1, 1),
        "phone": "01700000000",
        "email": "patient@example.com",
    }
    data.update(overrides)
    return patient_services.register_patient(data=data)


def test_booking_allocates_incrementing_tokens_per_doctor_day():
    doctor = _doctor()
    monday = _next_weekday(0)
    slot = _slot(doctor, weekday=monday.weekday())
    p1, p2 = _patient(), _patient(phone="01700000002")

    first = services.book_appointment(
        patient=p1, doctor=doctor, appt_date=monday, slot=slot
    )
    second = services.book_appointment(
        patient=p2, doctor=doctor, appt_date=monday, slot=slot
    )

    assert (first.token_no, second.token_no) == (1, 2)
    assert AuditLog.objects.filter(
        action=AuditAction.CREATE, object_id=str(first.pk)
    ).exists()


def test_tokens_are_isolated_per_doctor_and_day():
    doctor_a, doctor_b = _doctor(), _doctor(name_en="Dr. Other", bmdc_no="X-9")
    monday = _next_weekday(0)
    tuesday = monday + dt.timedelta(days=1)
    slot_a = _slot(doctor_a, weekday=monday.weekday())
    slot_b = _slot(doctor_b, weekday=monday.weekday())
    slot_a_tue = _slot(doctor_a, weekday=tuesday.weekday())

    a1 = services.book_appointment(
        patient=_patient(), doctor=doctor_a, appt_date=monday, slot=slot_a
    )
    b1 = services.book_appointment(
        patient=_patient(phone="01700000003"),
        doctor=doctor_b,
        appt_date=monday,
        slot=slot_b,
    )
    a2 = services.book_appointment(
        patient=_patient(phone="01700000004"),
        doctor=doctor_a,
        appt_date=tuesday,
        slot=slot_a_tue,
    )

    assert a1.token_no == 1
    assert b1.token_no == 1
    assert a2.token_no == 1


def test_capacity_is_enforced():
    doctor = _doctor()
    monday = _next_weekday(0)
    slot = _slot(doctor, weekday=monday.weekday(), cap=1)
    services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=monday, slot=slot
    )
    with pytest.raises(ValueError):
        services.book_appointment(
            patient=_patient(phone="01700000009"),
            doctor=doctor,
            appt_date=monday,
            slot=slot,
        )


def test_duplicate_active_booking_is_rejected():
    doctor = _doctor()
    monday = _next_weekday(0)
    slot = _slot(doctor, weekday=monday.weekday())
    patient = _patient()
    services.book_appointment(
        patient=patient, doctor=doctor, appt_date=monday, slot=slot
    )
    with pytest.raises(ValueError):
        services.book_appointment(
            patient=patient, doctor=doctor, appt_date=monday, slot=slot
        )


def test_booking_in_the_past_is_rejected():
    doctor = _doctor()
    past = dt.date(2020, 1, 1)
    slot = _slot(doctor, weekday=past.weekday())
    with pytest.raises(ValueError):
        services.book_appointment(
            patient=_patient(), doctor=doctor, appt_date=past, slot=slot
        )


def test_followup_uses_followup_fee_and_sets_slot_time():
    doctor = _doctor()
    monday = _next_weekday(0)
    slot = _slot(doctor, weekday=monday.weekday())
    appt = services.book_appointment(
        patient=_patient(),
        doctor=doctor,
        appt_date=monday,
        slot=slot,
        visit_type=AppointmentType.FOLLOWUP,
    )
    doctor.refresh_from_db()
    assert appt.consultation_fee == doctor.followup_fee
    assert appt.slot_time == slot.start_time


def test_cancel_and_status_transitions():
    doctor = _doctor()
    monday = _next_weekday(0)
    slot = _slot(doctor, weekday=monday.weekday())
    appt = services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=monday, slot=slot
    )

    services.set_status(instance=appt, status=AppointmentStatus.ARRIVED)
    services.set_status(instance=appt, status=AppointmentStatus.IN_CONSULTATION)
    services.set_status(instance=appt, status=AppointmentStatus.COMPLETED)
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.COMPLETED
    assert appt.completed_at is not None

    with pytest.raises(ValueError):
        services.set_status(instance=appt, status=AppointmentStatus.ARRIVED)


def test_cancel_records_reason_and_audit():
    doctor = _doctor()
    monday = _next_weekday(0)
    slot = _slot(doctor, weekday=monday.weekday())
    appt = services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=monday, slot=slot
    )
    services.cancel_appointment(instance=appt, reason="Patient request")
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CANCELLED
    assert appt.cancel_reason == "Patient request"
    assert appt.cancelled_at is not None


def test_reschedule_links_and_cancels_previous():
    doctor = _doctor()
    monday = _next_weekday(0)
    tuesday = monday + dt.timedelta(days=1)
    slot_mon = _slot(doctor, weekday=monday.weekday())
    slot_tue = _slot(doctor, weekday=tuesday.weekday())
    appt = services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=monday, slot=slot_mon
    )

    new_appt = services.reschedule_appointment(
        instance=appt, appt_date=tuesday, slot=slot_tue
    )
    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CANCELLED
    assert new_appt.rescheduled_from_id == appt.pk
    assert new_appt.appt_date == tuesday
    assert new_appt.token_no == 1


def test_daily_token_row_created():
    doctor = _doctor()
    monday = _next_weekday(0)
    slot = _slot(doctor, weekday=monday.weekday())
    services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=monday, slot=slot
    )
    counter = DoctorDailyToken.objects.get(doctor=doctor, token_date=monday)
    assert counter.last_token == 1
