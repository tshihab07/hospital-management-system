"""Shared test factories for the Patient Portal (RULES Phase 15)."""

from __future__ import annotations

import itertools

from django.contrib.auth import get_user_model

from apps.patients.models import Patient

_counter = itertools.count(1)
User = get_user_model()


def make_patient(**overrides) -> Patient:
    n = next(_counter)
    data = {
        "uhid": f"P-2026-{n:06d}",
        "full_name_en": f"Portal Patient {n}",
        "gender": "male",
        "phone": f"019{n:08d}"[:11],
        "email": f"portal{n}@example.com",
        "age_years": 35,
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def make_portal_user(patient: Patient | None = None, *, password: str = "PortalPass123"):
    """Create an active portal account linked to a (new or given) patient."""
    patient = patient or make_patient()
    user = User.objects.create_user(
        username=patient.uhid,
        password=password,
        email=patient.email,
        phone=patient.phone,
        full_name_en=patient.full_name_en,
        is_active=True,
        is_staff=False,
    )
    patient.portal_user = user
    patient.save(update_fields=["portal_user", "updated_at"])
    return patient, user


def make_staff_user(**overrides):
    data = {"username": f"staff{next(_counter)}", "password": "x", "is_staff": True}
    data.update(overrides)
    return User.objects.create_user(**data)
