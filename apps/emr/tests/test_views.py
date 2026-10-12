"""View / access-control tests for the EMR module."""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.emr import services
from apps.emr.models import (Allergy, DrugInteractionRule, Encounter,
                             InteractionSeverity, OrderStatus, Prescription,
                             ProblemListEntry)
from apps.masters.models import Drug, LabTest
from apps.opd.models import Appointment, AppointmentStatus

from .factories import make_doctor, make_encounter, make_patient

pytestmark = pytest.mark.django_db


def _role_with(*codenames: str) -> Role:
    name = "EMR-" + "-".join(codenames)
    role, _ = Role.objects.get_or_create(name=name)
    role.permissions.clear()
    for spec in codenames:
        app_label, _, codename = spec.partition(".")
        role.permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return role


def _user_with(*codenames: str, username: str = "emr-user"):
    user = User.objects.create_user(username=username, password="x")
    user.roles.add(_role_with(*codenames))
    return user


def _clinician():
    return _user_with(
        "emr.view_encounter",
        "emr.add_encounter",
        "emr.change_encounter",
        "emr.view_vital",
        "emr.add_vital",
        "emr.add_visitdiagnosis",
        "emr.view_prescription",
        "emr.add_prescription",
        "emr.change_prescription",
        "emr.view_laborder",
        "emr.add_laborder",
        "emr.change_laborder",
        "emr.view_problemlistentry",
        "emr.add_problemlistentry",
        "emr.change_problemlistentry",
        "emr.view_allergy",
        "emr.add_allergy",
        username="clinician",
    )


@pytest.fixture
def admin(client):
    user = User.objects.create_superuser(username="root-emr", password="x", email="")
    client.force_login(user)
    return client


def test_anonymous_redirected_to_login(client):
    response = client.get(reverse("emr:encounter_list"))
    assert response.status_code == 302
    assert "/accounts/login" in response.url


def test_permission_denied_without_perm(client):
    user = User.objects.create_user(username="nobody", password="x")
    client.force_login(user)
    response = client.get(reverse("emr:encounter_list"))
    assert response.status_code == 403


def test_encounter_list_renders(client):
    client.force_login(_clinician())
    make_encounter()
    response = client.get(reverse("emr:encounter_list"))
    assert response.status_code == 200
    assert b"Encounters" in response.content


def test_open_encounter_from_appointment(client):
    client.force_login(_clinician())
    appointment = Appointment.objects.create(
        patient=make_patient(),
        doctor=make_doctor(),
        appt_date=dt.date(2026, 6, 1),
        token_no=1,
    )
    response = client.post(
        reverse("emr:encounter_open") + f"?appointment={appointment.pk}",
        {
            "appointment": appointment.pk,
            "patient": appointment.patient.pk,
            "doctor": appointment.doctor.pk,
            "encounter_type": "outpatient",
            "chief_complaint": "Fever",
        },
    )
    assert response.status_code == 302
    encounter = Encounter.objects.get(appointment=appointment)
    assert encounter.chief_complaint == "Fever"
    assert response.url == reverse("emr:encounter_detail", args=[encounter.pk])


def test_patient_timeline_renders(client):
    client.force_login(_clinician())
    patient = make_patient()
    encounter = make_encounter(patient=patient)
    services.record_vitals(encounter=encounter, data={"pulse": 70})
    response = client.get(reverse("emr:patient_timeline", args=[patient.pk]))
    assert response.status_code == 200


def _prescription_post(drug_a, drug_b):
    return {
        "form-TOTAL_FORMS": "2",
        "form-INITIAL_FORMS": "0",
        "form-MIN_NUM_FORMS": "0",
        "form-MAX_NUM_FORMS": "1000",
        "form-0-drug": drug_a.pk,
        "form-0-dose": "5 mg",
        "form-0-route": "oral",
        "form-0-frequency": "1+0+0",
        "form-0-duration_days": "5",
        "form-0-quantity": "5",
        "form-1-drug": drug_b.pk,
        "form-1-dose": "75 mg",
        "form-1-route": "oral",
        "form-1-frequency": "0+1+0",
        "form-1-duration_days": "5",
        "form-1-quantity": "5",
        "notes": "Take after food.",
    }


def test_prescription_create_issues_and_warns(client):
    client.force_login(_clinician())
    encounter = make_encounter()
    a = Drug.objects.create(generic_name="Warfarin")
    b = Drug.objects.create(generic_name="Aspirin")
    DrugInteractionRule.objects.create(
        drug_a=a, drug_b=b, severity=InteractionSeverity.MAJOR
    )
    response = client.post(
        reverse("emr:prescription_create", args=[encounter.pk]),
        _prescription_post(a, b),
    )
    assert response.status_code == 302
    assert Prescription.objects.filter(encounter=encounter).count() == 1


