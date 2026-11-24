"""Shared test factories for the Billing & Payments module."""

from __future__ import annotations

import itertools

from apps.accounts.models import Role, User
from apps.patients.models import Patient

from .. import services
from ..models import Bill, BillType

_counter = itertools.count(1)


def make_patient(**overrides) -> Patient:
    n = next(_counter)
    data = {
        "uhid": f"B-2026-{n:06d}",
        "full_name_en": f"Billing Patient {n}",
        "gender": "male",
        "phone": f"018{n:08d}"[:11],
        "age_years": 40,
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def make_bill(*, patient=None, bill_type=BillType.OPD, **overrides) -> Bill:
    return services.create_bill(
        patient or make_patient(), bill_type=bill_type, **overrides
    )


def make_charged_bill(*, amount="1000.00", vat_rate="0", patient=None, **overrides):
    bill = make_bill(patient=patient, **overrides)
    services.post_charge(
        bill,
        item_type="consultation",
        description="Consultation",
        quantity=1,
        unit_price=amount,
        tax_rate=vat_rate,
    )
    return bill


def make_user(*permission_specs: str, username: str = "billing-user") -> User:
    """Create a user whose role holds the given ``app.codename`` permissions."""
    from django.contrib.auth.models import Permission

    role, _ = Role.objects.get_or_create(name="BILL-" + "-".join(permission_specs))
    role.permissions.clear()
    for spec in permission_specs:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(role)
    return user
