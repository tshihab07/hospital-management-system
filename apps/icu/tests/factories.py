"""Shared test factories for the ICU / Emergency module."""

from __future__ import annotations

import itertools

from apps.accounts.models import Role, User
from apps.icu import services
from apps.icu.models import EmergencyCase, IcuRecord
from apps.ipd import services as ipd_services
from apps.ipd.models import Bed, Ward
from apps.opd.models import Doctor
from apps.patients.models import Patient

_counter = itertools.count(1)


def make_patient(**overrides) -> Patient:
    n = next(_counter)
    data = {
        "uhid": f"ICU-2026-{n:06d}",
        "full_name_en": f"ICU Patient {n}",
        "gender": "male",
        "phone": f"018{n:08d}"[:11],
        "age_years": 40,
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def make_doctor(**overrides) -> Doctor:
    n = next(_counter)
    data = {
        "name_en": f"Dr. ICU {n}",
        "specialization": "Critical Care",
        "email": f"dr.icu{n}@example.com",
    }
    data.update(overrides)
    return Doctor.objects.create(**data)


def make_admission(patient=None, doctor=None):
    patient = patient or make_patient()
    doctor = doctor or make_doctor()
    ward = Ward.objects.create(name=f"ICU Ward {next(_counter)}", ward_type="icu")
    bed = Bed.objects.create(ward=ward, bed_no="01", daily_rate="8000")
    admission = ipd_services.request_admission(
        patient=patient, doctor=doctor, reason="Critical care"
    )
    return ipd_services.allocate_bed(admission=admission, bed=bed)


def make_icu_record(admission=None, **overrides) -> IcuRecord:
    admission = admission or make_admission()
    data = {"pulse": 80, "spo2": 98, "bp_systolic": 120, "bp_diastolic": 80}
    data.update(overrides)
    return services.create_icu_record(admission=admission, data=data)


def make_emergency_case(patient=None, **overrides) -> EmergencyCase:
    return services.open_emergency_case(
        patient=patient or make_patient(),
        complaint=overrides.pop("complaint", "Chest pain"),
        triage_level=overrides.pop("triage_level", "yellow"),
        attending_doctor=overrides.pop("attending_doctor", None),
        vitals=overrides.pop("vitals", None),
    )


def make_user(*permission_specs: str, username: str = "icu-user") -> User:
    """Create a user whose role holds the given ``app.codename`` permissions."""
    from django.contrib.auth.models import Permission

    role, _ = Role.objects.get_or_create(name="ICU-" + "-".join(permission_specs))
    role.permissions.clear()
    for spec in permission_specs:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(role)
    return user
