"""Access-control and CRUD tests for the RBAC admin screens."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.accounts.models import Role, User
from core.audit import AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(client):
    user = User.objects.create_superuser(username="root", password="x", email="")
    client.force_login(user)
    return client


def _role_with(*codenames: str) -> Role:
    role = Role.objects.create(name="Test Role")
    for codename in codenames:
        role.permissions.add(
            Permission.objects.get(
                content_type__app_label="accounts", codename=codename
            )
        )
    return role


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("accounts:user_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_user_without_permission_gets_403(client):
    user = User.objects.create_user(username="nobody", password="x")
    client.force_login(user)
    assert client.get(reverse("accounts:user_list")).status_code == 403
    assert client.get(reverse("accounts:role_list")).status_code == 403


def test_user_with_view_permission_can_list(client):
    role = _role_with("view_user")
    user = User.objects.create_user(username="viewer", password="x")
    user.roles.add(role)
    client.force_login(user)
    assert client.get(reverse("accounts:user_list")).status_code == 200


def test_admin_can_create_user(admin):
    role = _role_with("view_user")
    response = admin.post(
        reverse("accounts:user_create"),
        {
            "username": "newbie",
            "email": "n@example.com",
            "full_name_en": "New Bie",
            "full_name_bn": "",
            "phone": "",
            "designation": "Intern",
            "is_staff": "on",
            "is_active": "on",
            "roles": [str(role.pk)],
            "password1": "Str0ngPass!23",
            "password2": "Str0ngPass!23",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(username="newbie")
    assert user.roles.count() == 1
    assert AuditLog.objects.filter(
        action="create", model_name__contains="User"
    ).exists()


def test_admin_can_create_role_with_permissions(admin):
    perm = Permission.objects.get(
        content_type__app_label="accounts", codename="view_user"
    )
    response = admin.post(
        reverse("accounts:role_create"),
        {"name": "Reception", "description": "Front desk", "permissions": [perm.pk]},
    )
    assert response.status_code == 302
    role = Role.objects.get(name="Reception")
    assert role.permission_count == 1


def test_system_role_cannot_be_deleted(admin):
    system_role = Role.objects.create(name="System", is_system=True)
    response = admin.post(reverse("accounts:role_delete", args=[system_role.pk]))
    assert response.status_code == 302
    assert Role.objects.filter(pk=system_role.pk).exists()


def test_user_cannot_deactivate_self(admin):
    response = admin.post(
        reverse("accounts:user_toggle_active", args=[admin.session["_auth_user_id"]])
    )
    assert response.status_code == 302
    user = User.objects.get(pk=admin.session["_auth_user_id"])
    assert user.is_active
