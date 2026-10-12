"""Access-control and CRUD tests for patient screens."""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.patients import services
from apps.patients.models import Patient, PatientDocument

pytestmark = pytest.mark.django_db


def _role_with(*codenames: str) -> Role:
    name = "Tester-" + "-".join(codenames)
    role, _ = Role.objects.get_or_create(name=name)
    role.permissions.clear()
    for codename in codenames:
        role.permissions.add(
            Permission.objects.get(
                content_type__app_label="patients", codename=codename
            )
        )
    return role


def _receptionist():
    role = _role_with("view_patient", "add_patient", "change_patient")
    user = User.objects.create_user(username="reception", password="x")
    user.roles.add(role)
    return user


@pytest.fixture
def admin(client):
    user = User.objects.create_superuser(username="root", password="x", email="")
    client.force_login(user)
    return client


def _register(**overrides):
    data = {
        "full_name_en": "Test Patient",
        "gender": "male",
        "date_of_birth": dt.date(1995, 1, 1),
        "phone": "01700000000",
    }
    data.update(overrides)
    return services.register_patient(data=data)


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("patients:list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_without_permission_is_403(client):
    user = User.objects.create_user(username="nobody", password="x")
    client.force_login(user)
    assert client.get(reverse("patients:list")).status_code == 403


def test_receptionist_can_list_and_search(client):
    patient = _register(full_name_en="Karim", uhid="DHK-2026-000101")
    client.force_login(_receptionist())
    assert client.get(reverse("patients:list")).status_code == 200
    url = reverse("patients:list") + f"?q={patient.uhid}"
    assert patient.display_name in client.get(url).content.decode()


def test_duplicate_warning_blocks_until_confirmed(client):
    _register(phone="01700000001", date_of_birth=dt.date(1995, 1, 1))
    client.force_login(_receptionist())
    payload = {
        "full_name_en": "Test Patient",
        "phone": "01700000001",
        "date_of_birth": "1995-01-01",
        "gender": "male",
    }
    response = client.post(reverse("patients:create"), payload)
    assert response.status_code == 200
    assert "Possible duplicate" in response.content.decode()
    assert Patient.objects.count() == 1

    response = client.post(
        reverse("patients:create"), {**payload, "confirm_duplicate": "1"}
    )
    assert response.status_code == 302
    assert Patient.objects.count() == 2


def test_detail_shows_demographics(client):
    patient = _register()
    client.force_login(_receptionist())
    response = client.get(reverse("patients:detail", args=[patient.pk]))
    assert response.status_code == 200
    assert patient.uhid in response.content.decode()


def test_export_streams_csv(client):
    _register()
    client.force_login(_receptionist())
    response = client.get(reverse("patients:export"))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert "UHID" in response.content.decode()


def test_archive_and_restore(client):
    patient = _register()
    role = _role_with("view_patient", "delete_patient", "change_patient")
    user = User.objects.create_user(username="archiver", password="x")
    user.roles.add(role)
    client.force_login(user)

    assert client.post(reverse("patients:delete", args=[patient.pk])).status_code == 302
    patient.refresh_from_db()
    assert patient.is_deleted is True
    assert client.get(reverse("patients:list")).status_code == 200
    assert (
        client.post(reverse("patients:restore", args=[patient.pk])).status_code == 302
    )
    patient.refresh_from_db()
    assert patient.is_deleted is False


def test_document_upload(client):
    patient = _register()
    client.force_login(_receptionist())
    with open("/tmp/opencode/upload.txt", "wb") as fh:
        fh.write(b"sample")
    with open("/tmp/opencode/upload.txt", "rb") as upload:
        response = client.post(
            reverse("patients:document_create", args=[patient.pk]),
            {"title": "Old report", "category": "report", "file": upload},
        )
    assert response.status_code == 302
    assert PatientDocument.objects.filter(patient=patient, title="Old report").exists()


def test_merge_requires_custom_perm(client):
    primary = _register(full_name_en="Primary")
    duplicate = _register(full_name_en="Dup", phone="01700000002")
    viewer = _receptionist()
    client.force_login(viewer)
    response = client.post(
        reverse("patients:merge"),
        {"primary": primary.pk, "duplicate": duplicate.pk},
    )
    assert response.status_code == 403

    merge_role = _role_with("merge_patient")
    admin_user = User.objects.create_user(username="merger", password="x")
    admin_user.roles.add(merge_role)
    client.force_login(admin_user)
    response = client.post(
        reverse("patients:merge"),
        {"primary": primary.pk, "duplicate": duplicate.pk},
    )
    assert response.status_code == 302
    duplicate.refresh_from_db()
    assert duplicate.is_deleted is True
