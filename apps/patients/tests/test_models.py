"""Model-level tests for patients."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError

from apps.patients.models import Patient

pytestmark = pytest.mark.django_db


def _patient(**overrides):
    data = {
        "uhid": "DHK-2026-000001",
        "full_name_en": "Test Patient",
        "date_of_birth": dt.date(1990, 1, 1),
        "gender": "male",
        "phone": "01700000000",
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def test_age_from_dob():
    patient = _patient(date_of_birth=dt.date.today().replace(year=1995))
    assert patient.age is not None


def test_age_falls_back_to_stated_years():
    patient = _patient(date_of_birth=None, age_years=45)
    assert patient.age == 45


def test_clean_requires_dob_or_age():
    patient = _patient(date_of_birth=None, age_years=None)
    with pytest.raises(ValidationError):
        patient.full_clean()


def test_dob_cannot_be_in_future():
    patient = _patient(date_of_birth=dt.date.today() + dt.timedelta(days=1))
    with pytest.raises(ValidationError):
        patient.full_clean()


def test_uhid_is_immutable():
    patient = _patient()
    patient.uhid = "OTHER-2026-000002"
    with pytest.raises(ValidationError):
        patient.save()


def test_soft_delete_hides_from_default_manager():
    patient = _patient()
    patient.soft_delete()
    assert not Patient.objects.filter(pk=patient.pk).exists()
    assert Patient.all_objects.filter(pk=patient.pk).exists()
