"""Shared test factories for the EMR module."""

from __future__ import annotations

import itertools

from apps.emr.models import Encounter, EncounterType
from apps.opd.models import Doctor
from apps.patients.models import Patient

_counter = itertools.count(1)


def make_patient(**overrides) -> Patient:
    n = next(_counter)
    data = {
        "uhid": f"E-2026-{n:06d}",
        "full_name_en": f"EMR Patient {n}",
        "gender": "male",
        "phone": f"017{n:08d}"[:11],
        "age_years": 30,
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def make_doctor(**overrides) -> Doctor:
    n = next(_counter)
    data = {"name_en": f"Dr. EMR {n}", "specialization": "Medicine"}
    data.update(overrides)
    return Doctor.objects.create(**data)


def make_encounter(patient=None, doctor=None, **overrides) -> Encounter:
    return Encounter.objects.create(
        patient=patient or make_patient(),
        doctor=doctor or make_doctor(),
        encounter_type=overrides.pop("encounter_type", EncounterType.OUTPATIENT),
        **overrides,
    )
