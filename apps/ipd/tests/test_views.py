"""View / access-control tests for the IPD module."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.ipd import services
from apps.ipd.models import Admission, ClearanceDepartment
from apps.opd.models import Doctor

from .factories import (allocate, make_admission, make_bed, make_drug,
                        make_patient)

pytestmark = pytest.mark.django_db

_FULL = [
    "ipd.view_admission",
    "ipd.add_admission",
    "ipd.change_admission",
    "ipd.add_bedtransfer",
    "ipd.view_ward",
    "ipd.view_bed",
    "ipd.change_dischargeclearance",
    "ipd.view_dischargesummary",
    "ipd.add_dischargesummary",
    "ipd.add_nursingnote",
    "ipd.add_medicationadministration",
    "ipd.add_intakeoutput",
]


def _role_with(*codenames: str) -> Role:
    role, _ = Role.objects.get_or_create(name="IPD-" + "-".join(codenames))
    role.permissions.clear()
    for spec in codenames:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return role


def _user_with(*codenames: str, username: str = "ipd-user"):
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(_role_with(*codenames))
    return user


def test_anonymous_redirects_to_login():
    response = Client().get(reverse("ipd:admission_list"))
    assert response.status_code == 302
    assert "login" in response.url


def test_missing_permission_is_denied():
    client = Client()
    client.force_login(_user_with("patients.view_patient"))
    assert client.get(reverse("ipd:admission_list")).status_code == 403


def test_bed_map_requires_both_permissions():
    client = Client()
    client.force_login(_user_with("ipd.view_ward"))
    assert client.get(reverse("ipd:bed_map")).status_code == 403


def _admitted_admission():
    return allocate(make_admission(), make_bed())


def test_full_admission_lifecycle():
    client = Client()
    clin = _user_with(
        *_FULL,
        "ipd.add_medicationadministration",
        "ipd.add_intakeoutput",
        "ipd.add_nursingnote",
    )
    client.force_login(clin)

    patient = make_patient()
    bed = make_bed()
    doctor = Doctor.objects.create(name_en="Dr. Flow", specialization="Med")

    url = reverse("ipd:admission_create")
    assert client.get(url).status_code == 200
    response = client.post(
        url,
        {
            "patient": patient.pk,
            "doctor": doctor.pk,
            "admission_type": "routine",
            "reason": "Fever",
        },
    )
    assert response.status_code == 302
    admission = Admission.objects.get(patient=patient)

    detail = reverse("ipd:admission_detail", args=[admission.pk])
    assert client.get(detail).status_code == 200

    response = client.post(
        reverse("ipd:admission_allocate", args=[admission.pk]), {"bed": bed.pk}
    )
    assert response.status_code == 302
    admission.refresh_from_db()
    assert admission.ip_number is not None

    response = client.post(
        reverse("ipd:discharge_request", args=[admission.pk]), {"reason": "Recovered"}
    )
    assert response.status_code == 302
    admission.refresh_from_db()
    assert admission.status == "discharge_requested"

    for dep in (
        ClearanceDepartment.LAB,
        ClearanceDepartment.PHARMACY,
        ClearanceDepartment.BILLING,
    ):
        assert (
            client.post(
                reverse("ipd:discharge_clearance", args=[admission.pk]),
                {"department": dep, "cleared": "on"},
            ).status_code
            == 302
        )

    response = client.post(
        reverse("ipd:discharge", args=[admission.pk]),
        {
            "discharge_type": "routine",
            "diagnosis_summary": "Viral fever",
            "treatment_given": "Paracetamol",
            "follow_up": "In 3 days",
            "discharge_advice": "Rest",
        },
    )
    assert response.status_code == 302
    assert (
        client.get(reverse("ipd:discharge_summary", args=[admission.pk])).status_code
        == 200
    )


def test_care_forms_write_rows():
    client = Client()
    client.force_login(_user_with(*_FULL))
    admission = _admitted_admission()
    drug = make_drug()

    assert (
        client.post(
            reverse("ipd:nursing_note_create", args=[admission.pk]),
            {"shift": "day", "note": "Comfortable"},
        ).status_code
        == 302
    )

    now = timezone.now().replace(microsecond=0).strftime("%Y-%m-%dT%H:%M")
    assert (
        client.post(
            reverse("ipd:mar_create", args=[admission.pk]),
            {
                "drug": drug.pk,
                "dose": "500mg",
                "route": "oral",
                "scheduled_for": now,
                "action": "given",
            },
        ).status_code
        == 302
    )

    assert (
        client.post(
            reverse("ipd:intake_output_create", args=[admission.pk]),
            {
                "fluid_type": "intake",
                "category": "oral",
                "volume_ml": 200,
                "shift": "day",
            },
        ).status_code
        == 302
    )

    admission.refresh_from_db()
    assert admission.nursing_notes.count() == 1
    assert admission.medications.count() == 1
    assert admission.intake_output.count() == 1
    assert (
        client.get(reverse("ipd:admission_detail", args=[admission.pk])).status_code
        == 200
    )


def test_bed_map_lists_created_wards():
    client = Client()
    client.force_login(_user_with("ipd.view_ward", "ipd.view_bed"))
    make_bed()
    response = client.get(reverse("ipd:bed_map"))
    assert response.status_code == 200
    assert b"General ward" in response.content


def test_pdf_endpoint_renders_pdf():
    client = Client()
    client.force_login(_user_with(*_FULL))
    admission = _admitted_admission()
    for dep in ("lab", "pharmacy", "billing"):
        services.set_clearance(admission=admission, department=dep, cleared=True)
    services.discharge(
        admission=admission,
        summary_data={
            "diagnosis_summary": "X",
            "treatment_given": "Y",
            "follow_up": "Z",
        },
    )
    response = client.get(reverse("ipd:discharge_summary_pdf", args=[admission.pk]))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
