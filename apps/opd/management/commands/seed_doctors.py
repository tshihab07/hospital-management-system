"""Seed sample doctors, weekly availability and today's appointments."""

from __future__ import annotations

from datetime import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.masters.models import Department
from apps.opd import services
from apps.opd.models import Appointment, AvailabilitySlot, Doctor
from apps.patients.models import Patient

DOCTORS = [
    {
        "name_en": "Dr. Ayesha Rahman",
        "name_bn": "ডাঃ আইশা রহমান",
        "specialization": "Cardiology",
        "qualification": "MBBS, FCPS (Cardiology)",
        "bmdc_no": "A-10001",
        "phone": "01711000001",
        "email": "ayesha@example.com",
        "consultation_fee": "1000.00",
        "followup_fee": "500.00",
    },
    {
        "name_en": "Dr. Kamal Hossain",
        "name_bn": "ডাঃ কামাল হোসেন",
        "specialization": "Medicine",
        "qualification": "MBBS, MD (Internal Medicine)",
        "bmdc_no": "A-10002",
        "phone": "01711000002",
        "email": "kamal@example.com",
        "consultation_fee": "800.00",
        "followup_fee": "400.00",
    },
    {
        "name_en": "Dr. Nusrat Jahan",
        "name_bn": "ডাঃ নুসরাত জাহান",
        "specialization": "Gynaecology & Obstetrics",
        "qualification": "MBBS, FCPS (Gynae)",
        "bmdc_no": "A-10003",
        "phone": "01711000003",
        "email": "nusrat@example.com",
        "consultation_fee": "900.00",
        "followup_fee": "450.00",
    },
]

BLOCKS = [
    (time(9, 0), time(13, 0), 20),
    (time(17, 0), time(21, 0), 15),
]


class Command(BaseCommand):
    help = "Seed sample doctors with availability and today's appointments."

    def handle(self, *args, **options):
        department = Department.objects.filter(is_active=True).first()
        created = 0
        doctors = []
        for spec in DOCTORS:
            doctor, was_created = Doctor.objects.get_or_create(
                bmdc_no=spec["bmdc_no"],
                defaults={**spec, "department": department, "is_active": True},
            )
            if was_created:
                created += 1
            doctors.append(doctor)
            self._ensure_availability(doctor)
        self.stdout.write(
            self.style.SUCCESS(
                f"Doctors seeded ({created} created, {len(doctors)} total)."
            )
        )

        self._seed_appointments(doctors)

    def _ensure_availability(self, doctor: Doctor) -> None:
        for weekday in range(7):
            for start, end, cap in BLOCKS:
                AvailabilitySlot.objects.get_or_create(
                    doctor=doctor,
                    weekday=weekday,
                    start_time=start,
                    defaults={"end_time": end, "max_patients": cap, "is_active": True},
                )

    def _seed_appointments(self, doctors) -> None:
        today = timezone.localdate()
        if Appointment.objects.filter(appt_date=today).exists():
            self.stdout.write("Appointments already exist for today – skipped.")
            return
        patients = list(Patient.objects.filter(is_deleted=False).order_by("pk")[:3])
        if not patients:
            self.stdout.write("No patients available – skipped appointment seeding.")
            return
        made = 0
        for index, patient in enumerate(patients):
            doctor = doctors[index % len(doctors)]
            block = (
                AvailabilitySlot.objects.filter(
                    doctor=doctor, weekday=today.weekday(), is_active=True
                )
                .order_by("start_time")
                .first()
            )
            visit_type = "new" if index % 2 == 0 else "followup"
            try:
                services.book_appointment(
                    patient=patient,
                    doctor=doctor,
                    appt_date=today,
                    slot=block,
                    visit_type=visit_type,
                    notes="Seeded sample appointment",
                )
                made += 1
            except ValueError as exc:  # pragma: no cover - defensive
                self.stderr.write(f"Skipped one appointment: {exc}")
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {made} appointment(s) for today.")
        )
