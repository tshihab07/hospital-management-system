"""Read-only analytics for the Reports & Analytics module (RULES Phase 16).

Every function returns a *normalised report dictionary* so that the views,
exports (CSV/XLSX/PDF) and the scheduler can all render any report without
special-casing::

    {
        "key":         "daily_census",
        "title":       "Daily census",
        "description": "…",
        "start":       date | None,
        "end":         date | None,
        "columns":     ["Date", "Admissions", …],
        "rows":        [[…], …],
        "align":       ["left", "right", …],
        "formats":     ["date", "number", …],
        "totals":      [None, 12, …] | [],
        "summary":     [{"label": …, "value": …, "kind": "money"|"count"|…}],
        "chart":       {"type": "bar", "labels": […], "values": […] } | None,
        "meta":        {…},
    }

The data itself is never persisted — it is derived live from the operational
modules (billing, accounting, lab, pharmacy, HR, OT, IPD, ICU), which keeps the
control tower consistent with the systems of record.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import ReportType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MONEY = "money"
COUNT = "count"
PERCENT = "percent"
TEXT = "text"
NUMBER = "number"
DATE = "date"
DATETIME = "datetime"

_PAYMENT_METHODS = [
    ("cash", "Cash"),
    ("card", "Card"),
    ("bkash", "bKash"),
    ("nagad", "Nagad"),
    ("rocket", "Rocket"),
    ("bank", "Bank"),
]

_TRIAGE_ORDER = ["red", "orange", "yellow", "green", "blue"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dec(value) -> Decimal:
    return Decimal(str(value or "0"))


def default_range(*, parameters=None, default_days: int = 30) -> tuple[date, date]:
    """Resolve ``(start, end)`` from schedule parameters or sensible defaults."""
    params = parameters or {}
    end = _parse_date(params.get("end")) or timezone.localdate()
    start = _parse_date(params.get("start"))
    if start is None:
        days = params.get("range_days")
        try:
            days = int(days) if days else default_days
        except (TypeError, ValueError):
            days = default_days
        start = end - timedelta(days=days - 1)
    if start > end:  # pragma: no cover - defensive
        start, end = end, start
    return start, end


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    from django.utils.dateparse import parse_date

    return parse_date(str(value))


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    """List ``(year, month)`` pairs covering ``start`` … ``end``."""
    months: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    import calendar

    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _table(
    key: str,
    title: str,
    *,
    columns,
    rows,
    align=None,
    formats=None,
    totals=None,
    summary=None,
    chart=None,
    start=None,
    end=None,
    description="",
    meta=None,
) -> dict:
    if align is None:
        align = ["left"] + ["right"] * (len(columns) - 1)
    if formats is None:
        formats = [TEXT] * len(columns)
    return {
        "key": key,
        "title": title,
        "description": description,
        "start": start,
        "end": end,
        "columns": list(columns),
        "rows": [list(r) for r in rows],
        "align": list(align),
        "formats": list(formats),
        "totals": list(totals) if totals else [],
        "summary": list(summary) if summary else [],
        "chart": chart,
        "meta": meta or {},
    }


def _s(**entries) -> list[dict]:
    """Build a summary list from ``label=(value, kind)`` keyword pairs."""
    return [
        {"label": label, "value": value, "kind": kind}
        for label, (value, kind) in entries.items()
    ]


# ---------------------------------------------------------------------------
# Dashboard KPIs
# ---------------------------------------------------------------------------
def dashboard_kpis(*, day=None) -> dict:
    """Headline control-tower KPIs across every operational module."""
    day = day or timezone.localdate()
    return {
        "day": day,
        "patients": patient_kpis(day=day),
        "opd": opd_kpis(day=day),
        "ipd": ipd_kpis(),
        "er": er_kpis(day=day),
        "lab": lab_kpis(),
        "pharmacy": pharmacy_kpis(),
        "billing": billing_kpis(day=day),
        "accounting": accounting_kpis(day=day),
        "payroll": payroll_kpis(),
    }


def patient_kpis(*, day=None) -> dict:
    from apps.patients.models import Patient

    day = day or timezone.localdate()
    return {
        "total": Patient.objects.count(),
        "registered_today": Patient.objects.filter(created_at__date=day).count(),
        "registered_month": Patient.objects.filter(
            created_at__year=day.year, created_at__month=day.month
        ).count(),
    }


def opd_kpis(*, day=None) -> dict:
    from apps.opd.models import Appointment, AppointmentStatus

    day = day or timezone.localdate()
    today = Appointment.objects.filter(appt_date=day)
    return {
        "appointments_today": today.count(),
        "completed_today": today.filter(status=AppointmentStatus.COMPLETED).count(),
        "scheduled_today": today.filter(status=AppointmentStatus.SCHEDULED).count(),
        "cancelled_today": today.filter(status=AppointmentStatus.CANCELLED).count(),
    }


def ipd_kpis() -> dict:
    from apps.ipd.models import Admission, AdmissionStatus, Bed, BedStatus

    open_status = [AdmissionStatus.ADMITTED, AdmissionStatus.DISCHARGE_REQUESTED]
    total_beds = Bed.objects.count()
    occupied = Bed.objects.filter(status=BedStatus.OCCUPIED).count()
    return {
        "admitted": Admission.objects.filter(status__in=open_status).count(),
        "beds_total": total_beds,
        "beds_occupied": occupied,
        "beds_available": Bed.objects.filter(status=BedStatus.AVAILABLE).count(),
        "occupancy_pct": (
            round(occupied * 100 / total_beds, 1) if total_beds else Decimal("0")
        ),
    }


def er_kpis(*, day=None) -> dict:
    from apps.icu.models import EmergencyCase, EmergencyStatus

    day = day or timezone.localdate()
    open_cases = EmergencyCase.objects.exclude(
        status__in=[
            EmergencyStatus.DISCHARGED,
            EmergencyStatus.LEFT,
            EmergencyStatus.DECEASED,
        ]
    )
    waiting = open_cases.filter(status=EmergencyStatus.WAITING)
    oldest = waiting.order_by("arrival_time").first()
    return {
        "open_cases": open_cases.count(),
        "waiting": waiting.count(),
        "arrivals_today": EmergencyCase.objects.filter(
            arrival_time__date=day
        ).count(),
        "longest_wait": oldest.wait_minutes if oldest else 0,
    }


def lab_kpis() -> dict:
    from apps.emr.models import LabOrder, OrderStatus

    return {
        "pending": LabOrder.objects.filter(
            status__in=[OrderStatus.ORDERED, OrderStatus.IN_PROGRESS]
        ).count(),
        "completed_today": LabOrder.objects.filter(
            status=OrderStatus.COMPLETED, ordered_at__date=timezone.localdate()
        ).count(),
    }


def pharmacy_kpis() -> dict:
    from apps.pharmacy.models import DispenseRecord, StockBatch

    return {
        "dispenses_today": DispenseRecord.objects.filter(
            dispensed_at__date=timezone.localdate()
        ).count(),
        "stock_batches": StockBatch.objects.filter(is_active=True).count(),
    }


def billing_kpis(*, day=None) -> dict:
    from apps.billing.models import Bill, BillStatus, Payment

    day = day or timezone.localdate()
    billed = Bill.objects.exclude(status=BillStatus.CANCELLED)
    outstanding = sum((b.due_amount for b in billed), Decimal("0"))
    collected = Payment.objects.filter(paid_at__date=day).aggregate(
        total=Sum("amount")
    )["total"]
    return {
        "bills_today": Bill.objects.filter(created_at__date=day).count(),
        "open_bills": billed.exclude(status=BillStatus.PAID).count(),
        "collected_today": _dec(collected),
        "outstanding": outstanding,
    }


def accounting_kpis(*, day=None) -> dict:
    from apps.accounting import selectors as accounting

    day = day or timezone.localdate()
    start = day.replace(day=1)
    statement = accounting.income_statement(start=start, end=day)
    return {
        "revenue_mtd": statement["total_revenue"],
        "expense_mtd": statement["total_expense"],
        "net_income_mtd": statement["net_income"],
        "cash_and_bank": accounting.cash_and_bank_balance(),
    }


def payroll_kpis(*, year=None) -> dict:
    from apps.payroll.models import PayrollRun, PayrollRunStatus

    year = year or timezone.localdate().year
    runs = PayrollRun.objects.filter(year=year).exclude(
        status=PayrollRunStatus.CANCELLED
    )
    totals = runs.aggregate(
        gross=Sum("total_gross"), net=Sum("total_net"), tax=Sum("total_tax")
    )
    last = runs.order_by("-year", "-month", "-id").first()
    return {
        "runs": runs.count(),
        "gross": _dec(totals["gross"]),
        "net": _dec(totals["net"]),
        "tax": _dec(totals["tax"]),
        "last_run": last,
    }


def dashboard_alerts(*, day=None) -> list[dict]:
    """Operational alerts surfaced on the control-tower dashboard.

    Each alert is a small dict ``{level, title, count, url_name}`` where
    ``level`` is one of ``danger`` / ``warning`` / ``info``.
    """
    from django.utils.translation import gettext_lazy as _

    alerts: list[dict] = []

    try:
        from apps.pharmacy import selectors as pharmacy

        expired = pharmacy.expired_batches().count()
        if expired:
            alerts.append(
                {
                    "level": "danger",
                    "title": _("Expired stock batches"),
                    "count": expired,
                    "url_name": "pharmacy:expiry_alerts",
                }
            )
        expiring = pharmacy.expiring_batches(30).count()
        if expiring:
            alerts.append(
                {
                    "level": "warning",
                    "title": _("Batches expiring within 30 days"),
                    "count": expiring,
                    "url_name": "pharmacy:expiry_alerts",
                }
            )
        low = pharmacy.low_stock_drugs()
        if low:
            alerts.append(
                {
                    "level": "warning",
                    "title": _("Drugs below reorder level"),
                    "count": len(low),
                    "url_name": "pharmacy:stock_list",
                }
            )
    except Exception:  # pragma: no cover - defensive
        pass

    er = er_kpis(day=day)
    if er["waiting"] >= 5:
        alerts.append(
            {
                "level": "warning",
                "title": _("Emergency cases waiting"),
                "count": er["waiting"],
                "url_name": "icu:emergency_list",
            }
        )

    lab = lab_kpis()
    if lab["pending"]:
        alerts.append(
            {
                "level": "info",
                "title": _("Lab orders awaiting results"),
                "count": lab["pending"],
                "url_name": "lab:order_list",
            }
        )

    ipd = ipd_kpis()
    if ipd["occupancy_pct"] and ipd["occupancy_pct"] >= 90:
        alerts.append(
            {
                "level": "warning",
                "title": _("Bed occupancy above 90%"),
                "count": ipd["beds_occupied"],
                "url_name": "ipd:bed_map",
            }
        )

    return alerts


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------
def daily_census(*, start=None, end=None, **_) -> dict:
    """Day-by-day activity census across the hospital (RULES Phase 16)."""
    from apps.emr.models import LabOrder
    from apps.icu.models import EmergencyCase
    from apps.ipd.models import Admission, AdmissionStatus
    from apps.opd.models import Appointment, AppointmentStatus
    from apps.ot.models import Surgery, SurgeryStatus
    from apps.pharmacy.models import DispenseRecord, DispenseStatus

    end = end or timezone.localdate()
    start = start or end - timedelta(days=29)
    open_status = [AdmissionStatus.ADMITTED, AdmissionStatus.DISCHARGE_REQUESTED]

    rows = []
    totals = [0, 0, 0, 0, 0, 0, 0, 0]
    cursor = start
    while cursor <= end:
        admissions = Admission.objects.filter(admitted_at__date=cursor).count()
        discharges = Admission.objects.filter(discharged_at__date=cursor).count()
        inpatients = (
            Admission.objects.filter(status__in=open_status, admitted_at__date__lte=cursor)
            .filter(Q(discharged_at__isnull=True) | Q(discharged_at__date__gt=cursor))
            .count()
        )
        er = EmergencyCase.objects.filter(arrival_time__date=cursor).count()
        opd = Appointment.objects.filter(
            appt_date=cursor, status=AppointmentStatus.COMPLETED
        ).count()
        surgeries = (
            Surgery.objects.filter(scheduled_date=cursor)
            .exclude(status=SurgeryStatus.CANCELLED)
            .count()
        )
        lab = LabOrder.objects.filter(ordered_at__date=cursor).count()
        dispenses = DispenseRecord.objects.filter(
            dispensed_at__date=cursor, status=DispenseStatus.COMPLETED
        ).count()
        values = [admissions, discharges, inpatients, er, opd, surgeries, lab, dispenses]
        totals = [a + b for a, b in zip(totals, values)]
        rows.append([cursor, *values])
        cursor += timedelta(days=1)

    return _table(
        ReportType.DAILY_CENSUS,
        "Daily census",
        columns=[
            "Date",
            "Admissions",
            "Discharges",
            "Inpatients",
            "ER arrivals",
            "OPD visits",
            "Surgeries",
            "Lab orders",
            "Dispenses",
        ],
        align=["left"] + ["right"] * 8,
        formats=[DATE] + [NUMBER] * 8,
        rows=rows,
        totals=["Total", *totals],
        summary=_s(
            admissions=(totals[0], COUNT),
            discharges=(totals[1], COUNT),
            er_arrivals=(totals[3], COUNT),
            opd_visits=(totals[4], COUNT),
        ),
        chart={
            "type": "line",
            "labels": [r[0].strftime("%d/%m") for r in rows],
            "values": [r[5] for r in rows],
            "label": "OPD visits",
        },
        start=start,
        end=end,
        description="Daily patient flow: admissions, discharges, visits and "
        "diagnostic/theatre activity.",
    )


def monthly_revenue(*, start=None, end=None, **_) -> dict:
    """Revenue, collections, VAT and net income grouped by month."""
    from apps.accounting import selectors as accounting
    from apps.billing.models import Payment

    end = end or timezone.localdate()
    start = start or date(end.year, 1, 1)

    rows = []
    total_revenue = total_collection = total_vat = total_net = Decimal("0")
    labels = []
    values = []
    for year, month in _months_between(start, end):
        m_start, m_end = _month_bounds(year, month)
        statement = accounting.income_statement(start=m_start, end=m_end)
        vat = accounting.vat_return(start=m_start, end=m_end)
        collected = Payment.objects.filter(
            paid_at__date__gte=m_start, paid_at__date__lte=m_end
        ).aggregate(total=Sum("amount"))["total"]
        collected = _dec(collected)
        revenue = statement["total_revenue"]
        net = statement["net_income"]
        rows.append(
            [
                m_start.strftime("%b %Y"),
                revenue,
                collected,
                vat["output_vat"],
                statement["total_expense"],
                net,
            ]
        )
        labels.append(m_start.strftime("%b"))
        values.append(float(revenue))
        total_revenue += revenue
        total_collection += collected
        total_vat += vat["output_vat"]
        total_net += net

    return _table(
        ReportType.MONTHLY_REVENUE,
        "Monthly revenue",
        columns=["Month", "Revenue", "Collections", "Output VAT", "Expense", "Net"],
        align=["left"] + ["right"] * 5,
        formats=[TEXT, MONEY, MONEY, MONEY, MONEY, MONEY],
        rows=rows,
        totals=[
            "Total",
            total_revenue,
            total_collection,
            total_vat,
            "",
            total_net,
        ],
        summary=_s(
            revenue=(total_revenue, MONEY),
            collections=(total_collection, MONEY),
            vat=(total_vat, MONEY),
            net_income=(total_net, MONEY),
        ),
        chart={"type": "bar", "labels": labels, "values": values, "label": "Revenue"},
        start=start,
        end=end,
        description="Posted revenue, cash collections and net income per month.",
    )


def doctor_performance(*, start=None, end=None, **_) -> dict:
    """Patients seen, revenue generated and revenue-share per doctor."""
    from apps.opd.models import Appointment, AppointmentStatus, Doctor

    end = end or timezone.localdate()
    start = start or end - timedelta(days=29)

    agg = (
        Appointment.objects.filter(
            status=AppointmentStatus.COMPLETED,
            appt_date__gte=start,
            appt_date__lte=end,
            doctor__isnull=False,
        )
        .values("doctor_id")
        .annotate(seen=Count("id"), revenue=Sum("consultation_fee"))
    )
    by_id = {row["doctor_id"]: row for row in agg}
    doctors = {d.pk: d for d in Doctor.objects.all()}

    rows = []
    total_seen = 0
    total_rev = Decimal("0")
    total_share = Decimal("0")
    for doctor_id, row in by_id.items():
        doctor = doctors.get(doctor_id)
        if doctor is None:
            continue
        revenue = _dec(row["revenue"])
        share_pct = _dec(getattr(doctor, "revenue_share_pct", 0))
        share = (revenue * share_pct / Decimal("100")).quantize(Decimal("0.01"))
        rows.append(
            [
                doctor.name_en,
                getattr(doctor.department, "name", "") if doctor.department_id else "",
                row["seen"],
                revenue,
                share_pct,
                share,
            ]
        )
        total_seen += row["seen"]
        total_rev += revenue
        total_share += share

    rows.sort(key=lambda r: r[3], reverse=True)
    return _table(
        ReportType.DOCTOR_PERFORMANCE,
        "Doctor performance",
        columns=["Doctor", "Department", "Patients seen", "Revenue", "Share %", "Share"],
        align=["left", "left"] + ["right"] * 4,
        formats=[TEXT, TEXT, NUMBER, MONEY, PERCENT, MONEY],
        rows=rows,
        totals=["Total", "", total_seen, total_rev, "", total_share],
        summary=_s(
            doctors=(len(rows), COUNT),
            patients_seen=(total_seen, COUNT),
            revenue=(total_rev, MONEY),
            revenue_share=(total_share, MONEY),
        ),
        chart={
            "type": "bar",
            "labels": [r[0] for r in rows[:10]],
            "values": [float(r[3]) for r in rows[:10]],
            "label": "Revenue",
        },
        start=start,
        end=end,
        description="Completed consultations and generated revenue per physician.",
    )


def department_profitability(*, start=None, end=None, **_) -> dict:
    """Revenue, expense, profit and margin by clinical department."""
    from apps.accounting import selectors as accounting

    end = end or timezone.localdate()
    start = start or date(end.year, end.month, 1)

    data = accounting.department_profitability(start=start, end=end)
    rows = []
    total_rev = total_exp = total_profit = Decimal("0")
    for row in data:
        margin = (
            (row["profit"] * 100 / row["revenue"]).quantize(Decimal("0.1"))
            if row["revenue"]
            else Decimal("0")
        )
        rows.append(
            [row["department"], row["revenue"], row["expense"], row["profit"], margin]
        )
        total_rev += row["revenue"]
        total_exp += row["expense"]
        total_profit += row["profit"]

    rows.sort(key=lambda r: r[3], reverse=True)
    return _table(
        ReportType.DEPARTMENT_PROFITABILITY,
        "Department profitability",
        columns=["Department", "Revenue", "Expense", "Profit", "Margin %"],
        align=["left"] + ["right"] * 4,
        formats=[TEXT, MONEY, MONEY, MONEY, PERCENT],
        rows=rows,
        totals=["Total", total_rev, total_exp, total_profit, ""],
        summary=_s(
            revenue=(total_rev, MONEY),
            expense=(total_exp, MONEY),
            profit=(total_profit, MONEY),
            margin=(
                (total_profit * 100 / total_rev).quantize(Decimal("0.1"))
                if total_rev
                else Decimal("0"),
                PERCENT,
            ),
        ),
        chart={
            "type": "bar",
            "labels": [r[0] for r in rows],
            "values": [float(r[3]) for r in rows],
            "label": "Profit",
        },
        start=start,
        end=end,
        description="Posted revenue and expense attributed to each department.",
    )


def inventory_consumption(*, start=None, end=None, **_) -> dict:
    """Pharmacy stock consumed (dispensed, transferred or adjusted)."""
    from apps.pharmacy.models import MovementType, StockMovement

    end = end or timezone.localdate()
    start = start or end - timedelta(days=29)
    out_types = [
        MovementType.DISPENSE,
        MovementType.TRANSFER_OUT,
        MovementType.ADJUSTMENT,
        MovementType.RETURN,
    ]
    movements = (
        StockMovement.objects.filter(
            moved_at__date__gte=start,
            moved_at__date__lte=end,
            quantity__lt=0,
            movement_type__in=out_types,
        )
        .select_related("batch__drug")
        .order_by("moved_at")
    )
    agg: dict[int, dict] = {}
    for move in movements:
        drug = move.batch.drug
        entry = agg.setdefault(
            drug.pk,
            {
                "name": drug.generic_name,
                "brand": drug.brand_name,
                "unit": drug.unit,
                "quantity": 0,
                "value": Decimal("0"),
                "moves": 0,
            },
        )
        qty = abs(move.quantity)
        entry["quantity"] += qty
        entry["value"] += _dec(move.batch.purchase_price) * qty
        entry["moves"] += 1

    rows = sorted(
        [
            [e["name"], e["brand"], e["unit"], e["quantity"], e["value"], e["moves"]]
            for e in agg.values()
        ],
        key=lambda r: r[4],
        reverse=True,
    )
    total_qty = sum(r[3] for r in rows)
    total_value = sum((r[4] for r in rows), Decimal("0"))
    return _table(
        ReportType.INVENTORY_CONSUMPTION,
        "Inventory consumption",
        columns=["Drug", "Brand", "Unit", "Quantity", "Value", "Movements"],
        align=["left", "left", "left"] + ["right"] * 3,
        formats=[TEXT, TEXT, TEXT, NUMBER, MONEY, NUMBER],
        rows=rows,
        totals=["Total", "", "", total_qty, total_value, ""],
        summary=_s(
            drugs=(len(rows), COUNT),
            quantity=(total_qty, NUMBER),
            value=(total_value, MONEY),
        ),
        chart={
            "type": "bar",
            "labels": [r[0] for r in rows[:10]],
            "values": [float(r[4]) for r in rows[:10]],
            "label": "Value consumed",
        },
        start=start,
        end=end,
        description="Pharmacy stock issued to patients and wards, valued at cost.",
    )


def bed_occupancy(*, start=None, end=None, **_) -> dict:
    """Ward-wise bed occupancy heatmap (RULES Phase 16)."""
    from apps.ipd.models import Bed, BedStatus, Ward

    wards = Ward.objects.filter(is_active=True).order_by("name")
    rows = []
    beds_total = occupied_total = available_total = maintenance_total = 0
    for ward in wards:
        beds = Bed.objects.filter(ward=ward)
        total = beds.count()
        occupied = beds.filter(status=BedStatus.OCCUPIED).count()
        available = beds.filter(status=BedStatus.AVAILABLE).count()
        maintenance = beds.filter(status=BedStatus.MAINTENANCE).count()
        occupancy = round(occupied * 100 / total, 1) if total else Decimal("0")
        rows.append(
            [
                ward.name,
                ward.get_ward_type_display(),
                total,
                occupied,
                available,
                maintenance,
                occupancy,
            ]
        )
        beds_total += total
        occupied_total += occupied
        available_total += available
        maintenance_total += maintenance
    overall = round(occupied_total * 100 / beds_total, 1) if beds_total else Decimal("0")
    return _table(
        ReportType.BED_OCCUPANCY,
        "Bed occupancy",
        columns=[
            "Ward",
            "Type",
            "Beds",
            "Occupied",
            "Available",
            "Maintenance",
            "Occupancy %",
        ],
        align=["left", "left"] + ["right"] * 5,
        formats=[TEXT, TEXT, NUMBER, NUMBER, NUMBER, NUMBER, PERCENT],
        rows=rows,
        totals=[
            "Total",
            "",
            beds_total,
            occupied_total,
            available_total,
            maintenance_total,
            overall,
        ],
        summary=_s(
            beds=(beds_total, COUNT),
            occupied=(occupied_total, COUNT),
            available=(available_total, COUNT),
            occupancy=(overall, PERCENT),
        ),
        chart={
            "type": "bar",
            "labels": [r[0] for r in rows],
            "values": [float(r[6]) for r in rows],
            "label": "Occupancy %",
        },
        start=start,
        end=end,
        description="Live bed capacity and occupancy by ward.",
    )


def er_wait_times(*, start=None, end=None, **_) -> dict:
    """Emergency department wait-time analytics (RULES Phase 16)."""
    from apps.icu.models import EmergencyCase

    end = end or timezone.localdate()
    start = start or end - timedelta(days=29)
    cases = (
        EmergencyCase.objects.filter(
            arrival_time__date__gte=start, arrival_time__date__lte=end
        )
        .select_related("patient")
        .order_by("-arrival_time")
    )
    rows = []
    waits = []
    triage_counts = {level: 0 for level in _TRIAGE_ORDER}
    for case in cases:
        wait = case.wait_minutes
        waits.append(wait)
        triage_counts[case.triage_level] = triage_counts.get(case.triage_level, 0) + 1
        rows.append(
            [
                case.case_no or f"ER-{case.pk}",
                case.patient.display_name,
                case.get_triage_level_display(),
                timezone.localtime(case.arrival_time),
                wait,
                case.get_status_display(),
            ]
        )
    longest = max(waits) if waits else 0
    average = round(sum(waits) / len(waits), 1) if waits else Decimal("0")
    return _table(
        ReportType.ER_WAIT_TIMES,
        "ER wait times",
        columns=["Case", "Patient", "Triage", "Arrival", "Wait (min)", "Status"],
        align=["left", "left", "left", "left", "right", "left"],
        formats=[TEXT, TEXT, TEXT, DATETIME, NUMBER, TEXT],
        rows=rows,
        totals=["", "", "", "", longest, ""],
        summary=_s(
            cases=(len(rows), COUNT),
            average_wait=(average, NUMBER),
            longest_wait=(longest, NUMBER),
        ),
        chart={
            "type": "doughnut",
            "labels": [level.title() for level in _TRIAGE_ORDER],
            "values": [triage_counts.get(level, 0) for level in _TRIAGE_ORDER],
            "label": "Cases by triage",
        },
        start=start,
        end=end,
        description="Arrival-to-disposition waiting time by triage acuity.",
    )


def vat_return(*, start=None, end=None, **_) -> dict:
    """VAT return summary (output, input and net payable)."""
    from apps.accounting import selectors as accounting

    end = end or timezone.localdate()
    start = start or date(end.year, end.month, 1)
    vat = accounting.vat_return(start=start, end=end)
    rows = [
        ["Output VAT (sales)", vat["output_vat"]],
        ["Input VAT (purchases)", vat["input_vat"]],
        ["Net VAT payable", vat["net_payable"]],
    ]
    return _table(
        ReportType.VAT,
        "VAT return",
        columns=["Item", "Amount"],
        align=["left", "right"],
        formats=[TEXT, MONEY],
        rows=rows,
        summary=_s(
            output_vat=(vat["output_vat"], MONEY),
            input_vat=(vat["input_vat"], MONEY),
            net_payable=(vat["net_payable"], MONEY),
        ),
        start=start,
        end=end,
        description="VAT charged on sales, VAT recoverable on purchases and the "
        "net position for the period.",
    )


def collection(*, start=None, end=None, **_) -> dict:
    """Daily collection matrix by payment channel."""
    from apps.billing.models import Payment

    end = end or timezone.localdate()
    start = start or end - timedelta(days=29)
    totals_by_method = {key: Decimal("0") for key, _ in _PAYMENT_METHODS}
    by_day: dict[date, dict[str, Decimal]] = {}
    payments = Payment.objects.filter(
        paid_at__date__gte=start, paid_at__date__lte=end
    ).values("paid_at__date", "method", "amount")
    for row in payments:
        day = row["paid_at__date"]
        method = row["method"]
        amount = _dec(row["amount"])
        bucket = by_day.setdefault(day, {})
        bucket[method] = bucket.get(method, Decimal("0")) + amount
        totals_by_method[method] = totals_by_method.get(method, Decimal("0")) + amount

    rows = []
    grand = Decimal("0")
    for day in sorted(by_day):
        bucket = by_day[day]
        day_total = sum((bucket.get(k, Decimal("0")) for k, _ in _PAYMENT_METHODS), Decimal("0"))
        rows.append(
            [day, *[bucket.get(key, Decimal("0")) for key, _ in _PAYMENT_METHODS], day_total]
        )
        grand += day_total

    columns = ["Date", *[label for _, label in _PAYMENT_METHODS], "Total"]
    totals = [
        "Total",
        *[totals_by_method.get(key, Decimal("0")) for key, _ in _PAYMENT_METHODS],
        grand,
    ]
    summary = [
        {"label": label, "value": totals_by_method.get(key, Decimal("0")), "kind": MONEY}
        for key, label in _PAYMENT_METHODS
    ]
    summary.append({"label": "Total collected", "value": grand, "kind": MONEY})
    return _table(
        ReportType.COLLECTION,
        "Collection",
        columns=columns,
        align=["left"] + ["right"] * (len(columns) - 1),
        formats=[DATE] + [MONEY] * (len(columns) - 1),
        rows=rows,
        totals=totals,
        summary=summary,
        chart={
            "type": "doughnut",
            "labels": [label for _, label in _PAYMENT_METHODS],
            "values": [float(totals_by_method.get(key, Decimal("0"))) for key, _ in _PAYMENT_METHODS],
            "label": "Collection by channel",
        },
        start=start,
        end=end,
        description="Patient collections per day broken down by payment channel.",
    )


def payroll_register(*, start=None, end=None, **_) -> dict:
    """Payroll register: per-run salary totals for the period."""
    from apps.payroll.models import PayrollRun, PayrollRunStatus

    end = end or timezone.localdate()
    start = start or date(end.year, 1, 1)
    runs = (
        PayrollRun.objects.filter(period_start__lte=end, period_end__gte=start)
        .exclude(status=PayrollRunStatus.CANCELLED)
        .select_related("approved_by", "paid_by")
        .order_by("year", "month")
    )
    rows = []
    totals = [0, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")]
    for run in runs:
        rows.append(
            [
                run.code,
                f"{run.period_start.strftime('%b %Y')}",
                run.employee_count,
                run.total_gross,
                run.total_deductions,
                run.total_tax,
                run.total_pf_employee,
                run.total_net,
            ]
        )
        totals[0] += run.employee_count
        totals[1] += run.total_gross
        totals[2] += run.total_deductions
        totals[3] += run.total_tax
        totals[4] += run.total_pf_employee
        totals[5] += run.total_net
    return _table(
        ReportType.PAYROLL,
        "Payroll register",
        columns=[
            "Run",
            "Period",
            "Employees",
            "Gross",
            "Deductions",
            "Tax",
            "PF (employee)",
            "Net pay",
        ],
        align=["left", "left"] + ["right"] * 6,
        formats=[TEXT, TEXT, NUMBER, MONEY, MONEY, MONEY, MONEY, MONEY],
        rows=rows,
        totals=["Total", "", *totals],
        summary=_s(
            runs=(len(rows), COUNT),
            gross=(totals[1], MONEY),
            deductions=(totals[2], MONEY),
            net=(totals[5], MONEY),
        ),
        chart={
            "type": "bar",
            "labels": [r[1] for r in rows],
            "values": [float(r[7]) for r in rows],
            "label": "Net pay",
        },
        start=start,
        end=end,
        description="Salary runs processed in the period with gross, deductions "
        "and net pay.",
    )


def profit_and_loss(*, start=None, end=None, **_) -> dict:
    """Profit & loss statement from the general ledger (RULES Phase 16)."""
    from apps.accounting import selectors as accounting

    end = end or timezone.localdate()
    start = start or date(end.year, 1, 1)
    statement = accounting.income_statement(start=start, end=end)
    rows = []
    for row in statement["revenue_rows"]:
        rows.append(["Revenue", row["account"].name, row["amount"]])
    rows.append(["Revenue", "Total revenue", statement["total_revenue"]])
    for row in statement["expense_rows"]:
        rows.append(["Expense", row["account"].name, row["amount"]])
    rows.append(["Expense", "Total expense", statement["total_expense"]])
    rows.append(["Result", "Net income", statement["net_income"]])
    margin = (
        (statement["net_income"] * 100 / statement["total_revenue"]).quantize(
            Decimal("0.1")
        )
        if statement["total_revenue"]
        else Decimal("0")
    )
    return _table(
        ReportType.PNL,
        "Profit & loss",
        columns=["Section", "Account", "Amount"],
        align=["left", "left", "right"],
        formats=[TEXT, TEXT, MONEY],
        rows=rows,
        summary=_s(
            revenue=(statement["total_revenue"], MONEY),
            expense=(statement["total_expense"], MONEY),
            net_income=(statement["net_income"], MONEY),
            margin=(margin, PERCENT),
        ),
        chart={
            "type": "bar",
            "labels": ["Revenue", "Expense", "Net income"],
            "values": [
                float(statement["total_revenue"]),
                float(statement["total_expense"]),
                float(statement["net_income"]),
            ],
            "label": "Amount",
        },
        start=start,
        end=end,
        description="Revenue and expenses for the period with the resulting "
        "net income.",
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
BUILDERS = {
    ReportType.DAILY_CENSUS: daily_census,
    ReportType.MONTHLY_REVENUE: monthly_revenue,
    ReportType.DOCTOR_PERFORMANCE: doctor_performance,
    ReportType.DEPARTMENT_PROFITABILITY: department_profitability,
    ReportType.INVENTORY_CONSUMPTION: inventory_consumption,
    ReportType.BED_OCCUPANCY: bed_occupancy,
    ReportType.ER_WAIT_TIMES: er_wait_times,
    ReportType.VAT: vat_return,
    ReportType.COLLECTION: collection,
    ReportType.PAYROLL: payroll_register,
    ReportType.PNL: profit_and_loss,
}


def build_report(report_type: str, *, start=None, end=None) -> dict:
    """Build the normalised report dict for ``report_type``.

    ``KPI_SUMMARY`` is a dashboard-only report and is not a flat table, so it
    falls back to the daily census when requested for export.
    """
    builder = BUILDERS.get(report_type, daily_census)
    return builder(start=start, end=end)
