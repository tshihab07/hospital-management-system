"""Tests for the role-aware authentication backend."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from apps.accounts.models import Role, User

pytestmark = pytest.mark.django_db


def _grant(role: Role, codename: str, app_label: str = "accounts") -> None:
    role.permissions.add(
        Permission.objects.get(content_type__app_label=app_label, codename=codename)
    )


def test_role_permission_is_granted():
    role = Role.objects.create(name="Viewer")
    _grant(role, "view_user")
    user = User.objects.create_user(username="viewer", password="x")
    user.roles.add(role)

    assert user.has_perm("accounts.view_user")
    assert "accounts.view_user" in user.get_all_permissions()


def test_role_permission_does_not_grant_others():
    role = Role.objects.create(name="Viewer")
    _grant(role, "view_user")
    user = User.objects.create_user(username="viewer", password="x")
    user.roles.add(role)

    assert not user.has_perm("accounts.add_user")


def test_inactive_user_is_denied_even_with_role():
    role = Role.objects.create(name="Viewer")
    _grant(role, "view_user")
    user = User.objects.create_user(username="viewer", password="x", is_active=False)
    user.roles.add(role)

    assert not user.has_perm("accounts.view_user")


def test_superuser_bypasses_role_checks():
    su = User.objects.create_superuser(username="root", password="x", email="")
    assert su.has_perm("accounts.delete_user")