def test_prescription_print_and_pdf(client):
    client.force_login(_clinician())
    encounter = make_encounter()
    drug = Drug.objects.create(generic_name="Paracetamol")
    rx, _ = services.issue_prescription(
        encounter=encounter,
        items=[{"drug": drug, "dose": "500 mg", "frequency": "1+1+1"}],
    )
    print_response = client.get(reverse("emr:prescription_print", args=[rx.pk]))
    assert print_response.status_code == 200

    pdf_response = client.get(reverse("emr:prescription_pdf", args=[rx.pk]))
    assert pdf_response.status_code == 200
    assert pdf_response["Content-Type"] == "application/pdf"
    assert pdf_response.content[:4] == b"%PDF"


def test_problem_list_add(client):
    client.force_login(_clinician())
    patient = make_patient()
    response = client.post(
        reverse("emr:problem_list", args=[patient.pk]),
        {"description": "Asthma", "onset_date": "2020-01-01"},
    )
    assert response.status_code == 302
    assert ProblemListEntry.objects.filter(
        patient=patient, description="Asthma"
    ).exists()


def test_allergy_list_add(client):
    client.force_login(_clinician())
    patient = make_patient()
    response = client.post(
        reverse("emr:allergy_list", args=[patient.pk]),
        {"allergen": "Peanut", "allergy_type": "food", "severity": "severe"},
    )
    assert response.status_code == 302
    assert Allergy.objects.filter(patient=patient, allergen="Peanut").exists()


def test_lab_order_create_and_status(client):
    client.force_login(_clinician())
    encounter = make_encounter()
    test = LabTest.objects.create(code="CBC-V", name="CBC")
    response = client.post(
        reverse("emr:lab_order_create", args=[encounter.pk]),
        {"tests": [test.pk], "priority": "routine", "notes": ""},
    )
    assert response.status_code == 302
    order = encounter.lab_orders.first()
    assert order is not None

    status_response = client.post(
        reverse("emr:order_status", args=["lab", order.pk]), {"status": "completed"}
    )
    assert status_response.status_code == 302
    order.refresh_from_db()
    assert order.status == OrderStatus.COMPLETED


def test_open_then_close_completes_appointment(client):
    """Opening drives scheduled → in_consultation; closing completes it."""
    client.force_login(_clinician())
    appointment = Appointment.objects.create(
        patient=make_patient(),
        doctor=make_doctor(),
        appt_date=dt.date(2026, 6, 1),
        token_no=1,
    )
    client.post(
        reverse("emr:encounter_open") + f"?appointment={appointment.pk}",
        {
            "appointment": appointment.pk,
            "patient": appointment.patient.pk,
            "doctor": appointment.doctor.pk,
            "encounter_type": "outpatient",
            "chief_complaint": "Chest pain",
        },
    )
    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.IN_CONSULTATION
    encounter = Encounter.objects.get(appointment=appointment)

    client.post(reverse("emr:encounter_close", args=[encounter.pk]))
    appointment.refresh_from_db()
    assert appointment.status == AppointmentStatus.COMPLETED


def test_closed_encounter_blocks_new_orders(client):
    client.force_login(_clinician())
    encounter = make_encounter()
    services.close_encounter(instance=encounter)
    a = Drug.objects.create(generic_name="Metformin")
    b = Drug.objects.create(generic_name="Glibenclamide")

    get_response = client.get(reverse("emr:prescription_create", args=[encounter.pk]))
    assert get_response.status_code == 302
    assert get_response.url == reverse("emr:encounter_detail", args=[encounter.pk])

    post_response = client.post(
        reverse("emr:prescription_create", args=[encounter.pk]),
        _prescription_post(a, b),
    )
    assert post_response.status_code == 302
    assert Prescription.objects.count() == 0


def test_vital_and_diagnosis_add(client):
    client.force_login(_clinician())
    encounter = make_encounter()
    client.post(
        reverse("emr:vital_create", args=[encounter.pk]),
        {"pulse": "88", "bp_systolic": "130", "bp_diastolic": "85", "spo2": "98"},
    )
    client.post(
        reverse("emr:diagnosis_create", args=[encounter.pk]),
        {"description": "Viral fever", "is_primary": "on"},
    )
    encounter.refresh_from_db()
    assert encounter.vitals.count() == 1
    assert encounter.diagnoses.count() == 1
