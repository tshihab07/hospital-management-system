"""Service-layer tests for the Operation Theatre module."""

from __future__ import annotations

from datetime import date, time

import pytest

from apps.ot import selectors, services
from apps.ot.models import (Implant, PreOpChecklist, Surgery,
                            SurgeryConsumable, SurgeryStatus)

from .factories import make_doctor, make_patient, make_room, make_surgery

pytestmark = pytest.mark.django_db


def test_schedule_surgery_assigns_number_and_defaults():
    surgery = make_surgery()
    year = date(2026, 6, 1).year
    assert surgery.surgery_no == f"OT-{year}-00001"
    assert surgery.status == SurgeryStatus.SCHEDULED
    assert surgery.is_active


def test_sequential_numbers_increment():
    room = make_room()
    first = make_surgery(room=room)
    second = make_surgery(room=room, scheduled_date=date(2026, 6, 2))
    assert first.surgery_no.endswith("00001")
    assert second.surgery_no.endswith("00002")


def test_overlapping_booking_same_room_is_rejected():
    room = make_room()
    make_surgery(room=room, start_time=time(9, 0), end_time=time(10, 0))
    with pytest.raises(ValueError):
        make_surgery(
            room=room,
            start_time=time(9, 30),
            end_time=time(10, 30),
            scheduled_date=date(2026, 6, 1),
        )


def test_adjacent_booking_is_allowed():
    room = make_room()
    make_surgery(room=room, start_time=time(9, 0), end_time=time(10, 0))
    second = make_surgery(room=room, start_time=time(10, 0), end_time=time(11, 0))
    assert second.pk is not None


def test_different_rooms_do_not_conflict():
    day = date(2026, 6, 1)
    make_surgery(room=make_room(), scheduled_date=day)
    second = make_surgery(room=make_room(), scheduled_date=day)
    assert second.pk is not None


def test_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        make_surgery(start_time=time(11, 0), end_time=time(10, 0))


def test_reschedule_conflict_is_rejected():
    day = date(2026, 6, 1)
    room = make_room()
    make_surgery(
        room=room, scheduled_date=day, start_time=time(9, 0), end_time=time(10, 0)
    )
    second = make_surgery(
        room=make_room(),
        scheduled_date=day,
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    with pytest.raises(ValueError):
        services.reschedule_surgery(
            surgery=second,
            scheduled_date=day,
            start_time=time(9, 30),
            end_time=time(10, 30),
            ot_room=room,
        )


def test_reschedule_moves_surgery():
    day = date(2026, 6, 1)
    surgery = make_surgery(scheduled_date=day)
    services.reschedule_surgery(
        surgery=surgery,
        scheduled_date=date(2026, 6, 2),
        start_time=time(14, 0),
        end_time=time(15, 0),
    )
    surgery.refresh_from_db()
    assert surgery.scheduled_date == date(2026, 6, 2)
    assert surgery.start_time == time(14, 0)


def test_cancel_surgery_sets_reason():
    surgery = make_surgery()
    services.cancel_surgery(surgery=surgery, reason="Patient unfit")
    surgery.refresh_from_db()
    assert surgery.status == SurgeryStatus.CANCELLED
    assert surgery.cancellation_reason == "Patient unfit"
    assert not surgery.is_active


def test_preop_checklist_completeness():
    surgery = make_surgery()
    checklist = services.save_preop_checklist(
        surgery=surgery, data={"consent_signed": True, "npo_confirmed": True}
    )
    assert not checklist.is_complete
    assert "site_marked" in checklist.missing_items
    full = {item: True for item in PreOpChecklist.ITEMS}
    checklist = services.save_preop_checklist(surgery=surgery, data=full)
    assert checklist.is_complete
    assert checklist.verified_at is not None


def test_start_surgery_requires_complete_checklist():
    surgery = make_surgery()
    with pytest.raises(ValueError):
        services.start_surgery(surgery=surgery)

    services.save_preop_checklist(
        surgery=surgery, data={item: True for item in PreOpChecklist.ITEMS}
    )
    surgery.refresh_from_db()
    services.start_surgery(surgery=surgery)
    surgery.refresh_from_db()
    assert surgery.status == SurgeryStatus.IN_PROGRESS
    assert surgery.started_at is not None


def test_complete_surgery():
    surgery = make_surgery()
    services.complete_surgery(surgery=surgery)
    surgery.refresh_from_db()
    assert surgery.status == SurgeryStatus.COMPLETED
    assert surgery.completed_at is not None


def test_record_anesthesia_and_notes():
    surgery = make_surgery()
    services.record_anesthesia(
        surgery=surgery, data={"anesthesia_type": "general", "asa_grade": 2}
    )
    services.record_intraop_note(
        surgery=surgery, data={"findings": "Inflamed appendix", "blood_loss_ml": 50}
    )
    services.record_postop_note(
        surgery=surgery, data={"condition": "stable", "pain_score": 3}
    )
    surgery.refresh_from_db()
    assert surgery.anesthesia.asa_grade == 2
    assert surgery.intraop_note.blood_loss_ml == 50
    assert surgery.postop_note.condition == "stable"


def test_record_implant_tracks_to_patient():
    patient = make_patient()
    surgery = make_surgery(patient=patient)
    implant = services.record_implant(
        surgery=surgery,
        data={"name": "Titanium plate", "serial_no": "SN-1", "unit_price": "1500.00"},
    )
    assert implant.patient == patient
    assert implant.surgery == surgery
    assert implant.total == 1500
    assert Implant.objects.filter(patient=patient).count() == 1


def test_record_consumable_totals():
    surgery = make_surgery()
    consumable = services.record_consumable(
        surgery=surgery, data={"item": "Suture", "quantity": 3, "unit_price": "120.50"}
    )
    assert SurgeryConsumable.objects.filter(surgery=surgery).count() == 1
    assert float(consumable.total) == pytest.approx(361.50)


def test_add_team_member():
    surgery = make_surgery()
    member = services.add_team_member(
        surgery=surgery, role="assistant", doctor=make_doctor()
    )
    assert member.display_name


def test_utilization_report_computes_minutes():
    room = make_room()
    day = date(2026, 6, 1)
    make_surgery(
        room=room, scheduled_date=day, start_time=time(9, 0), end_time=time(11, 0)
    )
    report = selectors.utilization_report(start=day, end=day)
    row = next(r for r in report["rows"] if r["room"].pk == room.pk)
    assert row["surgery_count"] == 1
    assert row["used_minutes"] == 120
    assert report["total_surgeries"] == 1


def test_week_calendar_rows_include_cells():
    room = make_room()
    day = date(2026, 6, 1)  # Monday
    make_surgery(room=room, scheduled_date=day)
    calendar = selectors.week_calendar(week_start=day)
    row = next(r for r in calendar["rows"] if r["room"].pk == room.pk)
    day_cell = next(c for c in row["cells"] if c["day"] == day)
    assert len(day_cell["surgeries"]) == 1


def test_surgery_soft_delete_keeps_record():
    surgery = make_surgery()
    pk = surgery.pk
    surgery.delete()
    assert not Surgery.objects.filter(pk=pk).exists()
    assert Surgery.all_objects.filter(pk=pk).exists()
