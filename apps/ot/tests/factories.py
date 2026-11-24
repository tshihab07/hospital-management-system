"""Shared test factories for the Operation Theatre module."""

from __future__ import annotations

import itertools

from apps.accounts.models import Role, User
from apps.opd.models import Doctor
from apps.ot import services
from apps.ot.models import OTRoom, Surgery
from apps.patients.models import Patient

_counter = itertools.count(1)


def make_patient(**overrides) -> Patient:
    n = next(_counter)
    data = {
        "uhid": f"OT-2026-{n:06d}",
        "full_name_en": f"OT Patient {n}",
        "gender": "male",
        "phone": f"019{n:08d}"[:11],
        "age_years": 45,
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def make_doctor(**overrides) -> Doctor:
    n = next(_counter)
    data = {
        "name_en": f"Dr. OT {n}",
        "specialization": "Surgery",
        "email": f"dr.ot{n}@example.com",
    }
    data.update(overrides)
    return Doctor.objects.create(**data)


def make_room(**overrides) -> OTRoom:
    n = next(_counter)
    data = {"name": f"OT Test {n}", "room_no": f"T-{n:03d}", "room_type": "major"}
    data.update(overrides)
    return OTRoom.objects.create(**data)


def make_surgery(patient=None, surgeon=None, room=None, **overrides) -> Surgery:
    from datetime import date, time

    data = {
        "patient": patient or make_patient(),
        "surgeon": surgeon or make_doctor(),
        "ot_room": room or make_room(),
        "scheduled_date": overrides.pop("scheduled_date", date(2026, 6, 1)),
        "start_time": overrides.pop("start_time", time(9, 0)),
        "end_time": overrides.pop("end_time", time(10, 0)),
        "procedure_name": overrides.pop("procedure_name", "Appendectomy"),
    }
    data.update(overrides)
    return services.schedule_surgery(**data)


def make_user(*permission_specs: str, username: str = "ot-user") -> User:
    """Create a user whose role holds the given ``app.codename`` permissions."""
    from django.contrib.auth.models import Permission

    role, _ = Role.objects.get_or_create(name="OT-" + "-".join(permission_specs))
    role.permissions.clear()
    for spec in permission_specs:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(role)
    return user
