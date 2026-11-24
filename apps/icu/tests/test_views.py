"""View / access-control tests for the ICU / Emergency module."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.icu import selectors, services
from apps.icu.models import CriticalAlert, EmergencyCase, HandoverNote

from .factories import (make_admission, make_doctor, make_emergency_case,
                        make_icu_record, make_user)

pytestmark = pytest.mark.django_db

_ICU_VIEW = ["icu.view_icurecord"]
_ALL = [
    "icu.view_icurecord",
    "icu.add_icurecord",
    "icu.view_criticalalert",
    "icu.change_criticalalert",
    "icu.add_criticalscore",
    "icu.view_emergencycase",
    "icu.add_emergencycase",
    "icu.change_emergencycase",
    "icu.view_codebluealert",
    "icu.add_codebluealert",
    "icu.resolve_codebluealert",
    "icu.view_handovernote",
    "icu.add_handovernote",
    "icu.change_handovernote",
]


def _client(*specs, username="icu-view-user") -> Client:
    client = Client()
    client.force_login(make_user(*specs, username=username))
    return client


def test_anonymous_redirects_to_login():
    response = Client().get(reverse("icu:record_list"))
    assert response.status_code == 302
    assert "login" in response.url


def test_missing_permission_is_denied():
    response = _client("icu.view_emergencycase", username="none").get(
        reverse("icu:record_list")
    )
    assert response.status_code == 403


def test_record_list_renders():
    make_icu_record()
    response = _client(*_ICU_VIEW, username="rl").get(reverse("icu:record_list"))
    assert response.status_code == 200


def test_emergency_queue_renders_open_cases():
    case = make_emergency_case()
    response = _client(*_ALL, username="eq").get(reverse("icu:emergency_list"))
    assert response.status_code == 200
    assert case.case_no.encode() in response.content


def test_register_emergency_case_creates_patient_and_case():
    response = _client(*_ALL, username="reg").post(
        reverse("icu:emergency_register"),
        {
            "full_name_en": "ER Walk-in",
            "phone": "01611111111",
            "gender": "male",
            "age_years": 25,
            "complaint": "Fever",
            "triage_level": "green",
        },
    )
    assert response.status_code == 302
    assert EmergencyCase.objects.count() == 1


def test_emergency_triage_update():
    case = make_emergency_case()
    response = _client(*_ALL, username="tri").post(
        reverse("icu:emergency_triage", args=[case.pk]), {"triage_level": "red"}
    )
    assert response.status_code == 302
    case.refresh_from_db()
    assert case.triage_level == "red"


def test_convert_to_admission_view():
    case = make_emergency_case()
    doctor = make_doctor()
    response = _client(*_ALL, username="conv").post(
        reverse("icu:emergency_convert", args=[case.pk]),
        {"doctor": doctor.pk, "reason": "Needs admission"},
    )
    assert response.status_code == 302
    case.refresh_from_db()
    assert case.converted_admission_id is not None


def test_alert_list_and_acknowledge():
    admission = make_admission()
    services.create_icu_record(admission=admission, data={"spo2": 80})
    alert = CriticalAlert.objects.get(admission=admission)
    client = _client(*_ALL, username="al")
    assert client.get(reverse("icu:alert_list")).status_code == 200
    response = client.post(reverse("icu:alert_acknowledge", args=[alert.pk]))
    assert response.status_code == 302
    alert.refresh_from_db()
    assert alert.status == "acknowledged"


def test_code_blue_raise_view():
    response = _client(*_ALL, username="cb").post(
        reverse("icu:code_blue_raise"), {"location": "Ward 4"}
    )
    assert response.status_code == 302
    assert selectors.code_blues(status="active").count() == 1


def test_handover_create_view():
    response = _client(*_ALL, username="ho").post(
        reverse("icu:handover_create"),
        {"unit": "icu", "shift": "night", "summary": "Stable", "pending_tasks": ""},
    )
    assert response.status_code == 302
    assert HandoverNote.objects.count() == 1


def test_icu_record_create_view():
    admission = make_admission()
    response = _client(*_ALL, username="rec").post(
        reverse("icu:record_create", args=[admission.pk]),
        {"recorded_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "pulse": 88},
    )
    assert response.status_code == 302
    assert admission.icu_records.count() == 1
