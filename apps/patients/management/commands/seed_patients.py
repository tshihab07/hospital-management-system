"""Seed a few sample patients for local development and demos.

Usage::

    python manage.py seed_patients

Idempotent: patients are matched on phone + full name and skipped when they
already exist. UHIDs are allocated through the real service so the sequence
stays consistent.
"""

from __future__ import annotations

import datetime as dt

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.patients import services
from apps.patients.models import (BloodGroup, Gender, MaritalStatus, Patient,
                                  PatientType)

SAMPLE_PATIENTS = [
    {
        "full_name_en": "Abdul Karim",
        "full_name_bn": "আব্দুল করিম",
        "date_of_birth": dt.date(1985, 4, 12),
        "gender": Gender.MALE,
        "blood_group": BloodGroup.O_POS,
        "marital_status": MaritalStatus.MARRIED,
        "phone": "01711000001",
        "nid": "1990123456789",
        "address": "House 12, Road 5, Dhanmondi",
        "city": "Dhaka",
        "postcode": "1205",
        "guardian_name": "Rahima Begum",
        "guardian_relation": "mother",
        "emergency_contact_name": "Rahima Begum",
        "emergency_contact_relation": "mother",
        "emergency_contact_phone": "01711000011",
        "patient_type": PatientType.GENERAL,
        "occupation": "Teacher",
    },
    {
        "full_name_en": "Fatema Akter",
        "full_name_bn": "ফাতেমা আক্তার",
        "date_of_birth": dt.date(1992, 9, 3),
        "gender": Gender.FEMALE,
        "blood_group": BloodGroup.B_POS,
        "marital_status": MaritalStatus.SINGLE,
        "phone": "01711000002",
        "nid": "1992777888999",
        "address": "Flat 3B, Green Road",
        "city": "Dhaka",
        "postcode": "1205",
        "patient_type": PatientType.CORPORATE,
        "occupation": "Engineer",
    },
    {
        "full_name_en": "Md. Rafiqul Islam",
        "date_of_birth": dt.date(1978, 1, 20),
        "gender": Gender.MALE,
        "blood_group": BloodGroup.A_POS,
        "marital_status": MaritalStatus.MARRIED,
        "phone": "01711000003",
        "address": "Station Road, Cumilla",
        "city": "Cumilla",
        "patient_type": PatientType.VIP,
        "occupation": "Businessman",
    },
    {
        "full_name_en": "Sadia Rahman",
        "date_of_birth": dt.date(2001, 6, 15),
        "gender": Gender.FEMALE,
        "blood_group": BloodGroup.AB_POS,
        "marital_status": MaritalStatus.SINGLE,
        "phone": "01711000004",
        "address": "Uttara Sector 7",
        "city": "Dhaka",
        "patient_type": PatientType.STAFF,
        "occupation": "Nurse",
    },
]


class Command(BaseCommand):
    help = "Seed sample patients."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        created = 0
        for spec in SAMPLE_PATIENTS:
            exists = Patient.objects.filter(
                phone=spec["phone"], full_name_en=spec["full_name_en"]
            ).exists()
            if exists:
                continue
            services.register_patient(data=spec)
            created += 1

        self.stdout.write(
            self.style.SUCCESS(f"Sample patients seeded ({created} created).")
        )
