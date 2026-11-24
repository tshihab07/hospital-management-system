"""Shared test factories for the Pharmacy & Inventory module."""

from __future__ import annotations

import itertools

from apps.accounts.models import Role, User
from apps.emr.models import (Encounter, EncounterType, Prescription,
                             PrescriptionItem)
from apps.masters.models import Drug
from apps.opd.models import Doctor
from apps.patients.models import Patient

from ..models import PharmacyStore, StockBatch, StoreType, Vendor

_counter = itertools.count(1)


def make_patient(**overrides) -> Patient:
    n = next(_counter)
    data = {
        "uhid": f"P-2026-{n:06d}",
        "full_name_en": f"Pharmacy Patient {n}",
        "gender": "male",
        "phone": f"017{n:08d}"[:11],
        "age_years": 35,
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def make_doctor(**overrides) -> Doctor:
    n = next(_counter)
    data = {"name_en": f"Dr. Pharmacy {n}", "specialization": "General"}
    data.update(overrides)
    return Doctor.objects.create(**data)


def make_encounter(patient=None, doctor=None, **overrides) -> Encounter:
    return Encounter.objects.create(
        patient=patient or make_patient(),
        doctor=doctor or make_doctor(),
        encounter_type=overrides.pop("encounter_type", EncounterType.OUTPATIENT),
        **overrides,
    )


def make_drug(**overrides) -> Drug:
    n = next(_counter)
    data = {
        "generic_name": f"Paracetamol {n}",
        "brand_name": f"Brand {n}",
        "form": "tablet",
        "strength": "500mg",
        "unit": "tablet",
        "unit_price": "5.00",
        "reorder_level": 10,
    }
    data.update(overrides)
    return Drug.objects.create(**data)


def make_store(*, store_type=StoreType.CENTRAL, **overrides) -> PharmacyStore:
    n = next(_counter)
    data = {
        "name": f"Store {n}",
        "code": f"S{n:03d}",
        "store_type": store_type,
    }
    data.update(overrides)
    return PharmacyStore.objects.create(**data)


def make_vendor(**overrides) -> Vendor:
    n = next(_counter)
    data = {"name": f"Vendor {n}", "phone": "01700000000"}
    data.update(overrides)
    return Vendor.objects.create(**data)


def make_batch(*, store=None, drug=None, quantity=100, **overrides) -> StockBatch:
    n = next(_counter)
    data = {
        "store": store or make_store(),
        "drug": drug or make_drug(),
        "batch_no": overrides.pop("batch_no", f"B{n:04d}"),
        "quantity": quantity,
        "purchase_price": "3.00",
        "mrp": "5.00",
    }
    data.update(overrides)
    return StockBatch.objects.create(**data)


def make_prescription(
    *, patient=None, doctor=None, encounter=None, drugs=None, **overrides
):
    encounter = encounter or make_encounter()
    prescription = Prescription.objects.create(
        encounter=encounter,
        patient=patient or encounter.patient,
        doctor=doctor or encounter.doctor,
        **overrides,
    )
    for drug in drugs or [make_drug()]:
        PrescriptionItem.objects.create(
            prescription=prescription,
            drug=drug,
            dose="1 tab",
            frequency="TDS",
            duration_days=3,
            quantity=9,
        )
    return prescription


def make_user(*permission_specs: str, username: str = "pharmacy-user") -> User:
    """Create a user whose role holds the given ``app.codename`` permissions."""
    from django.contrib.auth.models import Permission

    role, _ = Role.objects.get_or_create(name="PHARM-" + "-".join(permission_specs))
    role.permissions.clear()
    for spec in permission_specs:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(role)
    return user
