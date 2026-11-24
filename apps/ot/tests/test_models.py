"""Model-level tests for the Operation Theatre module."""

from __future__ import annotations

from datetime import date, time

import pytest

from apps.ot.models import Implant, OTRoom, SurgicalTeamMember

from .factories import make_doctor, make_patient, make_surgery

pytestmark = pytest.mark.django_db


def test_room_str_includes_room_no():
    room = OTRoom.objects.create(name="OT-9", room_no="R9")
    assert "OT-9" in str(room)
    assert "R9" in str(room)


def test_surgery_duration_minutes():
    surgery = make_surgery(
        scheduled_date=date(2026, 6, 1),
        start_time=time(9, 15),
        end_time=time(11, 0),
    )
    assert surgery.duration_minutes == 105


def test_surgery_is_today_flag():
    from django.utils import timezone

    surgery = make_surgery(scheduled_date=timezone.localdate())
    assert surgery.is_today


def test_implant_total_multiplies_quantity():
    patient = make_patient()
    implant = Implant.objects.create(
        patient=patient, name="Screw", quantity=4, unit_price="250.00"
    )
    assert float(implant.total) == pytest.approx(1000.0)


def test_team_member_display_name_prefers_doctor():
    surgery = make_surgery()
    member = SurgicalTeamMember.objects.create(
        surgery=surgery, role="surgeon", doctor=make_doctor(name_en="Dr. Lead")
    )
    assert member.display_name == "Dr. Lead"
