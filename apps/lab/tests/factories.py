"""Shared test factories for the Laboratory & Radiology module."""

from __future__ import annotations

import itertools

from apps.accounts.models import Role, User
from apps.emr import services as emr_services
from apps.emr.models import Encounter, EncounterType
from apps.masters.models import LabTest, RadiologyTest
from apps.opd.models import Doctor
from apps.patients.models import Patient

_counter = itertools.count(1)


def make_patient(**overrides) -> Patient:
    n = next(_counter)
    data = {
        "uhid": f"L-2026-{n:06d}",
        "full_name_en": f"Lab Patient {n}",
        "gender": "male",
        "phone": f"016{n:08d}"[:11],
        "age_years": 40,
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def make_doctor(**overrides) -> Doctor:
    n = next(_counter)
    data = {"name_en": f"Dr. Lab {n}", "specialization": "Pathology"}
    data.update(overrides)
    return Doctor.objects.create(**data)


def make_encounter(patient=None, doctor=None, **overrides) -> Encounter:
    return Encounter.objects.create(
        patient=patient or make_patient(),
        doctor=doctor or make_doctor(),
        encounter_type=overrides.pop("encounter_type", EncounterType.OUTPATIENT),
        **overrides,
    )


def make_lab_test(**overrides) -> LabTest:
    n = next(_counter)
    data = {
        "code": f"LT-{n:04d}",
        "name": f"Lab Test {n}",
        "category": "Haematology",
        "price": "250.00",
        "reference_range": "4.0 - 10.0",
        "unit": "g/dL",
        "sample_type": "Blood",
    }
    data.update(overrides)
    return LabTest.objects.create(**data)


def make_radiology_test(**overrides) -> RadiologyTest:
    n = next(_counter)
    data = {
        "code": f"RT-{n:04d}",
        "name": f"Radiology Test {n}",
        "modality": "xray",
        "price": "600.00",
    }
    data.update(overrides)
    return RadiologyTest.objects.create(**data)


def make_lab_order(tests=None, encounter=None, **overrides):
    encounter = encounter or make_encounter()
    tests = tests or [make_lab_test()]
    return emr_services.create_lab_order(
        encounter=encounter,
        tests=tests,
        priority=overrides.pop("priority", None),
        notes=overrides.pop("notes", ""),
    )


def make_radiology_order(tests=None, encounter=None, **overrides):
    encounter = encounter or make_encounter()
    tests = tests or [make_radiology_test()]
    return emr_services.create_radiology_order(
        encounter=encounter,
        tests=tests,
        priority=overrides.pop("priority", None),
        clinical_indication=overrides.pop("clinical_indication", ""),
    )


def make_user(*permission_specs: str, username: str = "lab-user") -> User:
    """Create a user whose role holds the given ``app.codename`` permissions."""
    from django.contrib.auth.models import Permission

    role, _ = Role.objects.get_or_create(name="LAB-" + "-".join(permission_specs))
    role.permissions.clear()
    for spec in permission_specs:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(role)
    return user
