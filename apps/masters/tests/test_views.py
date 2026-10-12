"""Access-control and CRUD tests for the master-data screens."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.masters.models import Department, Drug

pytestmark = pytest.mark.django_db


def _role_with(*codenames: str) -> Role:
    role = Role.objects.create(name="Masters Tester")
    for codename in codenames:
        role.permissions.add(
            Permission.objects.get(content_type__app_label="masters", codename=codename)
        )
    return role


@pytest.fixture
def admin(client):
    user = User.objects.create_superuser(username="root", password="x", email="")
    client.force_login(user)
    return client


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("masters:home"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_home_lists_permitted_masters(client):
    role = _role_with("view_department")
    user = User.objects.create_user(username="viewer", password="x")
    user.roles.add(role)
    client.force_login(user)
    response = client.get(reverse("masters:home"))
    assert response.status_code == 200
    assert "Departments" in response.content.decode()


def test_list_without_permission_is_403(client):
    user = User.objects.create_user(username="nobody", password="x")
    client.force_login(user)
    response = client.get(reverse("masters:master_list", args=["departments"]))
    assert response.status_code == 403


def test_list_with_view_permission(client):
    role = _role_with("view_department")
    user = User.objects.create_user(username="viewer2", password="x")
    user.roles.add(role)
    client.force_login(user)
    Department.objects.create(name="OPD", code="OPD")
    response = client.get(reverse("masters:master_list", args=["departments"]))
    assert response.status_code == 200
    assert "OPD" in response.content.decode()


def test_unknown_slug_returns_404(admin):
    assert (
        admin.get(reverse("masters:master_list", args=["nonsense"])).status_code == 404
    )


def test_admin_creates_department(admin):
    response = admin.post(
        reverse("masters:master_create", args=["departments"]),
        {
            "name": "Cardiology",
            "code": "CARD",
            "type": "opd",
            "description": "",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    assert Department.objects.filter(code="CARD").exists()


def test_admin_toggles_drug_active(admin):
    drug = Drug.objects.create(generic_name="Napa")
    response = admin.post(reverse("masters:master_toggle", args=["drugs", drug.pk]))
    assert response.status_code == 302
    drug.refresh_from_db()
    assert drug.is_active is False


def test_toggle_rejects_get(admin):
    drug = Drug.objects.create(generic_name="Napa")
    response = admin.get(reverse("masters:master_toggle", args=["drugs", drug.pk]))
    assert response.status_code == 405


def test_hospital_profile_updates(admin):
    response = admin.post(
        reverse("masters:hospital_profile"),
        {
            "name_en": "City Hospital",
            "name_bn": "",
            "address": "",
            "city": "Dhaka",
            "postcode": "",
            "phone": "",
            "email": "",
            "website": "",
            "uhid_prefix": "CTH",
            "ip_prefix": "IP",
            "vat_reg_no": "",
            "bin_no": "",
            "trade_license": "",
            "footer_note": "",
        },
    )
    assert response.status_code == 302
    from apps.masters.models import HospitalProfile

    assert HospitalProfile.load().name_en == "City Hospital"
