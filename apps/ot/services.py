"""Write operations for the Operation Theatre module (atomic + audit).

Surgery scheduling runs under a row lock on the target :class:`OTRoom` and
rejects overlapping time slots, so no two active surgeries can occupy the same
theatre at once (RULES Phase 9 exit criteria). Surgery numbers follow
``OT-YYYY-NNNNN`` via the row-locked :class:`SurgerySequence` counter.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.audit import AuditAction, log_action, model_to_dict_safe

from .models import (ACTIVE_SURGERY_STATUSES, AnesthesiaRecord, Implant,
                     IntraOpNote, OTRoom, PatientCondition, PostOpNote,
                     PreOpChecklist, Surgery, SurgeryConsumable,
                     SurgerySequence, SurgeryStatus)


def _dec(value):
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


@transaction.atomic
def generate_ot_number(now=None) -> str:
    """Mint an ``OT-YYYY-NNNNN`` surgery number atomically."""
    now = now or timezone.localtime()
    year = now.year
    seq, _created = SurgerySequence.objects.select_for_update().get_or_create(year=year)
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    width = int(settings.IHMS.get("OT_NUMBER_WIDTH", 5))
    prefix = settings.IHMS.get("OT_PREFIX", "OT")
    return f"{prefix}-{year}-{seq.last_number:0{width}d}"


def check_conflict(
    *, room: OTRoom, date, start, end, exclude_pk=None
) -> Surgery | None:
    """Return a conflicting active surgery, or ``None`` when the slot is free."""
    qs = Surgery.objects.filter(
        ot_room=room,
        scheduled_date=date,
        status__in=ACTIVE_SURGERY_STATUSES,
        start_time__lt=end,
        end_time__gt=start,
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.first()


@transaction.atomic
def schedule_surgery(
    *,
    patient,
    surgeon,
    ot_room: OTRoom,
    scheduled_date,
    start_time,
    end_time,
    procedure_name: str,
    priority: str = "elective",
    admission=None,
    diagnosis: str = "",
    notes: str = "",
    actor=None,
    request=None,
) -> Surgery:
    """Schedule a surgery, rejecting OT room double-booking."""
    if end_time <= start_time:
        raise ValueError(_("End time must be after start time."))
    locked_room = OTRoom.objects.select_for_update().get(pk=ot_room.pk)
    clash = check_conflict(
        room=locked_room, date=scheduled_date, start=start_time, end=end_time
    )
    if clash is not None:
        raise ValueError(
            _("OT room %(room)s is already booked %(start)s–%(end)s (%(proc)s).")
            % {
                "room": locked_room,
                "start": clash.start_time.strftime("%H:%M"),
                "end": clash.end_time.strftime("%H:%M"),
                "proc": clash.procedure_name,
            }
        )
    surgery = Surgery.objects.create(
        surgery_no=generate_ot_number(),
        patient=patient,
        surgeon=surgeon,
        ot_room=locked_room,
        admission=admission,
        scheduled_date=scheduled_date,
        start_time=start_time,
        end_time=end_time,
        procedure_name=procedure_name,
        priority=priority or "elective",
        diagnosis=diagnosis,
        notes=notes,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    log_action(
        AuditAction.CREATE,
        instance=surgery,
        changes=model_to_dict_safe(surgery),
        user=actor,
        request=request,
    )
    return surgery


@transaction.atomic
def reschedule_surgery(
    *,
    surgery: Surgery,
    scheduled_date,
    start_time,
    end_time,
    ot_room=None,
    actor=None,
    request=None,
) -> Surgery:
    """Move a surgery to a new slot/room with conflict detection."""
    if end_time <= start_time:
        raise ValueError(_("End time must be after start time."))
    room = ot_room or surgery.ot_room
    OTRoom.objects.select_for_update().get(pk=room.pk)
    clash = check_conflict(
        room=room,
        date=scheduled_date,
        start=start_time,
        end=end_time,
        exclude_pk=surgery.pk,
    )
    if clash is not None:
        raise ValueError(
            _("OT room %(room)s is already booked %(start)s–%(end)s.")
            % {
                "room": room,
                "start": clash.start_time.strftime("%H:%M"),
                "end": clash.end_time.strftime("%H:%M"),
            }
        )
    surgery.scheduled_date = scheduled_date
    surgery.start_time = start_time
    surgery.end_time = end_time
    surgery.ot_room = room
    surgery.status = SurgeryStatus.SCHEDULED
    surgery.save()
    log_action(
        AuditAction.UPDATE,
        instance=surgery,
        changes=model_to_dict_safe(surgery),
        user=actor,
        request=request,
    )
    return surgery


@transaction.atomic
def set_surgery_status(
    *, surgery: Surgery, status: str, actor=None, request=None
) -> Surgery:
    surgery.status = status
    if status == SurgeryStatus.CANCELLED and not surgery.cancellation_reason:
        surgery.cancellation_reason = _("Cancelled")
    surgery.save(update_fields=["status", "cancellation_reason", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=surgery,
        changes=model_to_dict_safe(surgery),
        user=actor,
        request=request,
    )
    return surgery


@transaction.atomic
def cancel_surgery(
    *, surgery: Surgery, reason: str = "", actor=None, request=None
) -> Surgery:
    surgery.status = SurgeryStatus.CANCELLED
    surgery.cancellation_reason = reason
    surgery.save(update_fields=["status", "cancellation_reason", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=surgery,
        changes=model_to_dict_safe(surgery),
        user=actor,
        request=request,
    )
    return surgery


@transaction.atomic
def start_surgery(*, surgery: Surgery, actor=None, request=None) -> Surgery:
    """Start a surgery — the pre-op checklist **must** be complete first."""
    checklist = getattr(surgery, "preop_checklist", None)
    if checklist is None or not checklist.is_complete:
        missing = checklist.missing_items if checklist else list(PreOpChecklist.ITEMS)
        raise ValueError(
            _("Pre-op checklist incomplete: %(items)s.") % {"items": ", ".join(missing)}
        )
    surgery.status = SurgeryStatus.IN_PROGRESS
    surgery.started_at = timezone.now()
    surgery.save(update_fields=["status", "started_at", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=surgery,
        changes=model_to_dict_safe(surgery),
        user=actor,
        request=request,
    )
    return surgery


@transaction.atomic
def complete_surgery(*, surgery: Surgery, actor=None, request=None) -> Surgery:
    surgery.status = SurgeryStatus.COMPLETED
    surgery.completed_at = timezone.now()
    surgery.save(update_fields=["status", "completed_at", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=surgery,
        changes=model_to_dict_safe(surgery),
        user=actor,
        request=request,
    )
    return surgery


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
@transaction.atomic
def add_team_member(
    *,
    surgery: Surgery,
    role: str,
    doctor=None,
    staff=None,
    name: str = "",
    actor=None,
    request=None,
):
    from .models import SurgicalTeamMember

    member = SurgicalTeamMember.objects.create(
        surgery=surgery, role=role, doctor=doctor, staff=staff, name=name
    )
    log_action(
        AuditAction.CREATE,
        instance=member,
        changes=model_to_dict_safe(member),
        user=actor,
        request=request,
    )
    return member


# ---------------------------------------------------------------------------
# Checklists / notes (upsert OneToOne)
# ---------------------------------------------------------------------------
_PREOP_ITEMS = PreOpChecklist.ITEMS


@transaction.atomic
def save_preop_checklist(
    *, surgery: Surgery, data: dict, actor=None, request=None
) -> PreOpChecklist:
    checklist, _created = PreOpChecklist.objects.get_or_create(surgery=surgery)
    for item in _PREOP_ITEMS:
        setattr(checklist, item, bool(data.get(item)))
    checklist.notes = data.get("notes", checklist.notes)
    checklist.verified_by = (
        actor if getattr(actor, "pk", None) else checklist.verified_by
    )
    if checklist.is_complete:
        checklist.verified_at = timezone.now()
    checklist.save()
    log_action(
        AuditAction.UPDATE,
        instance=checklist,
        changes=model_to_dict_safe(checklist),
        user=actor,
        request=request,
    )
    return checklist


@transaction.atomic
def record_anesthesia(
    *, surgery: Surgery, data: dict, actor=None, request=None
) -> AnesthesiaRecord:
    record, _created = AnesthesiaRecord.objects.get_or_create(surgery=surgery)
    for field in (
        "anesthesia_type",
        "anesthetist",
        "asa_grade",
        "airway",
        "agents",
        "intubation_time",
        "extubation_time",
        "complications",
        "notes",
    ):
        if field in data:
            setattr(record, field, data[field])
    record.recorded_by = actor if getattr(actor, "pk", None) else record.recorded_by
    record.save()
    log_action(
        AuditAction.UPDATE,
        instance=record,
        changes=model_to_dict_safe(record),
        user=actor,
        request=request,
    )
    return record


@transaction.atomic
def record_intraop_note(
    *, surgery: Surgery, data: dict, actor=None, request=None
) -> IntraOpNote:
    note, _created = IntraOpNote.objects.get_or_create(surgery=surgery)
    for field in (
        "findings",
        "procedure_performed",
        "blood_loss_ml",
        "specimens",
        "drains",
        "closure",
        "notes",
    ):
        if field in data:
            setattr(note, field, data[field])
    note.recorded_by = actor if getattr(actor, "pk", None) else note.recorded_by
    note.save()
    log_action(
        AuditAction.UPDATE,
        instance=note,
        changes=model_to_dict_safe(note),
        user=actor,
        request=request,
    )
    return note


@transaction.atomic
def record_postop_note(
    *, surgery: Surgery, data: dict, actor=None, request=None
) -> PostOpNote:
    note, _created = PostOpNote.objects.get_or_create(surgery=surgery)
    for field in (
        "condition",
        "pain_score",
        "recovery_notes",
        "follow_up_plan",
        "notes",
    ):
        if field in data:
            setattr(note, field, data[field])
    note.recorded_by = actor if getattr(actor, "pk", None) else note.recorded_by
    note.save()
    log_action(
        AuditAction.UPDATE,
        instance=note,
        changes=model_to_dict_safe(note),
        user=actor,
        request=request,
    )
    return note


# ---------------------------------------------------------------------------
# Implants / consumables
# ---------------------------------------------------------------------------
@transaction.atomic
def record_implant(
    *, surgery: Surgery, data: dict, actor=None, request=None
) -> Implant:
    implant = Implant.objects.create(
        patient=surgery.patient,
        surgery=surgery,
        name=data["name"],
        manufacturer=data.get("manufacturer", ""),
        serial_no=data.get("serial_no", ""),
        lot_no=data.get("lot_no", ""),
        quantity=int(data.get("quantity") or 1),
        unit_price=_dec(data.get("unit_price")),
        notes=data.get("notes", ""),
    )
    log_action(
        AuditAction.CREATE,
        instance=implant,
        changes=model_to_dict_safe(implant),
        user=actor,
        request=request,
    )
    return implant


@transaction.atomic
def record_consumable(
    *, surgery: Surgery, data: dict, actor=None, request=None
) -> SurgeryConsumable:
    consumable = SurgeryConsumable.objects.create(
        surgery=surgery,
        item=data["item"],
        quantity=int(data.get("quantity") or 1),
        unit_price=_dec(data.get("unit_price")),
        notes=data.get("notes", ""),
    )
    log_action(
        AuditAction.CREATE,
        instance=consumable,
        changes=model_to_dict_safe(consumable),
        user=actor,
        request=request,
    )
    return consumable


# Re-export for convenience/tests.
__all__ = [
    "generate_ot_number",
    "check_conflict",
    "schedule_surgery",
    "reschedule_surgery",
    "set_surgery_status",
    "cancel_surgery",
    "start_surgery",
    "complete_surgery",
    "add_team_member",
    "save_preop_checklist",
    "record_anesthesia",
    "record_intraop_note",
    "record_postop_note",
    "record_implant",
    "record_consumable",
    "PatientCondition",
]
