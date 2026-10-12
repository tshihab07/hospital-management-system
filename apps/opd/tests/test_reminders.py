"""Email reminder tests (Phase 4 uses email instead of SMS)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from apps.opd import services
from apps.opd.models import Appointment, AvailabilitySlot, Doctor
from apps.patients import services as patient_services

pytestmark = pytest.mark.django_db


def _doctor(**overrides) -> Doctor:
    data = {"name_en": "Dr. Reminder", "specialization": "Medicine"}
    data.update(overrides)
    return Doctor.objects.create(**data)


def _patient(**overrides):
    data = {
        "full_name_en": "Reminder Patient",
        "gender": "female",
        "date_of_birth": dt.date(1990, 1, 1),
        "phone": "01700000000",
        "email": "reminder@example.com",
    }
    data.update(overrides)
    return patient_services.register_patient(data=data)


def _slot(doctor, weekday, start=dt.time(9, 0), end=dt.time(13, 0)):
    return AvailabilitySlot.objects.create(
        doctor=doctor,
        weekday=weekday,
        start_time=start,
        end_time=end,
        max_patients=10,
    )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_booking_sends_confirmation_email():
    doctor = _doctor()
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    slot = _slot(doctor, tomorrow.weekday())
    services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=tomorrow, slot=slot
    )
    assert len(mail.outbox) == 1
    assert "Reminder Patient" in mail.outbox[0].body
    assert mail.outbox[0].to == ["reminder@example.com"]


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_24h_reminder_sent_once():
    doctor = _doctor()
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    slot = _slot(doctor, tomorrow.weekday())
    appointment = services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=tomorrow, slot=slot
    )
    mail.outbox.clear()

    stats = services.send_reminders()
    assert stats["24h_sent"] == 1
    assert len(mail.outbox) == 1

    appointment.refresh_from_db()
    assert appointment.reminder_24h_sent is True

    mail.outbox.clear()
    assert services.send_reminders()["24h_sent"] == 0
    assert len(mail.outbox) == 0


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
@freeze_time("2026-06-15 10:00:00+06:00")
def test_1h_reminder_within_window():
    doctor = _doctor()
    today = timezone.localdate()
    now = timezone.localtime()
    start = (now + dt.timedelta(minutes=30)).time().replace(second=0, microsecond=0)
    end = (now + dt.timedelta(hours=2)).time().replace(second=0, microsecond=0)
    slot = _slot(doctor, today.weekday(), start=start, end=end)
    appointment = services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=today, slot=slot
    )
    mail.outbox.clear()

    stats = services.send_reminders()
    assert stats["1h_sent"] == 1
    appointment.refresh_from_db()
    assert appointment.reminder_1h_sent is True


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_dry_run_sends_nothing():
    doctor = _doctor()
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    slot = _slot(doctor, tomorrow.weekday())
    services.book_appointment(
        patient=_patient(), doctor=doctor, appt_date=tomorrow, slot=slot
    )
    mail.outbox.clear()
    stats = services.send_reminders(dry_run=True)
    assert stats["24h_sent"] == 1
    assert len(mail.outbox) == 0
    assert Appointment.objects.filter(reminder_24h_sent=True).count() == 0
