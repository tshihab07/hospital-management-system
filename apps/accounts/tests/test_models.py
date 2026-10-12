"""Model-level tests for identity & RBAC."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from apps.accounts.models import Role, User

pytestmark = pytest.mark.django_db


def _perm(codename: str, app_label: str = "accounts") -> Permission:
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def test_role_permission_count():
    role = Role.objects.create(name="Counter")
    role.permissions.add(_perm("view_user"), _perm("add_user"))
    assert role.permission_count == 2


def test_primary_role_and_role_names():
    user = User.objects.create_user(username="multi", password="x")
    user.roles.add(Role.objects.create(name="Bravo"), Role.objects.create(name="Alpha"))
    assert user.role_names == ["Alpha", "Bravo"]
    assert user.primary_role.name == "Alpha"


def test_has_role_superuser_shortcut():
    su = User.objects.create_superuser(username="root", password="x", email="")
    assert su.has_role("Does Not Exist")


def test_has_role_membership():
    user = User.objects.create_user(username="nurse", password="x")
    user.roles.add(Role.objects.create(name="Nurse"))
    assert user.has_role("Nurse", "Doctor")
    assert not user.has_role("Doctor")
