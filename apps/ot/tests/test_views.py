"""View / access-control tests for the Operation Theatre module."""

from __future__ import annotations

from datetime import date, time

import pytest
from django.test import Client
from django.urls import reverse

from apps.ot import services
from apps.ot.models import PreOpChecklist, Surgery, SurgeryStatus

from .factories import (make_doctor, make_patient, make_room, make_surgery,
                        make_user)

pytestmark = pytest.mark.django_db

_VIEW = ["ot.view_surgery"]
_ALL = [
    "ot.view_otroom",
    "ot.add_otroom",
    "ot.view_surgery",
    "ot.add_surgery",
    "ot.change_surgery",
    "ot.schedule_surgery",
    "ot.cancel_surgery",
    "ot.view_surgicalteammember",
    "ot.add_surgicalteammember",
    "ot.view_preopchecklist",
    "ot.add_preopchecklist",
    "ot.change_preopchecklist",
    "ot.view_anesthesiarecord",
    "ot.add_anesthesiarecord",
    "ot.view_intraopnote",
    "ot.add_intraopnote",
    "ot.view_postopnote",
    "ot.add_postopnote",
    "ot.view_implant",
    "ot.add_implant",
    "ot.view_surgeryconsumable",
    "ot.add_surgeryconsumable",
]


def _client(*specs, username="ot-view-user") -> Client:
    client = Client()
    client.force_login(make_user(*specs, username=username))
    return client


def test_anonymous_redirects_to_login():
    response = Client().get(reverse("ot:surgery_list"))
    assert response.status_code == 302
    assert "login" in response.url


def test_missing_permission_is_denied():
    response = _client("ot.view_otroom", username="none").get(
        reverse("ot:surgery_list")
    )
    assert response.status_code == 403


def test_surgery_list_renders():
    make_surgery()
    response = _client(*_VIEW, username="rl").get(reverse("ot:surgery_list"))
    assert response.status_code == 200


def test_schedule_surgery_via_view_creates_record():
    patient = make_patient()
    surgeon = make_doctor()
    room = make_room()
    response = _client(*_ALL, username="sched").post(
        reverse("ot:surgery_create"),
        {
            "patient": patient.pk,
            "surgeon": surgeon.pk,
            "ot_room": room.pk,
            "scheduled_date": "2026-06-10",
            "start_time": "09:00",
            "end_time": "10:00",
            "procedure_name": "Hernia repair",
            "priority": "elective",
            "diagnosis": "",
            "notes": "",
        },
    )
    assert response.status_code == 302
    assert Surgery.objects.filter(procedure_name="Hernia repair").exists()


def test_schedule_conflict_re_renders_with_error():
    room = make_room()
    make_surgery(
        room=room,
        scheduled_date=date(2026, 6, 10),
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    response = _client(*_ALL, username="clash").post(
        reverse("ot:surgery_create"),
        {
            "patient": make_patient().pk,
            "surgeon": make_doctor().pk,
            "ot_room": room.pk,
            "scheduled_date": "2026-06-10",
            "start_time": "09:30",
            "end_time": "10:30",
            "procedure_name": "Clash",
            "priority": "elective",
            "diagnosis": "",
            "notes": "",
        },
    )
    assert response.status_code == 200
    assert not Surgery.objects.filter(procedure_name="Clash").exists()


def test_surgery_detail_renders():
    surgery = make_surgery()
    response = _client(*_ALL, username="det").get(
        reverse("ot:surgery_detail", args=[surgery.pk])
    )
    assert response.status_code == 200
    assert surgery.surgery_no.encode() in response.content


def test_calendar_and_utilization_render():
    make_surgery(scheduled_date=date(2026, 6, 1))
    client = _client(*_VIEW, username="cal")
    assert client.get(reverse("ot:calendar")).status_code == 200
    assert client.get(reverse("ot:utilization")).status_code == 200


def test_preop_checklist_saved_via_view():
    surgery = make_surgery()
    data = {item: "on" for item in PreOpChecklist.ITEMS}
    response = _client(*_ALL, username="chk").post(
        reverse("ot:preop_checklist", args=[surgery.pk]), data
    )
    assert response.status_code == 302
    surgery.refresh_from_db()
    assert surgery.preop_checklist.is_complete


def test_start_action_blocked_without_checklist():
    surgery = make_surgery()
    response = _client(*_ALL, username="start1").post(
        reverse("ot:surgery_action", args=[surgery.pk, "start"])
    )
    assert response.status_code == 302
    surgery.refresh_from_db()
    assert surgery.status == SurgeryStatus.SCHEDULED


def test_start_action_succeeds_after_checklist():
    surgery = make_surgery()
    services.save_preop_checklist(
        surgery=surgery, data={item: True for item in PreOpChecklist.ITEMS}
    )
    _client(*_ALL, username="start2").post(
        reverse("ot:surgery_action", args=[surgery.pk, "start"])
    )
    surgery.refresh_from_db()
    assert surgery.status == SurgeryStatus.IN_PROGRESS


def test_cancel_action_sets_cancelled():
    surgery = make_surgery()
    _client(*_ALL, username="canc").post(
        reverse("ot:surgery_cancel", args=[surgery.pk]), {"reason": "N/A"}
    )
    surgery.refresh_from_db()
    assert surgery.status == SurgeryStatus.CANCELLED


def test_implant_add_via_view():
    surgery = make_surgery()
    response = _client(*_ALL, username="imp").post(
        reverse("ot:implant_add", args=[surgery.pk]),
        {"name": "Plate", "quantity": 1, "unit_price": "500.00", "status": "consumed"},
    )
    assert response.status_code == 302
    assert surgery.implants.count() == 1


def test_team_add_via_view():
    surgery = make_surgery()
    response = _client(*_ALL, username="team").post(
        reverse("ot:team_add", args=[surgery.pk]),
        {"role": "assistant", "doctor": make_doctor().pk},
    )
    assert response.status_code == 302
    assert surgery.team.count() == 1


def test_room_list_and_create():
    client = _client(*_ALL, username="rooms")
    assert client.get(reverse("ot:room_list")).status_code == 200
    response = client.post(
        reverse("ot:room_create"),
        {
            "name": "New OT",
            "room_no": "N1",
            "room_type": "minor",
            "status": "available",
        },
    )
    assert response.status_code == 302
