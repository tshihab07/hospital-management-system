"""Shared test factories for the IPD module."""

from __future__ import annotations

import itertools

from apps.ipd import services
from apps.ipd.models import Bed, Ward
from apps.masters.models import Drug
from apps.opd.models import Doctor
from apps.patients.models import Patient

_counter = itertools.count(1)


def make_ward(*, name: str | None = None, **overrides) -> Ward:
    n = next(_counter)
    data = {"name": name or f"Ward {n}", "floor": "2", "ward_type": "general"}
    data.update(overrides)
    return Ward.objects.create(**data)


def make_bed(
    ward: Ward | None = None, *, bed_no: str | None = None, **overrides
) -> Bed:
    n = next(_counter)
    data = {
        "ward": ward or make_ward(),
        "bed_no": bed_no or f"B{n:02d}",
        "daily_rate": "500",
    }
    data.update(overrides)
    return Bed.objects.create(**data)


def make_patient(**overrides) -> Patient:
    n = next(_counter)
    data = {
        "uhid": f"IP-2026-{n:06d}",
        "full_name_en": f"IPD Patient {n}",
        "gender": "male",
        "phone": f"019{n:08d}"[:11],
        "age_years": 35,
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def make_doctor(**overrides) -> Doctor:
    n = next(_counter)
    data = {"name_en": f"Dr. IPD {n}", "specialization": "Medicine"}
    data.update(overrides)
    return Doctor.objects.create(**data)


def make_drug(name: str = "Paracetamol") -> Drug:
    return Drug.objects.create(generic_name=name)


def make_admission(patient=None, doctor=None, **overrides):
    return services.request_admission(
        patient=patient or make_patient(),
        doctor=doctor or make_doctor(),
        reason=overrides.pop("reason", "Fever, observation"),
        admission_note=overrides.pop("admission_note", ""),
        admission_type=overrides.pop("admission_type", None),
        encounter=overrides.pop("encounter", None),
    )


def allocate(admission, bed: Bed):
    return services.allocate_bed(admission=admission, bed=bed)
