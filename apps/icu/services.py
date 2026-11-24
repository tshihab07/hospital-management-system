"""Write operations for ICU / Emergency (atomic + audit).

Every mutation runs inside a transaction and writes an :class:`AuditLog`
entry (RULES §4.4.1). Emergency case numbers use a row-locked per-year
:class:`EmergencySequence` counter, mirroring the UHID/IP generators.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.audit import AuditAction, log_action, model_to_dict_safe

from . import notifications
from .models import (AlertStatus, CodeBlueAlert, CodeBlueStatus, CriticalAlert,
                     CriticalScore, EmergencyCase, EmergencySequence,
                     EmergencyStatus, HandoverNote, IcuRecord, ScoreType)


def _to_decimal(value):
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _to_int(value):
    if value is None or value == "":
        return None
    return int(value)


# ---------------------------------------------------------------------------
# Emergency case numbering
# ---------------------------------------------------------------------------
@transaction.atomic
def generate_er_number(now=None) -> str:
    """Mint an ``ER-YYYY-NNNNN`` case number atomically."""
    from django.conf import settings

    now = now or timezone.localtime()
    year = now.year
    seq, _created = EmergencySequence.objects.select_for_update().get_or_create(
        year=year
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    width = int(settings.IHMS.get("ER_NUMBER_WIDTH", 5))
    prefix = settings.IHMS.get("ER_PREFIX", "ER")
    return f"{prefix}-{year}-{seq.last_number:0{width}d}"


# ---------------------------------------------------------------------------
# Critical care charting
# ---------------------------------------------------------------------------
@transaction.atomic
def create_icu_record(*, admission, data: dict, actor=None, request=None) -> IcuRecord:
    """Chart an ICU entry and raise alerts for any critical values."""
    record = IcuRecord(
        admission=admission,
        recorded_at=data.get("recorded_at") or timezone.now(),
        temperature=_to_decimal(data.get("temperature")),
        pulse=_to_int(data.get("pulse")),
        respiratory_rate=_to_int(data.get("respiratory_rate")),
        bp_systolic=_to_int(data.get("bp_systolic")),
        bp_diastolic=_to_int(data.get("bp_diastolic")),
        spo2=_to_int(data.get("spo2")),
        gcs=_to_int(data.get("gcs")),
        ventilator_mode=data.get("ventilator_mode") or "",
        fio2=_to_decimal(data.get("fio2")),
        peep=_to_int(data.get("peep")),
        tidal_volume=_to_int(data.get("tidal_volume")),
        set_rate=_to_int(data.get("set_rate")),
        intake_ml=_to_int(data.get("intake_ml")),
        output_ml=_to_int(data.get("output_ml")),
        notes=data.get("notes", ""),
        charted_by=actor if getattr(actor, "pk", None) else None,
    )
    record.full_clean(exclude=["admission"])
    record.save()
    log_action(
        AuditAction.CREATE,
        instance=record,
        changes=model_to_dict_safe(record),
        user=actor,
        request=request,
    )
    _raise_critical_alerts(record, actor=actor, request=request)
    return record


def _raise_critical_alerts(record: IcuRecord, *, actor=None, request=None) -> list:
    """Create + notify an alert for every critical finding on a chart."""
    alerts = []
    for finding in record.critical_findings:
        alert = CriticalAlert.objects.create(
            admission=record.admission,
            icu_record=record,
            parameter=finding["parameter"],
            value=str(finding["value"]),
            severity=finding["severity"],
            message=_("Critical %(param)s: %(value)s")
            % {"param": finding["parameter"], "value": finding["value"]},
        )
        alert.notified_to = ", ".join(notifications.critical_recipients(alert))
        notifications.send_critical_alert(alert)
        alert.save(update_fields=["notified_to", "updated_at"])
        log_action(
            AuditAction.CREATE,
            instance=alert,
            changes=model_to_dict_safe(alert),
            user=actor,
            request=request,
        )
        alerts.append(alert)
    return alerts


@transaction.atomic
def acknowledge_alert(
    *, alert: CriticalAlert, actor=None, request=None
) -> CriticalAlert:
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_by = actor if getattr(actor, "pk", None) else None
    alert.acknowledged_at = timezone.now()
    alert.save(
        update_fields=["status", "acknowledged_by", "acknowledged_at", "updated_at"]
    )
    log_action(
        AuditAction.UPDATE,
        instance=alert,
        changes=model_to_dict_safe(alert),
        user=actor,
        request=request,
    )
    return alert


@transaction.atomic
def resolve_alert(*, alert: CriticalAlert, actor=None, request=None) -> CriticalAlert:
    alert.status = AlertStatus.RESOLVED
    if not alert.acknowledged_at:
        alert.acknowledged_by = actor if getattr(actor, "pk", None) else None
        alert.acknowledged_at = timezone.now()
    alert.save(
        update_fields=["status", "acknowledged_by", "acknowledged_at", "updated_at"]
    )
    log_action(
        AuditAction.UPDATE,
        instance=alert,
        changes=model_to_dict_safe(alert),
        user=actor,
        request=request,
    )
    return alert


# ---------------------------------------------------------------------------
# APACHE II / SOFA scoring
# ---------------------------------------------------------------------------
def _band(value, bands):
    """Return points for the last band whose upper bound is >= value."""
    if value is None:
        return 0
    for upper, points in bands:
        if value <= upper:
            return points
    return bands[-1][1]


def calculate_apache_ii(data: dict) -> tuple[int, dict]:
    """Calculate an APACHE II score from a dict of inputs (aid, not authority)."""
    b: dict[str, int] = {}

    def t(v):
        return Decimal(str(v)) if v not in (None, "") else None

    temp = t(data.get("temperature"))
    if temp is not None:
        if temp >= 41:
            b["temperature"] = 4
        elif temp >= 39:
            b["temperature"] = 3
        elif temp >= 38.5:
            b["temperature"] = 1
        elif temp >= 36:
            b["temperature"] = 0
        elif temp >= 34:
            b["temperature"] = 1
        elif temp >= 32:
            b["temperature"] = 2
        elif temp >= 30:
            b["temperature"] = 3
        else:
            b["temperature"] = 4

    mapv = t(data.get("map"))
    if mapv is not None:
        b["map"] = _band(
            mapv, [(49, 4), (69, 2), (109, 0), (129, 2), (159, 3), (10**9, 4)]
        )

    hr = t(data.get("heart_rate"))
    if hr is not None:
        b["heart_rate"] = _band(
            hr, [(39, 4), (54, 3), (69, 2), (109, 0), (139, 2), (179, 3), (10**9, 4)]
        )

    rr = t(data.get("respiratory_rate"))
    if rr is not None:
        b["respiratory_rate"] = _band(
            rr, [(5, 4), (9, 2), (11, 1), (24, 0), (34, 1), (49, 3), (10**9, 4)]
        )

    pao2 = t(data.get("pao2"))
    if pao2 is not None:
        b["pao2"] = _band(pao2, [(54, 4), (60, 3), (70, 1), (10**9, 0)])

    ph = t(data.get("ph"))
    if ph is not None:
        b["ph"] = _band(
            ph,
            [
                (Decimal("7.14"), 4),
                (Decimal("7.24"), 3),
                (Decimal("7.32"), 2),
                (Decimal("7.49"), 0),
                (Decimal("7.59"), 1),
                (Decimal("7.69"), 3),
                (Decimal("99"), 4),
            ],
        )

    na = t(data.get("sodium"))
    if na is not None:
        b["sodium"] = _band(
            na,
            [
                (110, 4),
                (119, 3),
                (129, 2),
                (149, 0),
                (154, 1),
                (159, 2),
                (179, 3),
                (10**9, 4),
            ],
        )

    k = t(data.get("potassium"))
    if k is not None:
        b["potassium"] = _band(
            k,
            [
                (Decimal("2.49"), 4),
                (Decimal("2.99"), 2),
                (Decimal("3.49"), 1),
                (Decimal("5.4"), 0),
                (Decimal("5.9"), 1),
                (Decimal("6.9"), 3),
                (Decimal("99"), 4),
            ],
        )

    cr = t(data.get("creatinine"))
    if cr is not None:
        acute = bool(data.get("acute_renal_failure"))
        if cr >= 3.5:
            b["creatinine"] = 8 if acute else 4
        elif cr >= 2:
            b["creatinine"] = 6 if acute else 3
        elif cr >= 1.5:
            b["creatinine"] = 4 if acute else 2
        elif cr >= 0.6:
            b["creatinine"] = 0
        else:
            b["creatinine"] = 4 if acute else 2

    hct = t(data.get("hematocrit"))
    if hct is not None:
        b["hematocrit"] = _band(
            hct, [(19, 4), (29, 2), (45, 0), (49, 1), (59, 2), (10**9, 4)]
        )

    wbc = t(data.get("wbc"))
    if wbc is not None:
        b["wbc"] = _band(
            wbc,
            [
                (Decimal("0.99"), 4),
                (Decimal("2.99"), 2),
                (Decimal("14.9"), 0),
                (Decimal("19.9"), 1),
                (Decimal("39.9"), 2),
                (Decimal("999"), 4),
            ],
        )

    gcs = t(data.get("gcs"))
    if gcs is not None:
        b["gcs"] = int(15 - gcs)

    age = t(data.get("age"))
    if age is not None:
        if age <= 44:
            b["age"] = 0
        elif age <= 54:
            b["age"] = 2
        elif age <= 64:
            b["age"] = 3
        elif age <= 74:
            b["age"] = 5
        else:
            b["age"] = 6

    chronic = _to_int(data.get("chronic_points")) or 0
    if chronic:
        b["chronic_points"] = chronic

    return sum(b.values()), b


def calculate_sofa(data: dict) -> tuple[int, dict]:
    """Calculate a SOFA score from a dict of inputs (aid, not authority)."""
    b: dict[str, int] = {}

    ratio = data.get("pao2_fio2")
    if ratio is not None:
        ratio = float(ratio)
        support = bool(data.get("resp_support"))
        if ratio < 100 and support:
            b["respiration"] = 4
        elif ratio < 200 and support:
            b["respiration"] = 3
        elif ratio < 300:
            b["respiration"] = 2
        elif ratio < 400:
            b["respiration"] = 1
        else:
            b["respiration"] = 0

    platelets = data.get("platelets")
    if platelets is not None:
        platelets = float(platelets)
        b["coagulation"] = (
            4
            if platelets < 20
            else (
                3
                if platelets < 50
                else 2 if platelets < 100 else 1 if platelets < 150 else 0
            )
        )

    bilirubin = data.get("bilirubin")
    if bilirubin is not None:
        bilirubin = float(bilirubin)
        b["liver"] = (
            4
            if bilirubin >= 12
            else (
                3
                if bilirubin >= 6
                else 2 if bilirubin >= 2 else 1 if bilirubin >= 1.2 else 0
            )
        )

    mapv = data.get("map")
    if mapv is not None:
        mapv = float(mapv)
        vaso = int(data.get("vasopressor_level") or 0)
        if vaso >= 4:
            b["cardiovascular"] = 4
        elif vaso == 3:
            b["cardiovascular"] = 3
        elif vaso == 2:
            b["cardiovascular"] = 2
        elif mapv < 70:
            b["cardiovascular"] = 1
        else:
            b["cardiovascular"] = 0

    gcs = data.get("gcs")
    if gcs is not None:
        gcs = float(gcs)
        b["cns"] = (
            4
            if gcs < 6
            else 3 if gcs <= 9 else 2 if gcs <= 12 else 1 if gcs <= 14 else 0
        )

    cr = data.get("creatinine")
    urine = data.get("urine_output")
    renal = None
    if cr is not None:
        cr = float(cr)
        renal = (
            4
            if cr >= 5
            else 3 if cr >= 3.5 else 2 if cr >= 2 else 1 if cr >= 1.2 else 0
        )
    if urine is not None:
        urine = float(urine)
        urine_pts = 4 if urine < 200 else 3 if urine < 500 else 0
        renal = max(renal or 0, urine_pts)
    if renal is not None:
        b["renal"] = renal

    return sum(b.values()), b


@transaction.atomic
def record_score(
    *, admission, score_type: str, data: dict, actor=None, request=None
) -> CriticalScore:
    """Calculate and persist an APACHE II or SOFA score."""
    if score_type == ScoreType.APACHE_II:
        value, breakdown = calculate_apache_ii(data)
    elif score_type == ScoreType.SOFA:
        value, breakdown = calculate_sofa(data)
    else:
        raise ValueError(_("Unknown score type: %s") % score_type)
    score = CriticalScore.objects.create(
        admission=admission,
        score_type=score_type,
        score_value=value,
        breakdown=breakdown,
        calculated_by=actor if getattr(actor, "pk", None) else None,
    )
    log_action(
        AuditAction.CREATE,
        instance=score,
        changes=model_to_dict_safe(score),
        user=actor,
        request=request,
    )
    return score


# ---------------------------------------------------------------------------
# Emergency department
# ---------------------------------------------------------------------------
_VITAL_FIELDS = (
    "temperature",
    "pulse",
    "respiratory_rate",
    "bp_systolic",
    "bp_diastolic",
    "spo2",
)


@transaction.atomic
def open_emergency_case(
    *,
    patient,
    complaint: str,
    triage_level: str = "yellow",
    attending_doctor=None,
    vitals: dict | None = None,
    actor=None,
    request=None,
) -> EmergencyCase:
    """Open an ER case for an already-registered patient."""
    data = dict(vitals or {})
    case = EmergencyCase(
        case_no=generate_er_number(),
        patient=patient,
        complaint=complaint,
        triage_level=triage_level or "yellow",
        attending_doctor=attending_doctor,
        notes=data.get("notes", ""),
        registered_by=actor if getattr(actor, "pk", None) else None,
    )
    for field in _VITAL_FIELDS:
        value = data.get(field)
        setattr(
            case,
            field,
            _to_decimal(value) if field == "temperature" else _to_int(value),
        )
    case.full_clean(exclude=["patient"])
    case.save()
    log_action(
        AuditAction.CREATE,
        instance=case,
        changes=model_to_dict_safe(case),
        user=actor,
        request=request,
    )
    return case


@transaction.atomic
def quick_register_and_open_case(
    *,
    patient_data: dict,
    complaint: str,
    triage_level: str = "yellow",
    attending_doctor=None,
    vitals: dict | None = None,
    actor=None,
    request=None,
) -> EmergencyCase:
    """Register a minimal patient record and immediately open an ER case."""
    from apps.patients import services as patient_services

    patient = patient_services.register_patient(
        data=patient_data, actor=actor, request=request
    )
    return open_emergency_case(
        patient=patient,
        complaint=complaint,
        triage_level=triage_level,
        attending_doctor=attending_doctor,
        vitals=vitals,
        actor=actor,
        request=request,
    )


@transaction.atomic
def set_triage(
    *, case: EmergencyCase, triage_level: str, actor=None, request=None
) -> EmergencyCase:
    before = case.triage_level
    case.triage_level = triage_level
    case.save(update_fields=["triage_level", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=case,
        changes={"triage_level": {"from": before, "to": triage_level}},
        user=actor,
        request=request,
    )
    return case


@transaction.atomic
def assign_doctor(
    *, case: EmergencyCase, doctor, actor=None, request=None
) -> EmergencyCase:
    case.attending_doctor = doctor
    case.save(update_fields=["attending_doctor", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=case,
        changes=model_to_dict_safe(case),
        user=actor,
        request=request,
    )
    return case


@transaction.atomic
def set_emergency_status(
    *, case: EmergencyCase, status: str, actor=None, request=None
) -> EmergencyCase:
    case.status = status
    if status in {
        EmergencyStatus.DISCHARGED,
        EmergencyStatus.LEFT,
        EmergencyStatus.DECEASED,
    }:
        case.discharged_at = timezone.now()
    case.save(update_fields=["status", "discharged_at", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=case,
        changes=model_to_dict_safe(case),
        user=actor,
        request=request,
    )
    return case


@transaction.atomic
def convert_to_admission(
    *,
    case: EmergencyCase,
    doctor,
    reason: str = "",
    admission_type=None,
    actor=None,
    request=None,
) -> EmergencyCase:
    """Raise an IPD admission advice from an ER case and mark it admitted."""
    from apps.ipd import services as ipd_services

    admission = ipd_services.request_admission(
        patient=case.patient,
        doctor=doctor,
        admission_type=admission_type,
        reason=reason or case.complaint,
        encounter=None,
        actor=actor,
        request=request,
    )
    case.converted_admission = admission
    case.attending_doctor = case.attending_doctor or doctor
    case.status = EmergencyStatus.ADMITTED
    case.save(
        update_fields=[
            "converted_admission",
            "attending_doctor",
            "status",
            "updated_at",
        ]
    )
    log_action(
        AuditAction.UPDATE,
        instance=case,
        changes=model_to_dict_safe(case),
        user=actor,
        request=request,
    )
    return case


@transaction.atomic
def quick_discharge(*, case: EmergencyCase, actor=None, request=None) -> EmergencyCase:
    """Emergency quick discharge (billing is completed in Phase 12)."""
    return set_emergency_status(
        case=case, status=EmergencyStatus.DISCHARGED, actor=actor, request=request
    )


# ---------------------------------------------------------------------------
# Code Blue
# ---------------------------------------------------------------------------
@transaction.atomic
def raise_code_blue(
    *,
    location: str,
    admission=None,
    emergency_case=None,
    notes: str = "",
    actor=None,
    request=None,
) -> CodeBlueAlert:
    """Raise a Code Blue and broadcast it to on-duty staff."""
    alert = CodeBlueAlert.objects.create(
        location=location,
        admission=admission,
        emergency_case=emergency_case,
        notes=notes,
        called_by=actor if getattr(actor, "pk", None) else None,
    )
    alert.notified_count = notifications.broadcast_code_blue(alert)
    alert.save(update_fields=["notified_count", "updated_at"])
    log_action(
        AuditAction.CREATE,
        instance=alert,
        changes=model_to_dict_safe(alert),
        user=actor,
        request=request,
    )
    return alert


@transaction.atomic
def resolve_code_blue(
    *, alert: CodeBlueAlert, notes: str = "", actor=None, request=None
) -> CodeBlueAlert:
    alert.status = CodeBlueStatus.RESOLVED
    alert.resolved_at = timezone.now()
    alert.resolved_by = actor if getattr(actor, "pk", None) else None
    if notes:
        alert.notes = f"{alert.notes}\n{notes}".strip()
    alert.save(
        update_fields=["status", "resolved_at", "resolved_by", "notes", "updated_at"]
    )
    log_action(
        AuditAction.UPDATE,
        instance=alert,
        changes=model_to_dict_safe(alert),
        user=actor,
        request=request,
    )
    return alert


# ---------------------------------------------------------------------------
# Shift handover
# ---------------------------------------------------------------------------
@transaction.atomic
def record_handover(
    *,
    unit: str,
    shift: str,
    summary: str,
    admission=None,
    emergency_case=None,
    pending_tasks: str = "",
    handover_to=None,
    actor=None,
    request=None,
) -> HandoverNote:
    note = HandoverNote.objects.create(
        unit=unit,
        shift=shift,
        admission=admission,
        emergency_case=emergency_case,
        summary=summary,
        pending_tasks=pending_tasks,
        handover_to=handover_to,
        handed_over_by=actor if getattr(actor, "pk", None) else None,
    )
    log_action(
        AuditAction.CREATE,
        instance=note,
        changes=model_to_dict_safe(note),
        user=actor,
        request=request,
    )
    return note


@transaction.atomic
def acknowledge_handover(
    *, note: HandoverNote, actor=None, request=None
) -> HandoverNote:
    note.acknowledged = True
    note.save(update_fields=["acknowledged", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=note,
        changes=model_to_dict_safe(note),
        user=actor,
        request=request,
    )
    return note
