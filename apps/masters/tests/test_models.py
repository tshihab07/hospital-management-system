"""Model-level tests for master data."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.masters.models import (Bed, BedType, Department, Drug,
                                 HospitalProfile, Ward)

pytestmark = pytest.mark.django_db


def test_drug_str_includes_variant():
    drug = Drug.objects.create(
        generic_name="Paracetamol", brand_name="Napa", strength="500 mg"
    )
    assert "Paracetamol" in str(drug)
    assert "Napa" in str(drug)


def test_bed_unique_per_ward():
    ward = Ward.objects.create(name="W1", code="W1")
    bt = BedType.objects.create(name="General")
    Bed.objects.create(ward=ward, bed_no="B1", bed_type=bt)
    with pytest.raises(IntegrityError):
        Bed.objects.create(ward=ward, bed_no="B1", bed_type=bt)


def test_department_defaults_active():
    dept = Department.objects.create(name="OPD", code="OPD")
    assert dept.is_active is True


def test_hospital_profile_load_is_singleton():
    HospitalProfile.objects.create(name_en="First")
    HospitalProfile.objects.create(name_en="Second")
    assert HospitalProfile.load().name_en == "First"


def test_hospital_profile_load_creates_default():
    assert HospitalProfile.objects.count() == 0
    profile = HospitalProfile.load()
    assert profile.pk is not None
    assert HospitalProfile.objects.count() == 1
