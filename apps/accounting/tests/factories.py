"""Shared test factories for the Accounting module."""

from __future__ import annotations

import itertools

from apps.accounts.models import Role, User
from apps.billing.tests import factories as billing_factories

from .. import services

# Re-exported so accounting tests share the billing fixtures.
make_charged_bill = billing_factories.make_charged_bill
make_patient = billing_factories.make_patient

_counter = itertools.count(1)


def make_user(*permission_specs: str, username: str = "accounting-user") -> User:
    """Create a user whose role holds the given ``app.codename`` permissions."""
    from django.contrib.auth.models import Permission

    role, _ = Role.objects.get_or_create(name="ACC-" + "-".join(permission_specs))
    role.permissions.clear()
    for spec in permission_specs:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(role)
    return user


def seed_chart():
    return services.seed_chart_of_accounts()


def system_account(key):
    return services.get_system_account(key)
