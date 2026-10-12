"""Seed HR sample data: shifts, leave types, staff, roster, attendance, leave."""

from __future__ import annotations

import datetime as dt
import random
from datetime import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.hr import services
from apps.hr.models import (AttendanceStatus, LeaveType, Shift, Staff,
                            StaffStatus)
from apps.masters.models import Department, Designation

SHIFTS = [
    {
        "name": "Morning",
        "code": "MORN",
        "start_time": time(8, 0),
        "end_time": time(14, 0),
        "is_night": False,
    },
    {
        "name": "Evening",
        "code": "EVE",
        "start_time": time(14, 0),
        "end_time": time(20, 0),
        "is_night": False,
    },
    {
        "name": "Night",
        "code": "NIGHT",
        "start_time": time(20, 0),
        "end_time": time(8, 0),
        "is_night": True,
    },
    {
        "name": "General",
        "code": "GEN",
        "start_time": time(9, 0),
        "end_time": time(17, 0),
        "is_night": False,
    },
]

LEAVE_TYPES = [
    {"name": "Casual Leave", "code": "CL", "max_days_per_year": 10, "is_paid": True},
    {"name": "Sick Leave", "code": "SL", "max_days_per_year": 14, "is_paid": True},
    {"name": "Earned Leave", "code": "EL", "max_days_per_year": 20, "is_paid": True},
    {
        "name": "Leave Without Pay",
        "code": "LWP",
        "max_days_per_year": 30,
        "is_paid": False,
    },
]

STAFF = [
    {
        "employee_code": "EMP-1001",
        "name_en": "Rahima Begum",
        "name_bn": "রহিমা বেগম",
        "desig": "Senior Nurse",
        "salary": "25000.00",
    },
    {
        "employee_code": "EMP-1002",
        "name_en": "Sabbir Ahmed",
        "name_bn": "সাব্বির আহমেদ",
        "desig": "Lab Technician",
        "salary": "22000.00",
    },
    {
        "employee_code": "EMP-1003",
        "name_en": "Nasrin Akter",
        "name_bn": "নাসরিন আক্তার",
        "desig": "Receptionist",
        "salary": "18000.00",
    },
    {
        "employee_code": "EMP-1004",
        "name_en": "Jahid Hasan",
        "name_bn": "জাহিদ হাসান",
        "desig": "Accountant",
        "salary": "30000.00",
    },
    {
        "employee_code": "EMP-1005",
        "name_en": "Mizanur Rahman",
        "name_bn": "মিজানুর রহমান",
        "desig": "Ward Boy",
        "salary": "15000.00",
    },
]


class Command(BaseCommand):
    help = "Seed sample shifts, leave types, staff, roster, attendance and leave."

    def handle(self, *args, **options):
        shifts = self._seed_shifts()
        self._seed_leave_types()
        staff = self._seed_staff(shifts)
        self._seed_roster(staff, shifts)
        self._seed_attendance(staff)
        self._seed_leave(staff)
        self.stdout.write(self.style.SUCCESS("HR sample data seeded."))

    def _seed_shifts(self):
        shifts = {}
        for spec in SHIFTS:
            shift, _ = Shift.objects.get_or_create(code=spec["code"], defaults=spec)
            shifts[spec["code"]] = shift
        self.stdout.write(f"Shifts: {Shift.objects.count()} total.")
        return shifts

    def _seed_leave_types(self):
        for spec in LEAVE_TYPES:
            LeaveType.objects.get_or_create(code=spec["code"], defaults=spec)
        self.stdout.write(f"Leave types: {LeaveType.objects.count()} total.")

    def _seed_staff(self, shifts):
        department = Department.objects.filter(is_active=True).first()
        staff = []
        for index, spec in enumerate(STAFF):
            designation = self._designation(spec["desig"])
            code = spec["employee_code"]
            member, _ = Staff.objects.get_or_create(
                employee_code=code,
                defaults={
                    "name_en": spec["name_en"],
                    "name_bn": spec["name_bn"],
                    "department": department,
                    "designation": designation,
                    "employment_type": "permanent",
                    "status": StaffStatus.ACTIVE,
                    "shift": shifts["GEN"] if index % 2 == 0 else shifts["MORN"],
                    "basic_salary": spec["salary"],
                    "house_rent": "0.00",
                    "medical_allowance": "1000.00",
                    "transport_allowance": "800.00",
                },
            )
            staff.append(member)
        self.stdout.write(f"Staff: {Staff.objects.count()} total.")
        return staff

    def _designation(self, name: str) -> Designation:
        existing = Designation.objects.filter(name__iexact=name).first()
        if existing is not None:
            return existing
        base = "".join(word[0] for word in name.split()).upper() or name[:3].upper()
        base = base[:20]
        code = base
        counter = 1
        while Designation.objects.filter(code=code).exists():
            counter += 1
            code = f"{base[:17]}{counter}"
        return Designation.objects.create(name=name, code=code)

    def _seed_roster(self, staff, shifts):
        today = timezone.localdate()
        monday = today - dt.timedelta(days=today.weekday())
        codes = list(shifts.keys())
        made = 0
        for index, member in enumerate(staff):
            for offset in range(6):
                shift = shifts[codes[(index + offset) % len(codes)]]
                services.assign_roster(
                    staff=member,
                    shift=shift,
                    dates=[monday + dt.timedelta(days=offset)],
                )
                made += 1
        self.stdout.write(f"Roster entries assigned: {made}.")

    def _seed_attendance(self, staff):
        today = timezone.localdate()
        random.seed(42)
        created = 0
        for day_offset in range(1, 8):
            att_date = today - dt.timedelta(days=day_offset)
            if att_date.weekday() == 6:  # skip Sunday
                continue
            for member in staff:
                status = AttendanceStatus.PRESENT
                check_in, check_out = time(9, 0), time(17, 0)
                roll = random.random()
                if roll < 0.08:
                    status, check_in, check_out = AttendanceStatus.ABSENT, None, None
                elif roll < 0.18:
                    status, check_in = AttendanceStatus.LATE, time(9, 45)
                services.upsert_attendance(
                    staff=member,
                    att_date=att_date,
                    status=status,
                    check_in=check_in,
                    check_out=check_out,
                )
                created += 1
        self.stdout.write(f"Attendance rows upserted: {created}.")

    def _seed_leave(self, staff):
        from apps.hr.models import LeaveRequest

        if LeaveRequest.objects.exists():
            self.stdout.write("Leave requests already exist – skipped.")
            return
        casual = LeaveType.objects.filter(code="CL").first()
        sick = LeaveType.objects.filter(code="SL").first()
        today = timezone.localdate()
        samples = [
            (
                staff[0],
                casual,
                today + dt.timedelta(days=5),
                today + dt.timedelta(days=6),
                "Family event",
            ),
            (
                staff[1],
                sick,
                today + dt.timedelta(days=2),
                today + dt.timedelta(days=2),
                "Fever",
            ),
        ]
        made = 0
        for member, leave_type, start, end, reason in samples:
            try:
                leave = services.apply_leave(
                    staff=member,
                    leave_type=leave_type,
                    start_date=start,
                    end_date=end,
                    reason=reason,
                )
                if made == 0:
                    services.approve_leave(leave=leave, note="Approved by seed")
                made += 1
            except ValueError as exc:  # pragma: no cover - defensive
                self.stderr.write(f"Skipped a leave request: {exc}")
        self.stdout.write(f"Leave requests seeded: {made}.")
