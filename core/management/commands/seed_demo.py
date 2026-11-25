"""Seed an end-to-end demo dataset across every IHMS module.

The dataset tells one coherent story for two patients — an OPD-to-IPD
pneumonia admission discharged with a clean bill, and an emergency
appendectomy admission that is still running with a partial portal payment.
Every clinical event is backed by the matching bill, payment, stock movement
and accounting journal so the control-tower reports reconcile.

Idempotent: a marker on ``Admission.admission_note`` short-circuits a second
run (and refuses to overwrite a half-seeded database).
"""

from __future__ import annotations

import calendar
import datetime as dt
import io
from datetime import time
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounting import services as accounting
from apps.accounting.models import JournalEntry, SystemAccount
from apps.accounting.selectors import trial_balance
from apps.accounts.models import Role, User
from apps.billing import services as billing
from apps.billing.models import (
    Advance,
    Bill,
    BillItemType,
    BillStatus,
    MoneyReceipt,
    Payment,
    PaymentMode,
    ServicePackage,
)
from apps.emr import services as emr
from apps.emr.models import (
    AllergySeverity,
    AllergyType,
    AttachmentCategory,
    EncounterType,
    OrderPriority,
    OrderStatus,
    Route,
)
from apps.hr import services as hr
from apps.hr.models import AttendanceStatus, LeaveType, Staff, StaffStatus
from apps.icu import services as icu
from apps.icu.models import EmergencyStatus, ScoreType, TriageLevel, Unit, UnitShift
from apps.ipd import services as ipd
from apps.ipd.models import (
    Admission,
    AdmissionType,
    Bed,
    BedStatus,
    ClearanceDepartment,
    DischargeSummary,
    DischargeType,
    FluidCategory,
    FluidType,
    MarAction,
    NursingShift,
)
from apps.lab import services as lab
from apps.lab.models import LabSample, RadiologyRecord
from apps.masters.models import (
    Department,
    Designation,
    Diagnosis,
    Drug,
    LabTest,
    Procedure,
    RadiologyTest,
)
from apps.opd.models import (
    Appointment,
    AppointmentStatus,
    AppointmentType,
    AvailabilitySlot,
    Doctor,
)
from apps.ot import services as ot
from apps.ot.models import AnesthesiaType, OTRoom, PatientCondition, Surgery, TeamRole
from apps.patients import services as patients
from apps.patients.models import DocumentCategory, Patient
from apps.payroll import services as payroll
from apps.payroll.models import AdjustmentKind
from apps.pharmacy import services as pharmacy
from apps.pharmacy.models import DispenseRecord, PharmacyStore, PurchaseOrder, Vendor
from apps.portal import services as portal
from apps.portal.models import MedicalRecordRequest, MedicalRecordRequestStatus
from apps.reports import services as reports
from apps.reports.models import (
    ReportFormat,
    ReportFrequency,
    ReportSchedule,
    ReportType,
)

MARKER = "DEMO-FLOW"
PASSWORD = "Demo@12345"


