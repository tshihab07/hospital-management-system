"""Access-control and CRUD tests for OPD screens."""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.opd import services
from apps.opd.models import Appointment, AvailabilitySlot, Doctor
from apps.patients import services as patient_services

pytestmark = pytest.mark.django_db

EMAIL = "django.core.mail.backends.locmem.EmailBackend"


def _role_with(*codenames: str) -> Role:
    name = "OPD-" + "-".join(codenames)
    role, _ = Role.objects.get_or_create(name=name)
    role.permissions.clear()
    for spec in codenames:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return role


def _receptionist():
    role = _role_with(
        "patients.view_patient",
        "patients.add_patient",
        "patients.change_patient",
        "opd.view_doctor",
        "opd.view_appointment",
        "opd.add_appointment",
        "opd.change_appointment",
    )
    user = User.objects.create_user(username="reception-opd", password="x")
    user.roles.add(role)
    return user


@pytest.fixture
def admin(client):
    user = User.objects.create_superuser(username="root-opd", password="x", email="")
    client.force_login(user)
    return client


def _future(weekday: int = 0) -> dt.date:
    today = dt.date.today()
    return today + dt.timedelta(days=(weekday - today.weekday()) % 7 or 7)


def _doctor(**overrides) -> Doctor:
    data = {
        "name_en": "Dr. View",
        "specialization": "Medicine",
        "consultation_fee": "500.00",
        "followup_fee": "250.00",
    }
    data.update(overrides)
    return Doctor.objects.create(**data)


def _slot(doctor, weekday, cap=10):
    return AvailabilitySlot.objects.create(
        doctor=doctor,
        weekday=weekday,
        start_time=dt.time(9, 0),
        end_time=dt.time(13, 0),
        max_patients=cap,
    )


def _patient(**overrides):
    data = {
        "full_name_en": "View Patient",
        "gender": "male",
        "date_of_birth": dt.date(1990, 1, 1),
        "phone": "01700000000",
        "email": "view@example.com",
    }
    data.update(overrides)
    return patient_services.register_patient(data=data)


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("opd:appointment_list"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_without_permission_is_403(client):
    user = User.objects.create_user(username="nobody-opd", password="x")
    client.force_login(user)
    assert client.get(reverse("opd:appointment_list")).status_code == 403


def test_receptionist_can_list(client):
    client.force_login(_receptionist())
    assert client.get(reverse("opd:appointment_list")).status_code == 200


def test_booking_preview_lists_blocks(client):
    doctor = _doctor()
    target = _future(0)
    _slot(doctor, target.weekday())
    client.force_login(_receptionist())
    url = reverse("opd:appointment_book")
    response = client.get(url, {"doctor": doctor.pk, "appt_date": target.isoformat()})
    assert response.status_code == 200
    assert len(response.context["blocks"]) == 1


@override_settings(EMAIL_BACKEND=EMAIL)
def test_booking_post_creates_appointment(client):
    doctor = _doctor()
    target = _future(0)
    slot = _slot(doctor, target.weekday())
    patient = _patient()
    client.force_login(_receptionist())
    response = client.post(
        reverse("opd:appointment_book"),
        {
            "patient": patient.pk,
            "doctor": doctor.pk,
            "appt_date": target.isoformat(),
            "slot": slot.pk,
            "visit_type": "new",
            "notes": "Walk-in",
        },
    )
    assert response.status_code == 302
    appointment = Appointment.objects.get()
    assert appointment.token_no == 1
    assert appointment.patient_id == patient.pk
    assert response.url == reverse("opd:appointment_detail", args=[appointment.pk])


def test_appointment_detail_and_queue_render(client):
    doctor = _doctor()
    target = _future(0)
    slot = _slot(doctor, target.weekday())
    appointment = services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=target, slot=slot
    )
    client.force_login(_receptionist())
    assert (
        client.get(reverse("opd:appointment_detail", args=[appointment.pk])).status_code
        == 200
    )
    assert client.get(reverse("opd:queue")).status_code == 200


def test_status_change_and_cancel(client):
    doctor = _doctor()
    target = _future(0)
    slot = _slot(doctor, target.weekday())
    appointment = services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=target, slot=slot
    )
    client.force_login(_receptionist())

    client.post(
        reverse("opd:appointment_status", args=[appointment.pk]),
        {"status": "arrived"},
    )
    appointment.refresh_from_db()
    assert appointment.status == "arrived"

    client.post(
        reverse("opd:appointment_cancel", args=[appointment.pk]),
        {"reason": "changed mind"},
    )
    appointment.refresh_from_db()
    assert appointment.status == "cancelled"
    assert appointment.cancel_reason == "changed mind"


def test_availability_add_slot(admin):
    doctor = _doctor()
    response = admin.post(
        reverse("opd:doctor_availability", args=[doctor.pk]),
        {
            "weekday": 2,
            "start_time": "10:00",
            "end_time": "12:00",
            "max_patients": 8,
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    assert AvailabilitySlot.objects.filter(doctor=doctor, weekday=2).exists()
