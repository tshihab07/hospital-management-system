"""Model-level tests for the OPD module."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.opd.models import AvailabilitySlot, Doctor, DoctorDailyToken

pytestmark = pytest.mark.django_db


def _doctor(**overrides) -> Doctor:
    data = {"name_en": "Dr. Test", "specialization": "Medicine"}
    data.update(overrides)
    return Doctor.objects.create(**data)


def test_doctor_str_and_display_name():
    doctor = _doctor(name_en="Dr. Ayesha", specialization="Cardiology")
    assert str(doctor) == "Dr. Ayesha"
    assert doctor.display_name == "Dr. Ayesha, Cardiology"


def test_bmdc_unique():
    _doctor(bmdc_no="B-1")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _doctor(bmdc_no="B-1", name_en="Other")


def test_slot_requires_end_after_start():
    doctor = _doctor()
    slot = AvailabilitySlot(
        doctor=doctor,
        weekday=0,
        start_time=dt.time(13, 0),
        end_time=dt.time(9, 0),
    )
    with pytest.raises(ValidationError):
        slot.full_clean()


def test_slot_unique_per_doctor_day_start():
    doctor = _doctor()
    AvailabilitySlot.objects.create(
        doctor=doctor, weekday=1, start_time=dt.time(9, 0), end_time=dt.time(12, 0)
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AvailabilitySlot.objects.create(
                doctor=doctor,
                weekday=1,
                start_time=dt.time(9, 0),
                end_time=dt.time(11, 0),
            )


def test_daily_token_unique_per_doctor_day():
    doctor = _doctor()
    DoctorDailyToken.objects.create(doctor=doctor, token_date=dt.date(2026, 1, 1))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DoctorDailyToken.objects.create(
                doctor=doctor, token_date=dt.date(2026, 1, 1)
            )
