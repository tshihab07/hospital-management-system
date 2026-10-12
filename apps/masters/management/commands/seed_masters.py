"""Seed baseline master data so a fresh install is immediately usable.

Usage::

    python manage.py seed_masters

Idempotent: records are matched on their natural key and only created when
missing, so re-running never duplicates data.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.masters.models import (Bed, BedStatus, BedType, Department,
                                 DepartmentType, Designation,
                                 DesignationCategory, Diagnosis, Drug,
                                 DrugForm, HospitalProfile, LabTest,
                                 NotificationChannel, NotificationTemplate,
                                 PaymentKind, PaymentMethod, Procedure,
                                 RadiologyModality, RadiologyTest, TaxCategory,
                                 TaxConfig, Ward, WardType)

DEPARTMENTS = [
    ("Outpatient Department", "OPD", DepartmentType.OPD),
    ("Inpatient Department", "IPD", DepartmentType.IPD),
    ("Intensive Care Unit", "ICU", DepartmentType.ICU),
    ("Operation Theatre", "OT", DepartmentType.OT),
    ("Laboratory", "LAB", DepartmentType.LAB),
    ("Radiology & Imaging", "RAD", DepartmentType.RADIOLOGY),
    ("Pharmacy", "PHR", DepartmentType.PHARMACY),
    ("Emergency", "EMR", DepartmentType.EMERGENCY),
    ("Administration", "ADM", DepartmentType.ADMIN),
]

DESIGNATIONS = [
    ("Consultant", "CONS", DesignationCategory.CLINICAL),
    ("Medical Officer", "MO", DesignationCategory.CLINICAL),
    ("Staff Nurse", "SN", DesignationCategory.NURSING),
    ("Senior Staff Nurse", "SSN", DesignationCategory.NURSING),
    ("Lab Technician", "LT", DesignationCategory.TECHNICAL),
    ("Radiology Technician", "RT", DesignationCategory.TECHNICAL),
    ("Pharmacist", "PHRM", DesignationCategory.TECHNICAL),
    ("Receptionist", "RECP", DesignationCategory.ADMIN),
    ("Accountant", "ACC", DesignationCategory.ADMIN),
    ("Ward Attendant", "WA", DesignationCategory.SUPPORT),
]

WARD_TYPES = {
    "general": WardType.GENERAL,
    "cabin": WardType.CABIN,
    "icu": WardType.ICU,
}

BED_TYPES = [
    ("General Bed", 800),
    ("Cabin (Single)", 3500),
    ("Cabin (Deluxe)", 6000),
    ("ICU Bed", 5000),
    ("HDU Bed", 3000),
]

DRUGS = [
    ("Paracetamol", "Napa", DrugForm.TABLET, "500 mg", "pcs", 1.20),
    ("Paracetamol", "Napa", DrugForm.SYRUP, "120 mg/5 ml", "bottle", 85.00),
    ("Amoxicillin", "Moxacil", DrugForm.CAPSULE, "500 mg", "pcs", 12.00),
    ("Azithromycin", "Zimax", DrugForm.TABLET, "500 mg", "pcs", 35.00),
    ("Omeprazole", "Seclo", DrugForm.CAPSULE, "20 mg", "pcs", 7.00),
    ("Ceftriaxone", "Ceftron", DrugForm.INJECTION, "1 gm", "vial", 220.00),
    ("Metformin", "Glucomin", DrugForm.TABLET, "500 mg", "pcs", 3.50),
    ("Amlodipine", "Camlodin", DrugForm.TABLET, "5 mg", "pcs", 3.00),
    ("Salbutamol", "Sultolin", DrugForm.INHALER, "100 mcg", "pcs", 380.00),
    ("Normal Saline", "NS", DrugForm.INFUSION, "500 ml", "bag", 95.00),
]

LAB_TESTS = [
    ("CBC001", "Complete Blood Count", "Hematology", 500),
    ("CBC002", "Blood Sugar (Fasting)", "Biochemistry", 150),
    ("CBC003", "Blood Sugar (Random)", "Biochemistry", 150),
    ("CBC004", "Serum Creatinine", "Biochemistry", 400),
    ("CBC005", "Lipid Profile", "Biochemistry", 1500),
    ("CBC006", "Urine R/E", "Pathology", 250),
    ("CBC007", "S. TSH", "Hormone", 900),
    ("CBC008", "Liver Function Test", "Biochemistry", 1800),
]

RADIOLOGY = [
    ("RX001", "Chest X-Ray P/A", RadiologyModality.XRAY, 600),
    ("RX002", "X-Ray of Limb", RadiologyModality.XRAY, 700),
    ("US001", "Ultrasonography (Whole Abdomen)", RadiologyModality.USG, 1200),
    ("CT001", "CT Scan - Brain (Plain)", RadiologyModality.CT, 4500),
    ("MRI001", "MRI - Brain", RadiologyModality.MRI, 9000),
]

PROCEDURES = [
    ("PRC001", "Wound Dressing", "Minor", 500),
    ("PRC002", "Abscess Drainage", "Minor", 2500),
    ("PRC003", "Appendectomy", "Major", 30000),
    ("PRC004", "Caesarean Section", "Major", 45000),
    ("PRC005", "Endoscopy (Upper GI)", "Endoscopy", 6000),
]

DIAGNOSES = [
    ("A09", "Infectious gastroenteritis and colitis", "Digestive system"),
    ("E11", "Type 2 diabetes mellitus", "Endocrine"),
    ("I10", "Essential (primary) hypertension", "Circulatory system"),
    ("J06", "Acute upper respiratory infections", "Respiratory system"),
    ("J18", "Pneumonia, organism unspecified", "Respiratory system"),
    ("N39.0", "Urinary tract infection", "Genitourinary system"),
    ("K35", "Acute appendicitis", "Digestive system"),
    ("M54.5", "Low back pain", "Musculoskeletal system"),
    ("O80", "Encounter for full-term uncomplicated delivery", "Pregnancy"),
    ("R50.9", "Fever, unspecified", "General symptoms"),
]

TAXES = [
    ("VAT 5%", TaxCategory.VAT, 5),
    ("VAT 15%", TaxCategory.VAT, 15),
    ("AIT 5%", TaxCategory.AIT, 5),
    ("Service Charge 10%", TaxCategory.SERVICE_CHARGE, 10),
]

PAYMENTS = [
    ("Cash", "CASH", PaymentKind.CASH, 0),
    ("Debit / Credit Card", "CARD", PaymentKind.CARD, 1.5),
    ("bKash", "BKASH", PaymentKind.MOBILE, 1.85),
    ("Nagad", "NAGAD", PaymentKind.MOBILE, 1.5),
    ("Bank Transfer", "BANK", PaymentKind.BANK, 0),
]

NOTIFICATIONS = [
    (
        "Appointment Reminder",
        "APPT_REMINDER",
        NotificationChannel.SMS,
        "Appointment Reminder",
        "অ্যাপয়েন্টমেন্ট রিমাইন্ডার",
        "Dear {patient}, your appointment with {doctor} is on {date} at {time}.",
        "প্রিয় {patient}, আপনার {doctor} এর সাথে অ্যাপয়েন্টমেন্ট {date} তারিখে {time} টায়।",
    ),
    (
        "Admission Confirmation",
        "ADMISSION_CONFIRM",
        NotificationChannel.SMS,
        "Admission Confirmation",
        "ভর্তি নিশ্চিতকরণ",
        "Dear {patient}, you have been admitted to {ward}. IP No: {ip_no}.",
        "প্রিয় {patient}, আপনাকে {ward} ওয়ার্ডে ভর্তি করা হয়েছে। আইপি নং: {ip_no}।",
    ),
]


class Command(BaseCommand):
    help = "Seed baseline master data (departments, drugs, tests, taxes, etc.)."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        counts = {
            "departments": 0,
            "designations": 0,
            "wards": 0,
            "bed_types": 0,
            "beds": 0,
            "drugs": 0,
            "lab_tests": 0,
            "radiology": 0,
            "procedures": 0,
            "diagnoses": 0,
            "taxes": 0,
            "payments": 0,
            "notifications": 0,
        }

        def bump(key, created):
            if created:
                counts[key] += 1

        for name, code, dtype in DEPARTMENTS:
            _, created = Department.objects.get_or_create(
                code=code, defaults={"name": name, "type": dtype}
            )
            bump("departments", created)

        for name, code, cat in DESIGNATIONS:
            _, created = Designation.objects.get_or_create(
                code=code, defaults={"name": name, "category": cat}
            )
            bump("designations", created)

        bed_type_objs = {}
        for name, rate in BED_TYPES:
            obj, created = BedType.objects.get_or_create(
                name=name, defaults={"daily_rate": rate}
            )
            bed_type_objs[name] = obj
            bump("bed_types", created)

        opd = Department.objects.filter(code="OPD").first()
        icu_dept = Department.objects.filter(code="ICU").first()
        ward_specs = [
            ("General Ward", "WARD-GEN", WardType.GENERAL, 1, opd, "General Bed", 10),
            ("Cabin Block", "WARD-CAB", WardType.CABIN, 2, opd, "Cabin (Single)", 5),
            ("ICU", "WARD-ICU", WardType.ICU, 3, icu_dept, "ICU Bed", 4),
        ]
        for name, code, wtype, floor, dept, bed_type_name, bed_count in ward_specs:
            ward, created = Ward.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "type": wtype,
                    "floor": floor,
                    "department": dept,
                },
            )
            bump("wards", created)
            for i in range(1, bed_count + 1):
                _, bed_created = Bed.objects.get_or_create(
                    ward=ward,
                    bed_no=f"{code[-3:]}-{i:02d}",
                    defaults={
                        "bed_type": bed_type_objs[bed_type_name],
                        "status": BedStatus.AVAILABLE,
                    },
                )
                bump("beds", bed_created)

        for generic, brand, form, strength, unit, price in DRUGS:
            _, created = Drug.objects.get_or_create(
                generic_name=generic,
                brand_name=brand,
                form=form,
                strength=strength,
                defaults={"unit": unit, "unit_price": price, "reorder_level": 20},
            )
            bump("drugs", created)

        for code, name, category, price in LAB_TESTS:
            _, created = LabTest.objects.get_or_create(
                code=code, defaults={"name": name, "category": category, "price": price}
            )
            bump("lab_tests", created)

        for code, name, modality, price in RADIOLOGY:
            _, created = RadiologyTest.objects.get_or_create(
                code=code,
                defaults={"name": name, "modality": modality, "price": price},
            )
            bump("radiology", created)

        for code, name, category, price in PROCEDURES:
            _, created = Procedure.objects.get_or_create(
                code=code, defaults={"name": name, "category": category, "price": price}
            )
            bump("procedures", created)

        for code, name, category in DIAGNOSES:
            _, created = Diagnosis.objects.get_or_create(
                code=code, defaults={"name": name, "category": category}
            )
            bump("diagnoses", created)

        for name, category, rate in TAXES:
            _, created = TaxConfig.objects.get_or_create(
                name=name, defaults={"category": category, "rate": rate}
            )
            bump("taxes", created)

        for name, code, kind, charge in PAYMENTS:
            _, created = PaymentMethod.objects.get_or_create(
                code=code, defaults={"name": name, "kind": kind, "charge_pct": charge}
            )
            bump("payments", created)

        for (
            name,
            code,
            channel,
            sub_en,
            sub_bn,
            body_en,
            body_bn,
        ) in NOTIFICATIONS:
            _, created = NotificationTemplate.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "channel": channel,
                    "subject_en": sub_en,
                    "subject_bn": sub_bn,
                    "body_en": body_en,
                    "body_bn": body_bn,
                },
            )
            bump("notifications", created)

        profile, profile_created = HospitalProfile.objects.get_or_create(
            name_en="Model Hospital",
            defaults={
                "name_bn": "মডেল হাসপাতাল",
                "address": "123 Health Avenue",
                "city": "Dhaka",
                "postcode": "1200",
                "phone": "+8801700000000",
                "email": "info@example.com",
                "uhid_prefix": "DHK",
                "ip_prefix": "IP",
            },
        )

        summary = ", ".join(f"{k}={v}" for k, v in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Master data seeded ({summary})."))
        if profile_created:
            self.stdout.write(f"Hospital profile created: {profile}")