class Command(BaseCommand):
    help = "Seed a realistic, flow-consistent demo dataset (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        seeded = Admission.objects.filter(admission_note__contains=MARKER).count()
        if seeded >= 2:
            self.stdout.write(
                self.style.WARNING("Demo data already present — nothing to do.")
            )
            return
        if seeded:
            raise CommandError(
                "A partial demo seed was detected. Remove the DEMO-FLOW "
                "admissions (and dependent rows) before re-running."
            )

        self.today = timezone.localdate()
        self._seed_prereqs()
        self._tune_masters()
        self._ensure_hr()
        self._ensure_doctors()
        self._ensure_users()

        p1 = Patient.objects.filter(phone="01711000001").first()
        p2 = Patient.objects.filter(phone="01711000002").first()
        if p1 is None or p2 is None:
            raise CommandError("Run seed_patients first — demo patients missing.")

        self._seed_portal_accounts(p1, p2)
        self._seed_pharmacy_supply()
        self._seed_p1(p1)
        self._seed_p2(p2)
        self._seed_payroll()
        self._seed_reports()
        self._seed_documents(p1)

        self._print_summary(p1, p2)

    # ------------------------------------------------------------------
    # Prerequisites
    # ------------------------------------------------------------------
    def _seed_prereqs(self) -> None:
        sink = io.StringIO()
        for command in (
            "seed_masters",
            "seed_roles",
            "seed_chart_of_accounts",
            "seed_patients",
            "seed_payroll",
            "seed_ipd",
            "seed_icu",
            "seed_ot",
            "seed_pharmacy",
            "seed_emr",
            "seed_hr",
        ):
            call_command(command, stdout=sink, stderr=sink)

    def _tune_masters(self) -> None:
        LabTest.objects.filter(code="CBC001").update(
            unit="10^9/L", reference_range="4.0-11.0", sample_type="Whole blood (EDTA)"
        )
        LabTest.objects.filter(code="CBC003").update(
            unit="mg/dL", reference_range="70-140", sample_type="Blood (fluoride)"
        )
        LabTest.objects.filter(code="CBC004").update(
            unit="mg/dL", reference_range="0.6-1.2", sample_type="Serum"
        )
        ServicePackage.objects.get_or_create(
            code="PKG-DELIVERY",
            defaults={
                "name": "Normal Delivery Package",
                "description": "Three-day normal delivery package (demo catalogue).",
                "price": Decimal("60000"),
            },
        )
        ServicePackage.objects.get_or_create(
            code="PKG-APPENDECTOMY",
            defaults={
                "name": "Appendectomy Package",
                "description": "Open appendectomy package (demo catalogue).",
                "price": Decimal("55000"),
            },
        )

    # ------------------------------------------------------------------
    # People
    # ------------------------------------------------------------------
    def _ensure_hr(self) -> None:
        departments = {d.code: d for d in Department.objects.all()}
        specs = [
            (
                "EMP-1001",
                "Rahima Begum",
                "রহিমা বেগম",
                "IPD",
                "Senior Nurse",
                "25000",
                "nurse",
            ),
            (
                "EMP-1002",
                "Sabbir Ahmed",
                "সাব্বির আহমেদ",
                "LAB",
                "Lab Technician",
                "22000",
                "lab",
            ),
            (
                "EMP-1003",
                "Nasrin Akter",
                "নাসরিন আক্তার",
                "ADM",
                "Receptionist",
                "18000",
                "reception",
            ),
            (
                "EMP-1004",
                "Jahid Hasan",
                "জাহিদ হাসান",
                "ADM",
                "Accountant",
                "30000",
                "accountant",
            ),
            (
                "EMP-1005",
                "Mizanur Rahman",
                "মিজানুর রহমান",
                "IPD",
                "Ward Boy",
                "15000",
                None,
            ),
            ("EMP-1006", "Shamim Hossain", "", "ADM", "Cashier", "20000", "cashier"),
            (
                "EMP-1007",
                "Farhana Yasmin",
                "",
                "PHR",
                "Pharmacist",
                "24000",
                "pharmacist",
            ),
        ]
        self.staff = {}
        for code, name, name_bn, dept, desig, salary, _key in specs:
            basic = Decimal(salary)
            member, _ = Staff.objects.get_or_create(
                employee_code=code, defaults={"name_en": name}
            )
            member.name_en = name
            member.name_bn = name_bn
            member.department = departments.get(dept)
            member.designation = self._designation(desig)
            member.phone = f"0171{code[-4:]}"
            member.email = f"{code.lower()}@ihms.local"
            member.joining_date = self.today - dt.timedelta(days=900)
            member.employment_type = "permanent"
            member.status = StaffStatus.ACTIVE
            member.basic_salary = basic
            member.house_rent = (basic * Decimal("50") / Decimal("100")).quantize(
                Decimal("0.01")
            )
            member.medical_allowance = Decimal("1500")
            member.transport_allowance = Decimal("1000")
            member.pf_eligible = True
            member.tax_category = "general"
            member.salary_payment_mode = "bank"
            member.bank_name = "BRAC Bank"
            member.bank_account_no = f"1000{code[-4:]}"
            member.bank_routing_no = "060261726"
            member.save()
            self.staff[code] = member

    def _ensure_doctors(self) -> None:
        departments = {d.code: d for d in Department.objects.all()}
        specs = [
            (
                "ayesha",
                "Dr. Ayesha Rahman",
                "A-10001",
                "DOC-1001",
                "OPD",
                "General Medicine",
                "MBBS, FCPS (Medicine)",
                "1000",
                "500",
            ),
            (
                "kamal",
                "Dr. Kamal Hossain",
                "A-10002",
                "DOC-1002",
                "OPD",
                "Medicine",
                "MBBS, MD (Internal Medicine)",
                "800",
                "400",
            ),
            (
                "tanvir",
                "Dr. Tanvir Ahmed",
                "A-10004",
                "DOC-1004",
                "OT",
                "General Surgery",
                "MBBS, FCPS (Surgery)",
                "1200",
                "600",
            ),
            (
                "farid",
                "Dr. Farid Uddin",
                "A-10005",
                "DOC-1005",
                "RAD",
                "Radiology",
                "MBBS, DMRD",
                "1000",
                "500",
            ),
            (
                "rezaul",
                "Dr. Rezaul Karim",
                "A-10006",
                "DOC-1006",
                "OT",
                "Anaesthesiology",
                "MBBS, DA",
                "900",
                "450",
            ),
        ]
        self.doctors = {}
        for key, name, bmdc, emp, dept, spec, qual, fee, follow in specs:
            doctor, _ = Doctor.objects.get_or_create(
                bmdc_no=bmdc, defaults={"name_en": name}
            )
            doctor.name_en = name
            doctor.bmdc_no = bmdc
            doctor.employee_code = emp
            doctor.department = departments.get(dept)
            doctor.specialization = spec
            doctor.qualification = qual
            doctor.phone = f"01712{bmdc[-5:]}"
            doctor.email = f"{key}@ihms.local"
            doctor.joining_date = self.today - dt.timedelta(days=1200)
            doctor.consultation_fee = Decimal(fee)
            doctor.followup_fee = Decimal(follow)
            doctor.is_active = True
            doctor.save()
            self.doctors[key] = doctor
        for key in ("ayesha", "kamal", "tanvir"):
            self._ensure_slots(self.doctors[key])

    def _ensure_slots(self, doctor: Doctor) -> None:
        for weekday in range(7):
            for start, end, cap in (
                (time(9, 0), time(13, 0), 20),
                (time(17, 0), time(21, 0), 15),
            ):
                AvailabilitySlot.objects.get_or_create(
                    doctor=doctor,
                    weekday=weekday,
                    start_time=start,
                    defaults={"end_time": end, "max_patients": cap},
                )

    def _ensure_users(self) -> None:
        roles = {role.name: role for role in Role.objects.all()}
        specs = [
            (
                "doctor",
                "demo.doctor",
                "Dr. Ayesha Rahman",
                "Consultant",
                "Doctor",
                "ayesha",
                None,
            ),
            (
                "physician",
                "demo.physician",
                "Dr. Kamal Hossain",
                "Consultant",
                "Doctor",
                "kamal",
                None,
            ),
            (
                "surgeon",
                "demo.surgeon",
                "Dr. Tanvir Ahmed",
                "Consultant",
                "Doctor",
                "tanvir",
                None,
            ),
            (
                "nurse",
                "demo.nurse",
                "Rahima Begum",
                "Senior Staff Nurse",
                "Nurse",
                None,
                "EMP-1001",
            ),
            (
                "lab",
                "demo.lab",
                "Sabbir Ahmed",
                "Lab Technician",
                "Lab Technician",
                None,
                "EMP-1002",
            ),
            (
                "reception",
                "demo.reception",
                "Nasrin Akter",
                "Receptionist",
                "Receptionist",
                None,
                "EMP-1003",
            ),
            (
                "accountant",
                "demo.accountant",
                "Jahid Hasan",
                "Accountant",
                "Accountant",
                None,
                "EMP-1004",
            ),
            (
                "cashier",
                "demo.cashier",
                "Shamim Hossain",
                "Cashier",
                "Cashier",
                None,
                "EMP-1006",
            ),
            (
                "pharmacist",
                "demo.pharmacist",
                "Farhana Yasmin",
                "Pharmacist",
                "Pharmacist",
                None,
                "EMP-1007",
            ),
        ]
        self.users = {}
        for (
            key,
            username,
            full_name,
            designation,
            role_name,
            doctor_key,
            staff_code,
        ) in specs:
            role = roles.get(role_name)
            if role is None:
                raise CommandError(f"Role '{role_name}' is missing — run seed_roles.")
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User(username=username)
            user.email = f"{username}@ihms.local"
            user.phone = f"01713{abs(hash(username)) % 100000:05d}"
            user.full_name_en = full_name
            user.designation = designation
            user.is_staff = False
            user.is_active = True
            user.set_password(PASSWORD)
            user.save()
            user.roles.set([role])
            if doctor_key:
                doctor = self.doctors[doctor_key]
                doctor.user = user
                doctor.save(update_fields=["user", "updated_at"])
            if staff_code:
                member = self.staff[staff_code]
                member.user = user
                member.save(update_fields=["user", "updated_at"])
            self.users[key] = user

    def _designation(self, name: str) -> Designation:
        existing = Designation.objects.filter(name__iexact=name).first()
        if existing is not None:
            return existing
        base = (
            "".join(word[0] for word in name.split()).upper()[:20] or name[:3].upper()
        )
        code = base
        counter = 1
        while Designation.objects.filter(code=code).exists():
            counter += 1
            code = f"{base[:17]}{counter}"
        return Designation.objects.create(name=name, code=code)

    # ------------------------------------------------------------------
    # Portal accounts
    # ------------------------------------------------------------------
    def _seed_portal_accounts(self, p1: Patient, p2: Patient) -> None:
        for patient in (p1, p2):
            if patient.portal_user_id:
                patient.refresh_from_db()
                continue
            _user, verification, _code = portal.register_portal_account(
                uhid=patient.uhid,
                phone=patient.phone,
                email=patient.email,
                password=PASSWORD,
            )
            portal.verify_portal_account(
                verification=verification, code=verification.code
            )
            patient.refresh_from_db()
            portal.save_notification_preference(
                patient=patient,
                data={
                    "appointment_reminders": True,
                    "lab_report_ready": True,
                    "bill_due": True,
                    "admission_updates": True,
                    "email_enabled": True,
                    "sms_enabled": True,
                },
            )

    # ------------------------------------------------------------------
    # Pharmacy supply chain
    # ------------------------------------------------------------------
    def _seed_pharmacy_supply(self) -> None:
        self.stores = {s.code: s for s in PharmacyStore.objects.all()}
        central = self.stores["CS"]

        vendor, _ = Vendor.objects.get_or_create(
            name="Square Pharmaceuticals Ltd.",
            defaults={
                "contact_person": "Md. Salim Uddin",
                "phone": "01711556677",
                "email": "sales@square-demo.local",
                "address": "Mohakhali, Dhaka",
            },
        )

        specs = [
            ("Paracetamol", "tablet", 500, "0.85", "01"),
            ("Paracetamol", "syrup", 30, "60", "02"),
            ("Amoxicillin", "capsule", 200, "8.5", "03"),
            ("Azithromycin", "tablet", 100, "25", "04"),
            ("Omeprazole", "capsule", 200, "5", "05"),
            ("Ceftriaxone", "injection", 60, "160", "06"),
            ("Metformin", "tablet", 300, "2.5", "07"),
            ("Amlodipine", "tablet", 300, "2.1", "08"),
            ("Salbutamol", "inhaler", 20, "270", "09"),
            ("Normal Saline", "infusion", 100, "68", "10"),
        ]
        rows = []
        for generic, form, quantity, purchase, suffix in specs:
            drug = Drug.objects.filter(generic_name=generic, form=form).first()
            if drug is None:
                raise CommandError(
                    f"Drug {generic} ({form}) missing — run seed_masters."
                )
            rows.append(
                {
                    "drug": drug,
                    "quantity": quantity,
                    "purchase": Decimal(purchase),
                    "batch": f"B{suffix}-{self.today.year}",
                }
            )

        po = pharmacy.create_purchase_order(
            vendor=vendor,
            store=central,
            items=[
                {
                    "drug": row["drug"],
                    "quantity_ordered": row["quantity"],
                    "unit_price": row["purchase"],
                }
                for row in rows
            ],
            actor=self.users["pharmacist"],
            notes="DEMO-FLOW monthly replenishment",
        )
        po_items = {item.drug_id: item for item in po.items.all()}
        PurchaseOrder.objects.filter(pk=po.pk).update(
            order_date=self.today - dt.timedelta(days=8)
        )
        grn = pharmacy.receive_grn(
            store=central,
            purchase_order=po,
            vendor=vendor,
            received_date=self.today - dt.timedelta(days=7),
            items=[
                {
                    "drug": row["drug"],
                    "po_item": po_items[row["drug"].pk],
                    "batch_no": row["batch"],
                    "expiry_date": self.today + dt.timedelta(days=730),
                    "quantity": row["quantity"],
                    "purchase_price": row["purchase"],
                    "mrp": row["drug"].unit_price,
                }
                for row in rows
            ],
            actor=self.users["pharmacist"],
            notes="DEMO-FLOW GRN",
        )

        def move(code: str, generic: str, form: str, quantity: int) -> None:
            drug = Drug.objects.filter(generic_name=generic, form=form).first()
            pharmacy.transfer_stock(
                from_store=central,
                to_store=self.stores[code],
                drug=drug,
                quantity=quantity,
                actor=self.users["pharmacist"],
            )

        for generic, form, quantity in (
            ("Azithromycin", "tablet", 20),
            ("Paracetamol", "tablet", 100),
            ("Omeprazole", "capsule", 50),
            ("Ceftriaxone", "injection", 20),
            ("Normal Saline", "infusion", 20),
        ):
            move("OPD-P", generic, form, quantity)
        for generic, form, quantity in (
            ("Ceftriaxone", "injection", 20),
            ("Normal Saline", "infusion", 30),
            ("Paracetamol", "tablet", 100),
        ):
            move("WARD-P", generic, form, quantity)

        accounting.create_vendor_payment(
            vendor=vendor,
            amount=(grn.total_amount * Decimal("0.6")).quantize(Decimal("0.01")),
            method="bank",
            date=self.today - dt.timedelta(days=3),
            grn=grn,
            reference=grn.grn_number,
            notes="DEMO-FLOW 60% settlement of GRN",
            actor=self.users["accountant"],
        )
        accounting.create_expense(
            category=accounting.get_system_account(SystemAccount.EXPENSE_OTHER),
            paid_from=accounting.get_system_account(SystemAccount.BANK),
            amount=Decimal("15000"),
            description="Utilities (electricity & water) — demo",
            date=self.today - dt.timedelta(days=4),
            reference="EXP-DEMO-UTIL",
            actor=self.users["accountant"],
        )

    # ------------------------------------------------------------------
    # Patient one: OPD pneumonia → IPD → discharge
    # ------------------------------------------------------------------
    def _seed_p1(self, p1: Patient) -> None:
        day6 = self.today - dt.timedelta(days=6)
        doctor = self.doctors["kamal"]
        doctor_user = self.users["physician"]

        slot = self._slot_for(doctor, day6)
        appointment = Appointment.objects.create(
            doctor=doctor,
            patient=p1,
            slot=slot,
            appt_date=day6,
            slot_time=slot.start_time if slot else time(9, 0),
            token_no=1,
            status=AppointmentStatus.COMPLETED,
            visit_type=AppointmentType.NEW,
            consultation_fee=doctor.consultation_fee,
            notes="DEMO-FLOW OPD visit",
            created_by=self.users["reception"],
            arrived_at=self._at(day6, 9, 5),
            completed_at=self._at(day6, 9, 35),
        )

        enc, _ = emr.open_encounter(
            patient=p1,
            doctor=doctor,
            appointment=appointment,
            encounter_type=EncounterType.OUTPATIENT,
            chief_complaint="Fever and productive cough for four days",
            encounter_date=day6,
            actor=doctor_user,
        )
        self.enc1_opd = enc
        emr.record_vitals(
            encounter=enc,
            data={
                "temperature_c": "38.6",
                "pulse": 98,
                "respiratory_rate": 22,
                "bp_systolic": 130,
                "bp_diastolic": 84,
                "spo2": 95,
            },
            actor=self.users["nurse"],
        )
        emr.save_soap_note(
            encounter=enc,
            subjective="Fever for 4 days, productive cough with yellowish sputum, "
            "mild pleuritic chest pain. No haemoptysis.",
            objective="Temp 38.6 °C, pulse 98, RR 22, BP 130/84, SpO2 95% on air. "
            "Crackles at right base.",
            assessment="Community-acquired pneumonia, right lower lobe. "
            "Known hypertensive on amlodipine.",
            plan="Ceftriaxone + azithromycin, CBC/RBS/creatinine, chest X-ray, review.",
            actor=doctor_user,
        )
        emr.add_visit_diagnosis(
            encounter=enc,
            diagnosis=self._diagnosis("J18"),
            description="Community-acquired pneumonia, right lower lobe",
            is_primary=True,
            actor=doctor_user,
        )
        emr.add_problem(
            patient=p1,
            description="Essential hypertension",
            diagnosis=self._diagnosis("I10"),
            onset_date=self.today - dt.timedelta(days=1500),
            actor=doctor_user,
        )
        emr.add_allergy(
            patient=p1,
            allergen="Penicillin",
            allergy_type=AllergyType.DRUG,
            reaction="Rash and facial swelling",
            severity=AllergySeverity.MODERATE,
            actor=doctor_user,
        )

        lab_order = emr.create_lab_order(
            encounter=enc,
            tests=[
                self._lab_test("CBC001"),
                self._lab_test("CBC003"),
                self._lab_test("CBC004"),
            ],
            priority=OrderPriority.ROUTINE,
            notes="DEMO-FLOW baseline workup",
            actor=doctor_user,
        )
        sample = lab.ensure_sample(order=lab_order, actor=self.users["lab"])
        lab.collect_sample(sample=sample, actor=self.users["lab"])
        lab.receive_sample(sample=sample, actor=self.users["lab"])
        LabSample.objects.filter(pk=sample.pk).update(
            collected_at=self._at(day6, 10), received_at=self._at(day6, 10, 20)
        )
        values = {"CBC001": "9.2", "CBC003": "148", "CBC004": "1.1"}
        for item in lab_order.items.select_related("test"):
            result = lab.enter_result(
                order_item=item, value=values[item.test.code], actor=self.users["lab"]
            )
            lab.verify_result(result=result, actor=self.users["lab"])
        lab_order.refresh_from_db()
        lab.release_report(report=lab_order.report, actor=self.users["lab"])

        rad_order = emr.create_radiology_order(
            encounter=enc,
            tests=[self._radiology("RX001")],
            priority=OrderPriority.ROUTINE,
            clinical_indication="Suspected right lower lobe pneumonia",
            notes="DEMO-FLOW",
            actor=doctor_user,
        )
        record = lab.ensure_radiology_record(order=rad_order, actor=self.users["lab"])
        lab.schedule_radiology(
            record=record, scheduled_at=self._at(day6, 11), actor=self.users["lab"]
        )
        lab.record_radiology_report(
            record=record,
            findings="Patchy consolidation in the right lower zone. No effusion. "
            "Cardiothoracic ratio normal.",
            impression="Right lower lobe pneumonia.",
            radiologist=self.doctors["farid"],
            actor=self.users["lab"],
        )
        lab.verify_radiology(record=record, actor=self.users["lab"])
        lab.release_radiology(record=record, actor=self.users["lab"])
        RadiologyRecord.objects.filter(pk=record.pk).update(
            performed_at=self._at(day6, 11, 20)
        )

        bill = billing.post_opd_charges(p1, actor=self.users["reception"])
        bill = billing.post_lab_charges(p1, actor=self.users["reception"])
        billing.post_charge(
            bill,
            item_type=BillItemType.OTHER,
            description="Chest X-Ray P/A",
            quantity=1,
            unit_price=Decimal("600"),
            service_date=day6,
            source_type="lab.radiologyorder",
            source_id=rad_order.pk,
            actor=self.users["reception"],
        )

        prescription, _interactions = emr.issue_prescription(
            encounter=enc,
            items=[
                {
                    "drug": self._drug("Azithromycin", "tablet"),
                    "dose": "500 mg",
                    "route": Route.ORAL,
                    "frequency": "Once daily",
                    "duration_days": 3,
                    "quantity": 6,
                    "instructions": "After food",
                },
                {
                    "drug": self._drug("Paracetamol", "tablet"),
                    "dose": "500 mg",
                    "route": Route.ORAL,
                    "frequency": "Three times daily",
                    "duration_days": 5,
                    "quantity": 10,
                    "instructions": "For fever",
                },
                {
                    "drug": self._drug("Omeprazole", "capsule"),
                    "dose": "20 mg",
                    "route": Route.ORAL,
                    "frequency": "Once daily",
                    "duration_days": 5,
                    "quantity": 10,
                    "instructions": "Before breakfast",
                },
            ],
            notes="DEMO-FLOW OPD prescription",
            actor=doctor_user,
        )
        quantities = {item.pk: item.quantity for item in prescription.items.all()}
        dispense = pharmacy.dispense_prescription(
            prescription=prescription,
            store=self.stores["OPD-P"],
            quantities=quantities,
            actor=self.users["pharmacist"],
            notes="DEMO-FLOW OPD dispensing",
        )
        DispenseRecord.objects.filter(pk=dispense.pk).update(
            dispensed_at=self._at(day6, 12)
        )
        bill = billing.post_pharmacy_charges(p1, actor=self.users["reception"])

        self._issue_backdated(bill, self._at(day6, 17, 30), self.users["reception"])
        self._pay(
            bill,
            method=PaymentMode.CASH,
            amount=Decimal("1000"),
            when=self._at(day6, 17, 30),
            actor=self.users["cashier"],
        )
        self._pay(
            bill,
            method=PaymentMode.BKASH,
            amount=bill.due_amount,
            when=self._at(day6, 17, 30),
            actor=self.users["cashier"],
            txn_ref="BKASH-DEMO-P1",
        )
        emr.close_encounter(instance=enc, actor=doctor_user)

        self._seed_p1_ipd(p1, doctor, doctor_user)

    def _seed_p1_ipd(self, p1: Patient, doctor: Doctor, doctor_user: User) -> None:
        day5 = self.today - dt.timedelta(days=5)
        discharge_day = self.today - dt.timedelta(days=2)
        nurse_user = self.users["nurse"]

        enc, _ = emr.open_encounter(
            patient=p1,
            doctor=doctor,
            encounter_type=EncounterType.INPATIENT,
            chief_complaint="Pneumonia — admitted for IV antibiotics",
            encounter_date=day5,
            actor=doctor_user,
        )
        self.enc1_ipd = enc
        admission = ipd.request_admission(
            patient=p1,
            doctor=doctor,
            admission_type=AdmissionType.ROUTINE,
            reason="Community-acquired pneumonia",
            admission_note="DEMO-FLOW · CAP right lower lobe, IV antibiotics",
            encounter=enc,
            actor=doctor_user,
        )
        admission = ipd.allocate_bed(
            admission=admission, bed=self._free_bed("HDU"), actor=nurse_user
        )
        Admission.objects.filter(pk=admission.pk).update(admitted_at=self._at(day5, 11))
        admission.refresh_from_db()
        ipd.accrue_daily_charges(charge_date=day5, admission=admission)

        cabin = self._free_bed("Cabin Wing")
        ipd.transfer_bed(
            admission=admission,
            to_bed=cabin,
            reason="Clinical improvement — step-down to cabin",
            actor=doctor_user,
        )
        for offset in (4, 3, 2):
            ipd.accrue_daily_charges(
                charge_date=self.today - dt.timedelta(days=offset), admission=admission
            )

        advance = billing.add_advance(
            p1,
            amount=Decimal("15000"),
            method=PaymentMode.BKASH,
            admission=admission,
            txn_ref="ADV-DEMO-P1",
            notes="DEMO-FLOW admission deposit",
            actor=self.users["cashier"],
        )
        self._backdate_advance(advance, self._at(day5, 12))

        emr.record_vitals(
            encounter=enc,
            data={
                "temperature_c": "37.2",
                "pulse": 88,
                "respiratory_rate": 20,
                "bp_systolic": 126,
                "bp_diastolic": 80,
                "spo2": 94,
            },
            actor=nurse_user,
        )
        emr.save_soap_note(
            encounter=enc,
            subjective="Cough improving, less breathless, appetite returning.",
            objective="Afebrile. Right basal crackles reducing. SpO2 94% on air.",
            assessment="CAP — improving on IV ceftriaxone.",
            plan="Continue IV antibiotics, chest physiotherapy, step-down to cabin.",
            actor=doctor_user,
        )

        rx, _ = emr.issue_prescription(
            encounter=enc,
            items=[
                {
                    "drug": self._drug("Ceftriaxone", "injection"),
                    "dose": "1 gm",
                    "route": Route.IV,
                    "frequency": "Twice daily",
                    "duration_days": 3,
                    "quantity": 3,
                    "instructions": "Slow IV push",
                },
                {
                    "drug": self._drug("Normal Saline", "infusion"),
                    "dose": "500 ml",
                    "route": Route.IV,
                    "frequency": "Twice daily",
                    "duration_days": 2,
                    "quantity": 2,
                    "instructions": "Over 4 hours",
                },
            ],
            notes="DEMO-FLOW inpatient antibiotics",
            actor=doctor_user,
        )
        ceftriaxone = self._drug("Ceftriaxone", "injection")
        saline = self._drug("Normal Saline", "infusion")
        for when in (
            self._at(day5, 20),
            self._at(self.today - dt.timedelta(days=4), 8),
            self._at(self.today - dt.timedelta(days=4), 20),
            self._at(self.today - dt.timedelta(days=3), 8),
        ):
            ipd.record_mar(
                admission=admission,
                drug=ceftriaxone,
                dose="1 gm",
                route=Route.IV,
                scheduled_for=when,
                action=MarAction.GIVEN,
                notes="DEMO-FLOW",
                actor=nurse_user,
            )
        for when in (
            self._at(day5, 21),
            self._at(self.today - dt.timedelta(days=4), 9),
        ):
            ipd.record_mar(
                admission=admission,
                drug=saline,
                dose="500 ml",
                route=Route.IV,
                scheduled_for=when,
                action=MarAction.GIVEN,
                notes="DEMO-FLOW",
                actor=nurse_user,
            )
        for _day_offset, shift, note in (
            (
                5,
                NursingShift.DAY,
                "Admitted to HDU; IV access secured; antibiotics started.",
            ),
            (
                4,
                NursingShift.NIGHT,
                "Afebrile overnight; transferred to cabin at 10:00.",
            ),
            (3, NursingShift.DAY, "Mobilising well; oral intake adequate."),
        ):
            ipd.record_nursing_note(
                admission=admission,
                note=note,
                shift=shift,
                actor=nurse_user,
            )
        for _day_offset, shift, volume in (
            (5, NursingShift.DAY, 1200),
            (5, NursingShift.DAY, 900),
            (4, NursingShift.DAY, 1500),
            (4, NursingShift.DAY, 1100),
        ):
            category = FluidCategory.IV if volume > 1000 else FluidCategory.URINE
            ipd.record_intake_output(
                admission=admission,
                fluid_type=(
                    FluidType.INTAKE
                    if category == FluidCategory.IV
                    else FluidType.OUTPUT
                ),
                category=category,
                volume_ml=volume,
                shift=shift,
                actor=nurse_user,
            )

        chart = icu.create_icu_record(
            admission=admission,
            data={
                "temperature": "37.4",
                "pulse": 92,
                "respiratory_rate": 24,
                "bp_systolic": 122,
                "bp_diastolic": 78,
                "spo2": 88,
                "gcs": 15,
                "notes": "Transient desaturation after transfer — HDU chart.",
                "recorded_at": self._at(day5, 20),
            },
            actor=nurse_user,
        )
        alert = chart.alerts.filter(status="active").first()
        if alert is not None:
            icu.resolve_alert(alert=alert, actor=nurse_user)
        icu.create_icu_record(
            admission=admission,
            data={
                "temperature": "36.9",
                "pulse": 84,
                "respiratory_rate": 20,
                "bp_systolic": 124,
                "bp_diastolic": 80,
                "spo2": 96,
                "gcs": 15,
                "notes": "Stable on cabin — SpO2 improved on 2 L nasal prongs.",
                "recorded_at": self._at(self.today - dt.timedelta(days=4), 8),
            },
            actor=nurse_user,
        )
        icu.record_score(
            admission=admission,
            score_type=ScoreType.APACHE_II,
            data={
                "temperature": 37.2,
                "map": 76,
                "heart_rate": 96,
                "respiratory_rate": 22,
                "pao2": 78,
                "ph": 7.38,
                "sodium": 138,
                "potassium": 4.2,
                "creatinine": 1.1,
                "hematocrit": 38,
                "wbc": 11.5,
                "gcs": 15,
                "age": 40,
                "chronic_health": 0,
            },
            actor=doctor_user,
        )
        icu.record_score(
            admission=admission,
            score_type=ScoreType.SOFA,
            data={
                "pao2_fio2": 320,
                "resp_support": 0,
                "platelets": 220,
                "bilirubin": 0.8,
                "map": 76,
                "vasopressor_level": 0,
                "gcs": 15,
                "creatinine": 1.1,
                "urine_output": 1200,
            },
            actor=doctor_user,
        )
        blue = icu.raise_code_blue(
            location="HDU",
            admission=admission,
            notes="Transient desaturation to 88% — responded to oxygen.",
            actor=nurse_user,
        )
        icu.resolve_code_blue(
            alert=blue, notes="Recovered within two minutes.", actor=doctor_user
        )
        icu.record_handover(
            unit=Unit.ICU,
            shift=UnitShift.DAY,
            summary="CAP on IV ceftriaxone, step-down to cabin, SpO2 stable on air.",
            admission=admission,
            pending_tasks="Repeat chest X-ray before discharge.",
            actor=nurse_user,
        )

        ipd_bill = billing.create_bill(
            p1,
            bill_type="ipd",
            admission=admission,
            notes="DEMO-FLOW IPD bill",
            actor=self.users["reception"],
        )
        ipd_bill = billing.post_ipd_charges(admission, actor=self.users["reception"])

        ward_dispense = pharmacy.dispense_prescription(
            prescription=rx,
            store=self.stores["WARD-P"],
            quantities={item.pk: item.quantity for item in rx.items.all()},
            actor=self.users["pharmacist"],
            notes="DEMO-FLOW ward dispensing",
        )
        DispenseRecord.objects.filter(pk=ward_dispense.pk).update(
            dispensed_at=self._at(day5, 13)
        )
        for line in ward_dispense.items.all():
            billing.post_charge(
                ipd_bill,
                item_type=BillItemType.PHARMACY,
                description=f"{line.drug} × {line.quantity}",
                quantity=line.quantity,
                unit_price=line.unit_price,
                service_date=day5,
                source_type="pharmacy.dispenseitem",
                source_id=line.pk,
                actor=self.users["reception"],
            )
        ward_dispense.is_billed = True
        ward_dispense.save(update_fields=["is_billed", "updated_at"])

        billing.apply_discount(
            ipd_bill,
            amount=Decimal("700"),
            reason="DEMO-FLOW loyalty discount",
            actor=self.users["accountant"],
        )
        discharge_at = self._at(discharge_day, 12)
        self._issue_backdated(ipd_bill, discharge_at, self.users["reception"])
        payment = billing.apply_advance(
            advance, ipd_bill, amount=ipd_bill.due_amount, actor=self.users["cashier"]
        )
        self._backdate_payment(payment, discharge_at)

        for department in (
            ClearanceDepartment.LAB,
            ClearanceDepartment.PHARMACY,
            ClearanceDepartment.BILLING,
        ):
            ipd.set_clearance(
                admission=admission,
                department=department,
                cleared=True,
                notes="DEMO-FLOW no dues",
                actor=self.users["accountant"],
            )
        admission.refresh_from_db()
        ipd.mark_discharge_request(
            admission=admission,
            reason="Recovered — afebrile, SpO2 stable on air",
            actor=doctor_user,
        )
        summary = ipd.discharge(
            admission=admission,
            summary_data={
                "discharge_type": DischargeType.ROUTINE,
                "diagnosis_summary": "Community-acquired pneumonia, right lower lobe.",
                "treatment_given": (
                    "IV ceftriaxone and supportive care; step-down HDU → cabin."
                ),
                "follow_up": "Medicine OPD in 7 days with repeat chest X-ray.",
                "discharge_advice": (
                    "Complete oral antibiotics, avoid smoking, return if breathless."
                ),
            },
            actor=doctor_user,
        )
        Admission.objects.filter(pk=admission.pk).update(discharged_at=discharge_at)
        DischargeSummary.objects.filter(pk=summary.pk).update(
            discharged_at=discharge_at
        )
        emr.close_encounter(instance=enc, actor=doctor_user)

    # ------------------------------------------------------------------
    # Patient two: ER appendicitis → surgery → still admitted
    # ------------------------------------------------------------------
    def _seed_p2(self, p2: Patient) -> None:
        day3 = self.today - dt.timedelta(days=3)
        day1 = self.today - dt.timedelta(days=1)
        doctor = self.doctors["tanvir"]
        doctor_user = self.users["surgeon"]

        case = icu.open_emergency_case(
            patient=p2,
            complaint="Severe right lower abdominal pain for 12 hours with vomiting",
            triage_level=TriageLevel.ORANGE,
            attending_doctor=doctor,
            vitals={
                "temperature": "38.9",
                "pulse": 108,
                "respiratory_rate": 22,
                "bp_systolic": 118,
                "bp_diastolic": 76,
                "spo2": 97,
                "notes": "Rebound tenderness at McBurney's point.",
            },
            actor=doctor_user,
        )
        icu.set_emergency_status(
            case=case, status=EmergencyStatus.IN_TREATMENT, actor=doctor_user
        )

        enc, _ = emr.open_encounter(
            patient=p2,
            doctor=doctor,
            encounter_type=EncounterType.EMERGENCY,
            chief_complaint="Right lower abdominal pain and vomiting",
            encounter_date=day3,
            actor=doctor_user,
        )
        self.enc2_er = enc
        emr.record_vitals(
            encounter=enc,
            data={
                "temperature_c": "38.9",
                "pulse": 108,
                "respiratory_rate": 22,
                "bp_systolic": 118,
                "bp_diastolic": 76,
                "spo2": 97,
                "pain_score": 7,
            },
            actor=self.users["nurse"],
        )
        emr.save_soap_note(
            encounter=enc,
            subjective="Peri-umbilical pain migrating to right iliac fossa, "
            "anorexia and two episodes of vomiting.",
            objective="Febrile, tachycardic. Guarding and rebound tenderness at "
            "McBurney's point. Rovsing positive.",
            assessment="Acute appendicitis.",
            plan="NPO, IV fluids, analgesia, CBC/creatinine, USG abdomen, "
            "consent for appendectomy.",
            actor=doctor_user,
        )
        emr.add_visit_diagnosis(
            encounter=enc,
            diagnosis=self._diagnosis("K35"),
            description="Acute appendicitis",
            is_primary=True,
            actor=doctor_user,
        )
        emr.add_allergy(
            patient=p2,
            allergen="Sulfa drugs",
            allergy_type=AllergyType.DRUG,
            reaction="Urticaria",
            severity=AllergySeverity.MILD,
            actor=doctor_user,
        )

        lab_order = emr.create_lab_order(
            encounter=enc,
            tests=[self._lab_test("CBC001"), self._lab_test("CBC004")],
            priority=OrderPriority.STAT,
            notes="DEMO-FLOW ER workup",
            actor=doctor_user,
        )
        sample = lab.ensure_sample(order=lab_order, actor=self.users["lab"])
        lab.collect_sample(sample=sample, actor=self.users["lab"])
        lab.receive_sample(sample=sample, actor=self.users["lab"])
        LabSample.objects.filter(pk=sample.pk).update(
            collected_at=self._at(day3, 9), received_at=self._at(day3, 9, 15)
        )
        for item in lab_order.items.select_related("test"):
            value = "13.5" if item.test.code == "CBC001" else "0.9"
            result = lab.enter_result(
                order_item=item, value=value, actor=self.users["lab"]
            )
            lab.verify_result(result=result, actor=self.users["lab"])
        lab_order.refresh_from_db()
        lab.release_report(report=lab_order.report, actor=self.users["lab"])

        rad_order = emr.create_radiology_order(
            encounter=enc,
            tests=[self._radiology("US001")],
            priority=OrderPriority.STAT,
            clinical_indication="Suspected acute appendicitis",
            notes="DEMO-FLOW",
            actor=doctor_user,
        )
        record = lab.ensure_radiology_record(order=rad_order, actor=self.users["lab"])
        lab.schedule_radiology(
            record=record, scheduled_at=self._at(day3, 9, 30), actor=self.users["lab"]
        )
        lab.record_radiology_report(
            record=record,
            findings="Retrocaecal appendix, 11 mm, non-compressible with "
            "peri-appendiceal fat stranding. No free fluid.",
            impression="Acute appendicitis.",
            radiologist=self.doctors["farid"],
            actor=self.users["lab"],
        )
        lab.verify_radiology(record=record, actor=self.users["lab"])
        lab.release_radiology(record=record, actor=self.users["lab"])
        RadiologyRecord.objects.filter(pk=record.pk).update(
            performed_at=self._at(day3, 9, 45)
        )

        rx, _ = emr.issue_prescription(
            encounter=enc,
            items=[
                {
                    "drug": self._drug("Ceftriaxone", "injection"),
                    "dose": "1 gm",
                    "route": Route.IV,
                    "frequency": "Twice daily",
                    "duration_days": 3,
                    "quantity": 2,
                    "instructions": "Pre-operative prophylaxis",
                },
                {
                    "drug": self._drug("Paracetamol", "tablet"),
                    "dose": "500 mg",
                    "route": Route.ORAL,
                    "frequency": "Three times daily",
                    "duration_days": 4,
                    "quantity": 10,
                    "instructions": "For pain and fever",
                },
            ],
            notes="DEMO-FLOW ER prescription",
            actor=doctor_user,
        )
        dispense = pharmacy.dispense_prescription(
            prescription=rx,
            store=self.stores["OPD-P"],
            quantities={item.pk: item.quantity for item in rx.items.all()},
            actor=self.users["pharmacist"],
            notes="DEMO-FLOW ER dispensing",
        )
        DispenseRecord.objects.filter(pk=dispense.pk).update(
            dispensed_at=self._at(day3, 10)
        )

        er_bill = billing.create_bill(
            p2,
            bill_type="opd",
            notes="DEMO-FLOW emergency visit",
            actor=self.users["reception"],
        )
        billing.post_charge(
            er_bill,
            item_type=BillItemType.EMERGENCY,
            description="Emergency consultation · Dr. Tanvir Ahmed",
            quantity=1,
            unit_price=doctor.consultation_fee,
            service_date=day3,
            source_type="emr.emergencycase",
            source_id=case.pk,
            actor=self.users["reception"],
        )
        billing.post_lab_charges(p2, actor=self.users["reception"])
        billing.post_charge(
            er_bill,
            item_type=BillItemType.OTHER,
            description="Ultrasonography (Whole Abdomen)",
            quantity=1,
            unit_price=Decimal("1200"),
            service_date=day3,
            source_type="lab.radiologyorder",
            source_id=rad_order.pk,
            actor=self.users["reception"],
        )
        billing.post_pharmacy_charges(p2, actor=self.users["reception"])
        self._issue_backdated(er_bill, self._at(day3, 12), self.users["reception"])
        self._pay(
            er_bill,
            method=PaymentMode.CARD,
            amount=er_bill.due_amount,
            when=self._at(day3, 12),
            actor=self.users["cashier"],
            txn_ref="CARD-DEMO-P2",
        )

        case = icu.convert_to_admission(
            case=case,
            doctor=doctor,
            reason="Acute appendicitis — for appendectomy",
            admission_type=AdmissionType.EMERGENCY,
            actor=doctor_user,
        )
        admission = case.converted_admission
        Admission.objects.filter(pk=admission.pk).update(
            admission_note="DEMO-FLOW · Acute appendicitis, post-op day 1",
            admitted_at=self._at(day3, 12, 30),
        )
        admission.refresh_from_db()
        ipd.allocate_bed(
            admission=admission,
            bed=self._free_bed("General Ward"),
            actor=self.users["nurse"],
        )
        Admission.objects.filter(pk=admission.pk).update(
            admitted_at=self._at(day3, 12, 30)
        )
        admission.refresh_from_db()
        for offset in (3, 2, 1):
            ipd.accrue_daily_charges(
                charge_date=self.today - dt.timedelta(days=offset), admission=admission
            )

        enc_ipd, _ = emr.open_encounter(
            patient=p2,
            doctor=doctor,
            encounter_type=EncounterType.INPATIENT,
            chief_complaint="Post-appendectomy care",
            encounter_date=day3,
            actor=doctor_user,
        )
        self.enc2_ipd = enc_ipd
        emr.close_encounter(instance=enc, actor=doctor_user)
        icu.record_handover(
            unit=Unit.ER,
            shift=UnitShift.DAY,
            summary=(
                "Acute appendicitis, USG confirmed, transferred to ward for surgery."
            ),
            emergency_case=case,
            pending_tasks="Consent, NPO, pre-op checklist.",
            actor=doctor_user,
        )
        emr.record_vitals(
            encounter=enc_ipd,
            data={
                "temperature_c": "37.8",
                "pulse": 92,
                "respiratory_rate": 18,
                "bp_systolic": 120,
                "bp_diastolic": 78,
                "spo2": 98,
                "pain_score": 4,
            },
            actor=self.users["nurse"],
        )
        for _day_offset, shift, note in (
            (3, NursingShift.DAY, "Admitted from ER; pre-op checklist completed."),
            (
                2,
                NursingShift.DAY,
                "Post-op day 1: afebrile, wound clean, tolerating sips.",
            ),
            (1, NursingShift.NIGHT, "Pain controlled; mobilising with assistance."),
        ):
            ipd.record_nursing_note(
                admission=admission, note=note, shift=shift, actor=self.users["nurse"]
            )

        procedure_order = emr.create_procedure_order(
            encounter=enc_ipd,
            procedure=self._procedure("PRC003"),
            priority=OrderPriority.URGENT,
            scheduled_for=self._at(day1, 9),
            notes="DEMO-FLOW appendectomy",
            actor=doctor_user,
        )
        emr.set_order_status(
            instance=procedure_order, status=OrderStatus.COMPLETED, actor=doctor_user
        )

        surgery = ot.schedule_surgery(
            patient=p2,
            surgeon=doctor,
            ot_room=self._ot_room(),
            scheduled_date=day1,
            start_time=time(9, 0),
            end_time=time(10, 30),
            procedure_name="Appendectomy (open)",
            priority="urgent",
            admission=admission,
            diagnosis="Acute appendicitis",
            notes="DEMO-FLOW",
            actor=doctor_user,
        )
        ot.save_preop_checklist(
            surgery=surgery,
            data={
                "consent_signed": True,
                "npo_confirmed": True,
                "site_marked": True,
                "allergies_reviewed": True,
                "vitals_stable": True,
                "blood_arranged": True,
                "iv_access": True,
                "imaging_available": True,
                "notes": "DEMO-FLOW checklist complete",
            },
            actor=doctor_user,
        )
        ot.add_team_member(
            surgery=surgery, role=TeamRole.SURGEON, doctor=doctor, actor=doctor_user
        )
        ot.add_team_member(
            surgery=surgery,
            role=TeamRole.ASSISTANT,
            doctor=self.doctors["kamal"],
            actor=doctor_user,
        )
        ot.add_team_member(
            surgery=surgery,
            role=TeamRole.ANESTHETIST,
            doctor=self.doctors["rezaul"],
            actor=doctor_user,
        )
        ot.add_team_member(
            surgery=surgery,
            role=TeamRole.SCRUB_NURSE,
            staff=self.staff["EMP-1001"],
            actor=doctor_user,
        )
        ot.add_team_member(
            surgery=surgery,
            role=TeamRole.CIRCULATING,
            staff=self.staff["EMP-1005"],
            actor=doctor_user,
        )
        ot.start_surgery(surgery=surgery, actor=doctor_user)
        ot.record_anesthesia(
            surgery=surgery,
            data={
                "anesthesia_type": AnesthesiaType.GENERAL,
                "anesthetist": self.doctors["rezaul"],
                "asa_grade": 2,
                "airway": "Endotracheal tube",
                "agents": "Propofol, sevoflurane",
                "intubation_time": time(9, 5),
                "extubation_time": time(10, 10),
                "notes": "Uneventful induction and emergence.",
            },
            actor=doctor_user,
        )
        ot.record_intraop_note(
            surgery=surgery,
            data={
                "findings": "Inflamed, retrocaecal appendix with minimal serous fluid.",
                "procedure_performed": "Open appendectomy through gridiron incision.",
                "blood_loss_ml": 50,
                "specimens": "Appendix sent for histopathology",
                "drains": "None",
                "closure": "Layer-wise closure with Vicryl 2-0",
                "notes": "No intra-operative complication.",
            },
            actor=doctor_user,
        )
        ot.record_postop_note(
            surgery=surgery,
            data={
                "condition": PatientCondition.STABLE,
                "pain_score": 3,
                "recovery_notes": "Recovered in PACU, vitals stable.",
                "follow_up_plan": "Review in 7 days; suture removal in 10 days.",
                "notes": "DEMO-FLOW",
            },
            actor=doctor_user,
        )
        consumable_a = ot.record_consumable(
            surgery=surgery,
            data={
                "item": "Vicryl 2-0 suture",
                "quantity": 2,
                "unit_price": Decimal("600"),
                "notes": "DEMO-FLOW",
            },
            actor=doctor_user,
        )
        consumable_b = ot.record_consumable(
            surgery=surgery,
            data={
                "item": "Sterile gauze pack",
                "quantity": 1,
                "unit_price": Decimal("300"),
                "notes": "DEMO-FLOW",
            },
            actor=doctor_user,
        )
        ot.complete_surgery(surgery=surgery, actor=doctor_user)
        Surgery.objects.filter(pk=surgery.pk).update(
            started_at=self._at(day1, 9, 5),
            completed_at=self._at(day1, 10, 20),
        )

        rx_ipd, _ = emr.issue_prescription(
            encounter=enc_ipd,
            items=[
                {
                    "drug": self._drug("Paracetamol", "tablet"),
                    "dose": "500 mg",
                    "route": Route.ORAL,
                    "frequency": "Three times daily",
                    "duration_days": 4,
                    "quantity": 10,
                    "instructions": "For post-operative pain",
                },
                {
                    "drug": self._drug("Ceftriaxone", "injection"),
                    "dose": "1 gm",
                    "route": Route.IV,
                    "frequency": "Twice daily",
                    "duration_days": 2,
                    "quantity": 2,
                    "instructions": "Post-operative cover",
                },
            ],
            notes="DEMO-FLOW inpatient prescription",
            actor=doctor_user,
        )
        ward_dispense = pharmacy.dispense_prescription(
            prescription=rx_ipd,
            store=self.stores["WARD-P"],
            quantities={item.pk: item.quantity for item in rx_ipd.items.all()},
            actor=self.users["pharmacist"],
            notes="DEMO-FLOW ward dispensing",
        )
        DispenseRecord.objects.filter(pk=ward_dispense.pk).update(
            dispensed_at=self._at(day1, 11)
        )

        ipd_bill = billing.create_bill(
            p2,
            bill_type="ipd",
            admission=admission,
            notes="DEMO-FLOW IPD bill",
            actor=self.users["reception"],
        )
        ipd_bill = billing.post_ipd_charges(admission, actor=self.users["reception"])
        billing.post_charge(
            ipd_bill,
            item_type=BillItemType.PROCEDURE,
            description="Appendectomy",
            quantity=1,
            unit_price=Decimal("30000"),
            service_date=day1,
            source_type="emr.procedureorder",
            source_id=procedure_order.pk,
            actor=self.users["reception"],
        )
        for consumable in (consumable_a, consumable_b):
            billing.post_charge(
                ipd_bill,
                item_type=BillItemType.CONSUMABLE,
                description=consumable.item,
                quantity=consumable.quantity,
                unit_price=consumable.unit_price,
                service_date=day1,
                source_type="ot.surgeryconsumable",
                source_id=consumable.pk,
                actor=self.users["reception"],
            )
            consumable.is_billed = True
            consumable.save(update_fields=["is_billed", "updated_at"])
        for line in ward_dispense.items.all():
            billing.post_charge(
                ipd_bill,
                item_type=BillItemType.PHARMACY,
                description=f"{line.drug} × {line.quantity}",
                quantity=line.quantity,
                unit_price=line.unit_price,
                service_date=day1,
                source_type="pharmacy.dispenseitem",
                source_id=line.pk,
                actor=self.users["reception"],
            )
        ward_dispense.is_billed = True
        ward_dispense.save(update_fields=["is_billed", "updated_at"])

        self._issue_backdated(ipd_bill, self._at(day1, 12), self.users["reception"])
        payment = portal.initiate_portal_payment(
            bill=ipd_bill,
            method=PaymentMode.BKASH,
            amount=Decimal("20000"),
            patient=p2,
            actor=p2.portal_user,
        )
        portal.confirm_portal_payment(
            payment=payment,
            success=True,
            gateway_ref="SANDBOX-DEMO-P2",
            actor=p2.portal_user,
        )
        self._backdate_payment(payment, self._at(day1, 12, 30))

        self._seed_portal_activity(p2)

    def _seed_portal_activity(self, p2: Patient) -> None:
        portal.create_record_request(
            patient=p2,
            data={
                "purpose": "For insurance reimbursement",
                "records_from": self.today - dt.timedelta(days=10),
                "records_to": self.today,
            },
            actor=p2.portal_user,
        )

    # ------------------------------------------------------------------
    # Payroll
    # ------------------------------------------------------------------
    def _seed_payroll(self) -> None:
        first_this = self.today.replace(day=1)
        last_prev = first_this - dt.timedelta(days=1)
        year, month = last_prev.year, last_prev.month
        days = calendar.monthrange(year, month)[1]
        active = list(Staff.objects.filter(status=StaffStatus.ACTIVE))

        for day in range(1, days + 1):
            att_date = dt.date(year, month, day)
            if att_date.weekday() == 6:
                continue
            for member in active:
                hr.upsert_attendance(
                    staff=member,
                    att_date=att_date,
                    status=AttendanceStatus.PRESENT,
                    check_in=time(9, 0),
                    check_out=time(17, 0),
                    actor=self.users["accountant"],
                )

        by_code = {member.employee_code: member for member in active}

        def working_day(day: int) -> dt.date:
            att_date = dt.date(year, month, day)
            while att_date.weekday() == 6:
                att_date += dt.timedelta(days=1)
            return att_date

        for day in (4, 11, 18):
            hr.upsert_attendance(
                staff=by_code["EMP-1002"],
                att_date=working_day(day),
                status=AttendanceStatus.LATE,
                check_in=time(9, 45),
                check_out=time(17, 0),
                actor=self.users["accountant"],
            )
        hr.upsert_attendance(
            staff=by_code["EMP-1003"],
            att_date=working_day(7),
            status=AttendanceStatus.ABSENT,
            actor=self.users["accountant"],
        )

        lwp = LeaveType.objects.filter(code="LWP").first()
        if lwp is not None:
            start = working_day(14)
            end = working_day(15)
            leave = hr.apply_leave(
                staff=by_code["EMP-1005"],
                leave_type=lwp,
                start_date=start,
                end_date=end,
                reason="DEMO-FLOW unpaid personal leave",
                actor=self.users["accountant"],
            )
            hr.approve_leave(
                leave=leave, note="Approved (demo)", actor=self.users["accountant"]
            )
            for day in (start, end):
                hr.upsert_attendance(
                    staff=by_code["EMP-1005"],
                    att_date=day,
                    status=AttendanceStatus.LEAVE,
                    actor=self.users["accountant"],
                )

        payroll.create_adjustment(
            staff=by_code["EMP-1001"],
            year=year,
            month=month,
            kind=AdjustmentKind.EARNING,
            amount=Decimal("2000"),
            reason="DEMO-FLOW performance bonus",
            actor=self.users["accountant"],
        )
        payroll.create_adjustment(
            staff=by_code["EMP-1003"],
            year=year,
            month=month,
            kind=AdjustmentKind.DEDUCTION,
            amount=Decimal("500"),
            reason="DEMO-FLOW late fine",
            actor=self.users["accountant"],
        )

        run = payroll.generate_run(
            year=year,
            month=month,
            payment_date=last_prev,
            payment_method="bank",
            notes="DEMO-FLOW payroll run",
            actor=self.users["accountant"],
        )
        payroll.approve_run(run, actor=self.users["accountant"])
        self.payroll_run = payroll.mark_run_paid(
            run, payment_date=last_prev, actor=self.users["accountant"]
        )

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    def _seed_reports(self) -> None:
        first_prev = self.today.replace(day=1) - dt.timedelta(days=1)
        first_prev = first_prev.replace(day=1)
        last_prev = self.today.replace(day=1) - dt.timedelta(days=1)

        self.report_runs = []
        self.report_runs.append(
            reports.generate_report(
                ReportType.DAILY_CENSUS,
                report_format=ReportFormat.CSV,
                start=self.today,
                end=self.today,
                actor=self.users["accountant"],
            )
        )
        daily = ReportSchedule.objects.filter(name="Daily Census (demo)").first()
        if daily is None:
            daily = ReportSchedule.objects.create(
                name="Daily Census (demo)",
                report_type=ReportType.DAILY_CENSUS,
                frequency=ReportFrequency.DAILY,
                report_format=ReportFormat.CSV,
                parameters={"range_days": 1},
                created_by=self.users["accountant"],
            )
        self.report_runs.append(
            reports.run_schedule(
                daily, actor=self.users["accountant"], send_email=False
            )
        )

        monthly = ReportSchedule.objects.filter(name="Monthly Revenue (demo)").first()
        if monthly is None:
            monthly = ReportSchedule.objects.create(
                name="Monthly Revenue (demo)",
                report_type=ReportType.MONTHLY_REVENUE,
                frequency=ReportFrequency.MONTHLY,
                report_format=ReportFormat.XLSX,
                parameters={"start": str(first_prev), "end": str(last_prev)},
                created_by=self.users["accountant"],
            )
        self.report_runs.append(
            reports.run_schedule(
                monthly, actor=self.users["accountant"], send_email=False
            )
        )

    # ------------------------------------------------------------------
    # Documents & portal requests
    # ------------------------------------------------------------------
    def _seed_documents(self, p1: Patient) -> None:
        patients.add_document(
            patient=p1,
            data={
                "title": "National ID (demo scan)",
                "category": DocumentCategory.ID,
                "file": ContentFile(
                    b"DEMO national ID scan for Abdul Karim\n", name="demo-nid-p1.txt"
                ),
                "notes": "DEMO-FLOW",
            },
            actor=self.users["reception"],
        )
        emr.add_attachment(
            patient=p1,
            file=ContentFile(
                b"DEMO chest X-ray narrative report\n", name="demo-cxr-p1.txt"
            ),
            title="Chest X-ray report (demo)",
            category=AttachmentCategory.REPORT,
            encounter=self.enc1_opd,
            description="DEMO-FLOW",
            actor=self.users["physician"],
        )
        follow_up = self.today + dt.timedelta(days=7)
        doctor = self.doctors["kamal"]
        portal.book_portal_appointment(
            patient=p1,
            doctor=doctor,
            appt_date=follow_up,
            slot=self._slot_for(doctor, follow_up),
            visit_type=AppointmentType.FOLLOWUP,
            actor=p1.portal_user,
        )
        request = portal.create_record_request(
            patient=p1,
            data={
                "purpose": "Second opinion — copies of discharge documents",
                "records_from": self.today - dt.timedelta(days=10),
                "records_to": self.today,
            },
            actor=p1.portal_user,
        )
        MedicalRecordRequest.objects.filter(pk=request.pk).update(
            status=MedicalRecordRequestStatus.COMPLETED,
            handled_by=self.users["reception"],
            handled_at=self._at(self.today - dt.timedelta(days=1), 15),
            response_notes="DEMO-FLOW documents released.",
        )

    # ------------------------------------------------------------------
    # Backdating helpers
    # ------------------------------------------------------------------
    def _issue_backdated(self, bill: Bill, when, actor) -> Bill:
        Bill.objects.filter(pk=bill.pk).update(status=BillStatus.ISSUED, issued_at=when)
        bill.refresh_from_db()
        return billing.issue_bill(bill, actor=actor)

    def _pay(
        self,
        bill: Bill,
        *,
        method: str,
        amount,
        when,
        actor,
        txn_ref: str = "",
    ) -> Payment:
        payment = billing.collect_payment(
            bill,
            method=method,
            amount=amount,
            txn_ref=txn_ref,
            actor=actor,
        )
        self._backdate_payment(payment, when)
        return payment

    def _backdate_payment(self, payment: Payment, when) -> None:
        Payment.objects.filter(pk=payment.pk).update(paid_at=when)
        MoneyReceipt.objects.filter(payment=payment).update(issued_at=when)
        JournalEntry.objects.filter(
            source_type="billing.payment", source_id=str(payment.pk)
        ).update(date=when.date())

    def _backdate_advance(self, advance: Advance, when) -> None:
        Advance.objects.filter(pk=advance.pk).update(paid_at=when)
        JournalEntry.objects.filter(
            source_type="billing.advance", source_id=str(advance.pk)
        ).update(date=when.date())

    # ------------------------------------------------------------------
    # Lookups / utilities
    # ------------------------------------------------------------------
    def _at(self, day: dt.date, hour: int = 9, minute: int = 0):
        naive = dt.datetime.combine(day, time(hour, minute))
        return timezone.make_aware(naive, timezone.get_current_timezone())

    def _slot_for(self, doctor: Doctor, day: dt.date):
        return (
            AvailabilitySlot.objects.filter(
                doctor=doctor, weekday=day.weekday(), is_active=True
            )
            .order_by("start_time")
            .first()
        )

    def _free_bed(self, ward_name: str) -> Bed:
        bed = (
            Bed.objects.filter(ward__name=ward_name, status=BedStatus.AVAILABLE)
            .order_by("bed_no")
            .first()
        )
        if bed is None:
            raise CommandError(f"No available bed in {ward_name}.")
        return bed

    def _ot_room(self) -> OTRoom:
        room = OTRoom.objects.filter(name="OT-1").first()
        if room is None:
            room = OTRoom.objects.order_by("name").first()
        if room is None:
            raise CommandError("No OT room found — run seed_ot.")
        return room

    def _drug(self, generic: str, form: str) -> Drug:
        drug = Drug.objects.filter(generic_name=generic, form=form).first()
        if drug is None:
            raise CommandError(f"Drug {generic} ({form}) missing.")
        return drug

    def _lab_test(self, code: str) -> LabTest:
        test = LabTest.objects.filter(code=code).first()
        if test is None:
            raise CommandError(f"Lab test {code} missing.")
        return test

    def _radiology(self, code: str) -> RadiologyTest:
        test = RadiologyTest.objects.filter(code=code).first()
        if test is None:
            raise CommandError(f"Radiology test {code} missing.")
        return test

    def _procedure(self, code: str) -> Procedure:
        procedure = Procedure.objects.filter(code=code).first()
        if procedure is None:
            raise CommandError(f"Procedure {code} missing.")
        return procedure

    def _diagnosis(self, code: str) -> Diagnosis:
        diagnosis = Diagnosis.objects.filter(code=code).first()
        if diagnosis is None:
            raise CommandError(f"Diagnosis {code} missing.")
        return diagnosis

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def _print_summary(self, p1: Patient, p2: Patient) -> None:
        bills = Bill.objects.filter(patient__in=[p1, p2]).order_by("id")
        self.stdout.write(self.style.SUCCESS("Demo dataset seeded."))
        self.stdout.write(f"Patients: {p1.uhid} / {p2.uhid}")
        for bill in bills:
            due = bill.total - bill.paid_amount
            self.stdout.write(
                f"  {bill.bill_no} · {bill.bill_type} · total {bill.total} "
                f"· paid {bill.paid_amount} · due {due} · {bill.status}"
            )
        advance = Advance.objects.filter(patient=p1).first()
        if advance is not None:
            self.stdout.write(f"P1 advance balance: {advance.balance}")
        for admission in Admission.objects.filter(patient__in=[p1, p2]):
            self.stdout.write(
                f"  Admission {admission.ip_number or admission.pk} · "
                f"{admission.patient.full_name_en} · {admission.status}"
            )
        trial = trial_balance(as_of=self.today)
        self.stdout.write(
            f"Trial balance: Dr {trial['total_debit']} / Cr {trial['total_credit']} "
            f"(balanced={trial['is_balanced']})"
        )
        run = getattr(self, "payroll_run", None)
        if run is not None:
            self.stdout.write(
                f"Payroll {run.code}: {run.payslips.count()} payslips, "
                f"net {run.total_net}, status {run.status}"
            )
        for report_run in getattr(self, "report_runs", []):
            filename = report_run.file.name if report_run.file else "—"
            self.stdout.write(
                f"Report {report_run.report_type} ({report_run.report_format}): "
                f"{report_run.status} · {filename}"
            )
