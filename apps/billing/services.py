"""Write operations for the Billing & Payments module (atomic + audit).

Everything that changes money lives here: charge posting from the clinical
modules, invoice computation (subtotal / VAT / approval-tiered discount),
payment collection with money-receipt issuance, advance deposits, refunds and
the bill-settlement step that clears an IPD billing clearance.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting import integration as accounting_hooks
from core.audit import AuditAction, log_action, model_to_dict_safe

from .models import (
    Advance,
    Bill,
    BillingSequence,
    BillItem,
    BillItemType,
    BillStatus,
    BillType,
    CreditNote,
    CreditNoteStatus,
    DiscountStatus,
    MoneyReceipt,
    Payment,
    PaymentMode,
    Refund,
    RefundStatus,
    SequenceKind,
    ServicePackage,
    _dec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _money(value) -> Decimal:
    return _dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _actor_id(actor):
    return actor if getattr(actor, "pk", None) else None


def _next_number(kind: SequenceKind) -> str:
    now = timezone.localtime()
    seq, _ = BillingSequence.objects.select_for_update().get_or_create(
        year=now.year, kind=kind
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    prefix, width = {
        SequenceKind.BILL: (
            settings.IHMS.get("BILL_PREFIX", "BILL"),
            int(settings.IHMS.get("BILL_NUMBER_WIDTH", 5)),
        ),
        SequenceKind.RECEIPT: (
            settings.IHMS.get("MONEY_RECEIPT_PREFIX", "MR"),
            int(settings.IHMS.get("MONEY_RECEIPT_NUMBER_WIDTH", 5)),
        ),
        SequenceKind.ADVANCE: (
            settings.IHMS.get("ADVANCE_PREFIX", "ADV"),
            int(settings.IHMS.get("BILL_NUMBER_WIDTH", 5)),
        ),
        SequenceKind.REFUND: (
            settings.IHMS.get("REFUND_PREFIX", "REF"),
            int(settings.IHMS.get("BILL_NUMBER_WIDTH", 5)),
        ),
        SequenceKind.CREDIT: (
            settings.IHMS.get("CREDIT_NOTE_PREFIX", "CN"),
            int(settings.IHMS.get("CREDIT_NOTE_NUMBER_WIDTH", 5)),
        ),
        SequenceKind.PACKAGE: (
            settings.IHMS.get("PACKAGE_PREFIX", "PKG"),
            int(settings.IHMS.get("PACKAGE_NUMBER_WIDTH", 5)),
        ),
    }[kind]
    return f"{prefix}-{now.year}-{seq.last_number:0{width}d}"


def resolve_vat_rate() -> Decimal:
    """NBR-compliant default VAT rate from the ``TaxConfig`` master.

    Falls back to ``IHMS["BILL_DEFAULT_VAT_RATE"]`` when no active VAT row is
    configured (RULES Phase 12: *"VAT calculation — per line, NBR rules"*).
    """
    from apps.masters.models import TaxCategory, TaxConfig

    cfg = (
        TaxConfig.objects.filter(category=TaxCategory.VAT, is_active=True)
        .order_by("pk")
        .first()
    )
    if cfg is not None:
        return _dec(cfg.rate)
    return _dec(settings.IHMS.get("BILL_DEFAULT_VAT_RATE", "0"))


def _vat_rate(bill: Bill) -> Decimal:
    """The VAT rate carried by the bill (set at creation from the NBR config)."""
    return _dec(bill.vat_rate)


# ---------------------------------------------------------------------------
# Invoice construction
# ---------------------------------------------------------------------------
@transaction.atomic
def create_bill(
    patient,
    *,
    bill_type: str = BillType.OPD,
    admission=None,
    vat_rate=0,
    notes: str = "",
    actor=None,
    request=None,
) -> Bill:
    """Create a brand-new bill with a generated number."""
    rate = _dec(vat_rate) if _dec(vat_rate) > 0 else resolve_vat_rate()
    bill = Bill.objects.create(
        patient=patient,
        admission=admission,
        bill_no=_next_number(SequenceKind.BILL),
        bill_type=bill_type,
        vat_rate=rate,
        notes=notes,
        created_by=_actor_id(actor),
    )
    log_action(
        AuditAction.CREATE,
        instance=bill,
        changes=model_to_dict_safe(bill),
        user=actor,
        request=request,
    )
    return bill


@transaction.atomic
def get_or_create_open_bill(
    patient, *, bill_type: str = BillType.OPD, admission=None, actor=None
) -> Bill:
    """Return the patient's open bill (draft/issued/unpaid) or create one.

    Locked bills (any payment received) are skipped so that post-payment
    corrections always go through a credit note rather than mutating a settled
    invoice.
    """
    qs = Bill.objects.filter(
        patient=patient,
        bill_type=bill_type,
        paid_amount=0,
        status__in=[BillStatus.DRAFT, BillStatus.ISSUED, BillStatus.PARTIALLY_PAID],
    )
    if admission is not None:
        qs = qs.filter(admission=admission)
    bill = qs.order_by("-created_at").first()
    if bill is not None:
        return bill
    bill = Bill.objects.create(
        patient=patient,
        admission=admission,
        bill_no=_next_number(SequenceKind.BILL),
        bill_type=bill_type,
        vat_rate=resolve_vat_rate(),
        created_by=_actor_id(actor),
    )
    log_action(
        AuditAction.CREATE,
        instance=bill,
        changes=model_to_dict_safe(bill),
        user=actor,
    )
    return bill


@transaction.atomic
def post_charge(
    bill: Bill,
    *,
    item_type: str,
    description: str,
    quantity=1,
    unit_price=0,
    tax_rate=None,
    service_date=None,
    source_type: str = "",
    source_id: str = "",
    allow_locked: bool = False,
    actor=None,
    request=None,
) -> BillItem:
    """Append a charge line to ``bill`` and recompute the totals."""
    if bill.is_locked and not allow_locked:
        raise ValueError(
            _("This bill has been paid and is locked; issue a credit note instead.")
        )
    qty = _dec(quantity) if _dec(quantity) != 0 else Decimal("1")
    price = _dec(unit_price)
    amount = _money(qty * price)
    rate = _dec(tax_rate) if tax_rate is not None else _vat_rate(bill)
    vat_amount = _money(amount * rate / Decimal("100"))
    item = BillItem.objects.create(
        bill=bill,
        item_type=item_type,
        description=description,
        quantity=qty,
        unit_price=price,
        amount=amount,
        tax_rate=rate,
        vat_amount=vat_amount,
        service_date=service_date,
        source_type=source_type,
        source_id=str(source_id or ""),
    )
    recompute_bill(bill)
    if source_type != "billing.creditnote":
        accounting_hooks.on_bill_updated(bill, actor=actor, request=request)
    log_action(
        AuditAction.CREATE,
        instance=item,
        changes=model_to_dict_safe(item),
        user=actor,
        request=request,
    )
    return item


@transaction.atomic
def recompute_bill(bill: Bill, *, actor=None, request=None) -> Bill:
    bill.recompute(save=False)
    bill.save(update_fields=["subtotal", "vat", "total", "paid_amount", "updated_at"])
    return bill


@transaction.atomic
def calculate_vat(bill: Bill, *, rate=None, actor=None, request=None) -> Bill:
    """Apply a VAT rate to every line and recompute the invoice."""
    apply_rate = _dec(rate) if rate is not None else _vat_rate(bill)
    bill.vat_rate = apply_rate
    for item in bill.items.all():
        item.tax_rate = apply_rate
        item.vat_amount = _money(_dec(item.amount) * apply_rate / Decimal("100"))
        item.save(update_fields=["tax_rate", "vat_amount", "updated_at"])
    bill.save(update_fields=["vat_rate", "updated_at"])
    recompute_bill(bill)
    log_action(
        AuditAction.UPDATE,
        instance=bill,
        changes={"vat_rate": str(apply_rate)},
        user=actor,
        request=request,
    )
    return bill


@transaction.atomic
def issue_bill(bill: Bill, *, actor=None, request=None) -> Bill:
    if bill.status == BillStatus.DRAFT:
        bill.status = BillStatus.ISSUED
        bill.issued_at = timezone.now()
        bill.save(update_fields=["status", "issued_at", "updated_at"])
        log_action(
            AuditAction.UPDATE,
            instance=bill,
            changes={"status": BillStatus.ISSUED},
            user=actor,
            request=request,
        )
    accounting_hooks.on_bill_issued(bill, actor=actor, request=request)
    return bill


# ---------------------------------------------------------------------------
# Discount workflow
# ---------------------------------------------------------------------------
@transaction.atomic
def apply_discount(
    bill: Bill, *, amount, reason: str = "", actor=None, request=None
) -> Bill:
    """Set the bill discount, routing large discounts to an approval tier."""
    if bill.is_locked:
        raise ValueError(
            _("This bill has been paid and is locked; issue a credit note instead.")
        )
    value = _money(amount)
    if value < 0:
        raise ValueError(_("Discount cannot be negative."))
    bill.recompute(save=False)
    if value > _dec(bill.subtotal):
        raise ValueError(_("Discount cannot exceed the subtotal."))
    bill.discount = value
    bill.discount_reason = reason
    if value == 0:
        bill.discount_status = DiscountStatus.NONE
        bill.discount_approved_by = None
        bill.discount_approved_at = None
    else:
        threshold = _dec(settings.IHMS.get("BILL_DISCOUNT_APPROVAL_THRESHOLD", "1000"))
        pct = _dec(settings.IHMS.get("BILL_DISCOUNT_APPROVAL_PCT", "10"))
        subtotal = _dec(bill.subtotal)
        pct_used = (value * Decimal("100") / subtotal) if subtotal > 0 else Decimal("0")
        if value >= threshold or (pct > 0 and pct_used >= pct):
            bill.discount_status = DiscountStatus.PENDING
            bill.discount_approved_by = None
            bill.discount_approved_at = None
        else:
            bill.discount_status = DiscountStatus.APPROVED
            bill.discount_approved_by = _actor_id(actor)
            bill.discount_approved_at = timezone.now()
    bill.save(
        update_fields=[
            "discount",
            "discount_reason",
            "discount_status",
            "discount_approved_by",
            "discount_approved_at",
            "updated_at",
        ]
    )
    recompute_bill(bill)
    log_action(
        AuditAction.UPDATE,
        instance=bill,
        changes={"discount": str(value), "status": bill.discount_status},
        user=actor,
        request=request,
    )
    return bill


@transaction.atomic
def decide_discount(bill: Bill, *, approved: bool, actor=None, request=None) -> Bill:
    if bill.discount_status != DiscountStatus.PENDING:
        raise ValueError(_("This bill has no discount pending approval."))
    bill.discount_status = (
        DiscountStatus.APPROVED if approved else DiscountStatus.REJECTED
    )
    if approved:
        bill.discount_approved_by = _actor_id(actor)
        bill.discount_approved_at = timezone.now()
    else:
        bill.discount = Decimal("0")
        bill.discount_approved_by = None
        bill.discount_approved_at = None
    bill.save(
        update_fields=[
            "discount",
            "discount_status",
            "discount_approved_by",
            "discount_approved_at",
            "updated_at",
        ]
    )
    recompute_bill(bill)
    log_action(
        AuditAction.APPROVE,
        instance=bill,
        changes={"discount_status": bill.discount_status},
        user=actor,
        request=request,
    )
    return bill


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
def _refresh_status(bill: Bill) -> Bill:
    if bill.status == BillStatus.CANCELLED:
        return bill
    paid = _dec(bill.paid_amount)
    total = _dec(bill.total)
    if paid <= 0:
        status = BillStatus.ISSUED if bill.issued_at else BillStatus.DRAFT
    elif paid < total:
        status = BillStatus.PARTIALLY_PAID
    else:
        status = BillStatus.PAID
    if bill.status != status:
        bill.status = status
        bill.save(update_fields=["status", "updated_at"])
    return bill


@transaction.atomic
def collect_payment(
    bill: Bill,
    *,
    method: str,
    amount,
    txn_ref: str = "",
    gateway_ref: str = "",
    actor=None,
    request=None,
) -> Payment:
    """Record a payment, issue a money receipt and refresh the bill status."""
    value = _money(amount)
    if value <= 0:
        raise ValueError(_("Payment amount must be greater than zero."))
    due = bill.due_amount
    if value > due:
        raise ValueError(
            _("Payment exceeds the outstanding balance of %(d)s.") % {"d": f"{due:.2f}"}
        )
    if bill.status == BillStatus.DRAFT:
        issue_bill(bill, actor=actor, request=request)
    payment = Payment.objects.create(
        bill=bill,
        method=method,
        amount=value,
        txn_ref=txn_ref,
        gateway_ref=gateway_ref,
        received_by=_actor_id(actor),
    )
    MoneyReceipt.objects.create(
        payment=payment,
        receipt_no=_next_number(SequenceKind.RECEIPT),
        amount=value,
        issued_by=_actor_id(actor),
    )
    bill.paid_amount = _dec(bill.paid_amount) + value
    bill.save(update_fields=["paid_amount", "updated_at"])
    _refresh_status(bill)
    log_action(
        AuditAction.PAYMENT,
        instance=payment,
        changes=model_to_dict_safe(payment),
        user=actor,
        request=request,
    )
    accounting_hooks.on_payment_recorded(payment, actor=actor, request=request)
    if bill.admission_id:
        settle_admission(bill.admission, actor=actor, request=request)
    return payment


# ---------------------------------------------------------------------------
# Advances / deposits
# ---------------------------------------------------------------------------
@transaction.atomic
def add_advance(
    patient,
    *,
    amount,
    method: str = PaymentMode.CASH,
    admission=None,
    txn_ref: str = "",
    notes: str = "",
    actor=None,
    request=None,
) -> Advance:
    value = _money(amount)
    if value <= 0:
        raise ValueError(_("Advance amount must be greater than zero."))
    advance = Advance.objects.create(
        patient=patient,
        admission=admission,
        advance_no=_next_number(SequenceKind.ADVANCE),
        amount=value,
        method=method,
        txn_ref=txn_ref,
        notes=notes,
        received_by=_actor_id(actor),
    )
    log_action(
        AuditAction.PAYMENT,
        instance=advance,
        changes=model_to_dict_safe(advance),
        user=actor,
        request=request,
    )
    accounting_hooks.on_advance_created(advance, actor=actor, request=request)
    return advance


@transaction.atomic
def apply_advance(
    advance: Advance, bill: Bill, *, amount=None, actor=None, request=None
) -> Payment:
    """Adjust an advance deposit against a bill."""
    value = _money(amount) if amount is not None else advance.balance
    if value <= 0:
        raise ValueError(_("Amount must be greater than zero."))
    if value > advance.balance:
        raise ValueError(_("Amount exceeds the advance balance."))
    payment = collect_payment(
        bill,
        method=PaymentMode.CASH,
        amount=value,
        txn_ref=advance.advance_no,
        actor=actor,
        request=request,
    )
    payment.notes = _("Advance adjustment %(no)s") % {"no": advance.advance_no}
    payment.save(update_fields=["notes", "updated_at"])
    advance.adjusted_amount = _dec(advance.adjusted_amount) + value
    advance.save(update_fields=["adjusted_amount", "updated_at"])
    return payment


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
@transaction.atomic
def create_refund(
    *,
    amount,
    reason: str,
    method: str = PaymentMode.CASH,
    bill: Bill | None = None,
    payment: Payment | None = None,
    actor=None,
    request=None,
) -> Refund:
    value = _money(amount)
    if value <= 0:
        raise ValueError(_("Refund amount must be greater than zero."))
    refund = Refund.objects.create(
        bill=bill,
        payment=payment,
        refund_no=_next_number(SequenceKind.REFUND),
        amount=value,
        method=method,
        reason=reason,
        requested_by=_actor_id(actor),
    )
    log_action(
        AuditAction.CREATE,
        instance=refund,
        changes=model_to_dict_safe(refund),
        user=actor,
        request=request,
    )
    return refund


@transaction.atomic
def decide_refund(
    refund: Refund, *, approved: bool, actor=None, request=None
) -> Refund:
    if refund.status != RefundStatus.REQUESTED:
        raise ValueError(_("This refund has already been decided."))
    if approved:
        refund.status = RefundStatus.APPROVED
        refund.approved_by = _actor_id(actor)
        refund.approved_at = timezone.now()
    else:
        refund.status = RefundStatus.REJECTED
    refund.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    log_action(
        AuditAction.APPROVE,
        instance=refund,
        changes={"status": refund.status},
        user=actor,
        request=request,
    )
    return refund


@transaction.atomic
def process_refund(
    refund: Refund, *, txn_ref: str = "", actor=None, request=None
) -> Refund:
    if refund.status != RefundStatus.APPROVED:
        raise ValueError(_("Only approved refunds can be processed."))
    if refund.amount > _dec(refund.bill.paid_amount):
        raise ValueError(_("Refund exceeds the amount paid on this bill."))
    refund.status = RefundStatus.PROCESSED
    refund.refunded_at = timezone.now()
    if txn_ref:
        refund.txn_ref = txn_ref
    refund.save(update_fields=["status", "refunded_at", "txn_ref", "updated_at"])
    bill = refund.bill
    bill.paid_amount = _dec(bill.paid_amount) - _dec(refund.amount)
    bill.save(update_fields=["paid_amount", "updated_at"])
    _refresh_status(bill)
    log_action(
        AuditAction.PAYMENT,
        instance=refund,
        changes=model_to_dict_safe(refund),
        user=actor,
        request=request,
    )
    accounting_hooks.on_refund_processed(refund, actor=actor, request=request)
    return refund


# ---------------------------------------------------------------------------
# Discharge settlement
# ---------------------------------------------------------------------------
@transaction.atomic
def settle_admission(admission, *, actor=None, request=None) -> bool:
    """Clear the *Billing* discharge clearance once every bill is settled."""
    from apps.ipd.models import ClearanceDepartment, DischargeClearance

    bills = Bill.objects.filter(admission=admission).exclude(
        status=BillStatus.CANCELLED
    )
    outstanding = any(_dec(b.total) > _dec(b.paid_amount) for b in bills)
    clearance = DischargeClearance.objects.filter(
        admission=admission, department=ClearanceDepartment.BILLING
    ).first()
    if not outstanding and bills.exists():
        if clearance is None:
            clearance = DischargeClearance.objects.create(
                admission=admission, department=ClearanceDepartment.BILLING
            )
        clearance.is_cleared = True
        clearance.cleared_by = _actor_id(actor)
        clearance.cleared_at = timezone.now()
        clearance.save(
            update_fields=["is_cleared", "cleared_by", "cleared_at", "updated_at"]
        )
        log_action(
            AuditAction.UPDATE,
            instance=clearance,
            changes={"is_cleared": True},
            user=actor,
            request=request,
        )
        return True
    return False


# ---------------------------------------------------------------------------
# Charge posting from the clinical modules
# ---------------------------------------------------------------------------
@transaction.atomic
def post_ipd_charges(admission, *, actor=None, request=None) -> Bill:
    """Post accrued :class:`~apps.ipd.models.DailyCharge` rows to an IPD bill."""
    from apps.ipd.models import ChargeStatus

    bill = get_or_create_open_bill(
        admission.patient,
        bill_type=BillType.IPD,
        admission=admission,
        actor=actor,
    )
    pending = admission.daily_charges.filter(status=ChargeStatus.ACCRUED)
    for charge in pending:
        if _dec(charge.bed_charge) > 0:
            post_charge(
                bill,
                item_type=BillItemType.BED,
                description=_("Bed charge · %(d)s") % {"d": charge.charge_date},
                quantity=1,
                unit_price=charge.bed_charge,
                service_date=charge.charge_date,
                source_type="ipd.dailycharge",
                source_id=charge.pk,
                actor=actor,
                request=request,
            )
        if _dec(charge.nursing_charge) > 0:
            post_charge(
                bill,
                item_type=BillItemType.NURSING,
                description=_("Nursing charge · %(d)s") % {"d": charge.charge_date},
                quantity=1,
                unit_price=charge.nursing_charge,
                service_date=charge.charge_date,
                source_type="ipd.dailycharge",
                source_id=charge.pk,
                actor=actor,
                request=request,
            )
        if _dec(charge.doctor_visit_charge) > 0:
            post_charge(
                bill,
                item_type=BillItemType.DOCTOR_VISIT,
                description=_("Doctor visit · %(d)s") % {"d": charge.charge_date},
                quantity=1,
                unit_price=charge.doctor_visit_charge,
                service_date=charge.charge_date,
                source_type="ipd.dailycharge",
                source_id=charge.pk,
                actor=actor,
                request=request,
            )
        charge.status = ChargeStatus.POSTED
        charge.save(update_fields=["status", "updated_at"])
    return bill


@transaction.atomic
def post_lab_charges(patient, *, actor=None, request=None) -> Bill:
    """Post unbilled :class:`~apps.lab.models.LabCharge` rows for a patient."""
    from apps.lab.models import LabCharge

    bill = get_or_create_open_bill(patient, bill_type=BillType.OPD, actor=actor)
    charges = LabCharge.objects.filter(
        order__patient=patient, is_billed=False
    ).select_related("test", "order")
    for charge in charges:
        post_charge(
            bill,
            item_type=BillItemType.LAB,
            description=str(charge.test),
            quantity=1,
            unit_price=charge.amount,
            source_type="lab.labcharge",
            source_id=charge.pk,
            actor=actor,
            request=request,
        )
        charge.is_billed = True
        charge.save(update_fields=["is_billed", "updated_at"])
    return bill


@transaction.atomic
def post_pharmacy_charges(patient, *, actor=None, request=None) -> Bill:
    """Post unbilled pharmacy dispense records for a patient."""
    from apps.pharmacy.models import DispenseRecord

    bill = get_or_create_open_bill(patient, bill_type=BillType.OPD, actor=actor)
    dispenses = DispenseRecord.objects.filter(
        patient=patient, is_billed=False
    ).prefetch_related("items__drug")
    for dispense in dispenses:
        for line in dispense.items.all():
            post_charge(
                bill,
                item_type=BillItemType.PHARMACY,
                description=str(line.drug),
                quantity=line.quantity,
                unit_price=line.unit_price,
                source_type="pharmacy.dispenseitem",
                source_id=line.pk,
                actor=actor,
                request=request,
            )
        dispense.is_billed = True
        dispense.save(update_fields=["is_billed", "updated_at"])
    return bill


@transaction.atomic
def post_ot_charges(patient, *, actor=None, request=None) -> Bill:
    """Post unbilled OT implants and consumables for a patient."""
    from apps.ot.models import Implant, SurgeryConsumable

    bill = get_or_create_open_bill(patient, bill_type=BillType.OPD, actor=actor)
    for implant in Implant.objects.filter(patient=patient, is_billed=False):
        post_charge(
            bill,
            item_type=BillItemType.IMPLANT,
            description=implant.name,
            quantity=implant.quantity,
            unit_price=implant.unit_price,
            source_type="ot.implant",
            source_id=implant.pk,
            actor=actor,
            request=request,
        )
        implant.is_billed = True
        implant.save(update_fields=["is_billed", "updated_at"])
    for consumable in SurgeryConsumable.objects.filter(
        surgery__patient=patient, is_billed=False
    ):
        post_charge(
            bill,
            item_type=BillItemType.CONSUMABLE,
            description=consumable.item,
            quantity=consumable.quantity,
            unit_price=consumable.unit_price,
            source_type="ot.surgeryconsumable",
            source_id=consumable.pk,
            actor=actor,
            request=request,
        )
        consumable.is_billed = True
        consumable.save(update_fields=["is_billed", "updated_at"])
    return bill


@transaction.atomic
def post_opd_charges(patient, *, actor=None, request=None) -> Bill:
    """Post completed OPD consultation fees to the patient's bill.

    Idempotent: an appointment is billed at most once, tracked by a
    ``BillItem`` with ``source_type="opd.appointment"`` (RULES Phase 12: charge
    posting *from OPD*).
    """
    from apps.opd.models import Appointment, AppointmentStatus

    bill = get_or_create_open_bill(patient, bill_type=BillType.OPD, actor=actor)
    appointments = Appointment.objects.filter(
        patient=patient, status=AppointmentStatus.COMPLETED
    ).select_related("doctor")
    for appointment in appointments:
        if BillItem.objects.filter(
            source_type="opd.appointment", source_id=str(appointment.pk)
        ).exists():
            continue
        fee = _dec(appointment.consultation_fee)
        if fee <= 0:
            continue
        doctor = appointment.doctor
        description = _("Consultation · %(n)s") % {
            "n": getattr(doctor, "name_en", doctor) if doctor else ""
        }
        post_charge(
            bill,
            item_type=BillItemType.CONSULTATION,
            description=description,
            quantity=1,
            unit_price=fee,
            service_date=appointment.appt_date,
            source_type="opd.appointment",
            source_id=appointment.pk,
            actor=actor,
            request=request,
        )
    return bill


@transaction.atomic
def create_package_bill(
    patient,
    package: ServicePackage,
    *,
    admission=None,
    vat_rate=None,
    actor=None,
    request=None,
) -> Bill:
    """Generate a PACKAGE invoice from a bundled rate card (PRD §4.7.1)."""
    bill = create_bill(
        patient,
        bill_type=BillType.PACKAGE,
        admission=admission,
        vat_rate=_dec(vat_rate) if vat_rate is not None else resolve_vat_rate(),
        notes=_("Package: %(p)s") % {"p": package.name},
        actor=actor,
        request=request,
    )
    components = list(package.components.all())
    if components:
        for component in components:
            post_charge(
                bill,
                item_type=component.item_type,
                description=component.description,
                quantity=component.quantity,
                unit_price=component.unit_price,
                service_date=timezone.localdate(),
                source_type="billing.packageitem",
                source_id=component.pk,
                actor=actor,
                request=request,
            )
    else:
        post_charge(
            bill,
            item_type=BillItemType.PACKAGE,
            description=package.name,
            quantity=1,
            unit_price=package.price,
            service_date=timezone.localdate(),
            source_type="billing.package",
            source_id=package.pk,
            actor=actor,
            request=request,
        )
    issue_bill(bill, actor=actor, request=request)
    return bill


# ---------------------------------------------------------------------------
# Credit notes (post-payment corrections)
# ---------------------------------------------------------------------------
@transaction.atomic
def create_credit_note(
    bill: Bill, *, amount, reason: str, actor=None, request=None
) -> CreditNote:
    value = _money(amount)
    if value <= 0:
        raise ValueError(_("Credit note amount must be greater than zero."))
    if value > _dec(bill.total):
        raise ValueError(_("Credit note cannot exceed the bill total."))
    note = CreditNote.objects.create(
        bill=bill,
        note_no=_next_number(SequenceKind.CREDIT),
        amount=value,
        reason=reason,
        created_by=_actor_id(actor),
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
def issue_credit_note(note: CreditNote, *, actor=None, request=None) -> CreditNote:
    if note.status != CreditNoteStatus.DRAFT:
        raise ValueError(_("Only draft credit notes can be issued."))
    bill = note.bill
    post_charge(
        bill,
        item_type=BillItemType.OTHER,
        description=_("Credit note %(no)s") % {"no": note.note_no},
        quantity=1,
        unit_price=-_dec(note.amount),
        tax_rate=0,
        source_type="billing.creditnote",
        source_id=note.pk,
        allow_locked=True,
        actor=actor,
        request=request,
    )
    note.status = CreditNoteStatus.ISSUED
    note.issued_at = timezone.now()
    note.save(update_fields=["status", "issued_at", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=note,
        changes={"status": CreditNoteStatus.ISSUED},
        user=actor,
        request=request,
    )
    accounting_hooks.on_credit_note_issued(note, actor=actor, request=request)
    return note


@transaction.atomic
def void_credit_note(note: CreditNote, *, actor=None, request=None) -> CreditNote:
    if note.status != CreditNoteStatus.ISSUED:
        raise ValueError(_("Only issued credit notes can be voided."))
    note.status = CreditNoteStatus.VOID
    note.voided_at = timezone.now()
    note.save(update_fields=["status", "voided_at", "updated_at"])
    bill = note.bill
    for bill_item in BillItem.objects.filter(
        source_type="billing.creditnote", source_id=str(note.pk)
    ):
        bill_item.delete()
    recompute_bill(bill)
    log_action(
        AuditAction.UPDATE,
        instance=note,
        changes={"status": CreditNoteStatus.VOID},
        user=actor,
        request=request,
    )
    accounting_hooks.on_credit_note_voided(note, actor=actor, request=request)
    return note


# ---------------------------------------------------------------------------
# Online payment gateway
# ---------------------------------------------------------------------------
@transaction.atomic
def initiate_online_payment(
    bill: Bill,
    *,
    method: str = PaymentMode.BKASH,
    amount=None,
    actor=None,
    request=None,
) -> Payment:
    """Start a gateway transaction and record a pending payment.

    Uses the configured gateway provider (a sandbox/mock provider by default —
    RULES Phase 12: *"Payment gateway integration (SSLCommerz or direct)"*).
    """
    from .gateways import get_gateway

    value = _money(amount) if amount is not None else bill.due_amount
    if value <= 0:
        raise ValueError(_("Payment amount must be greater than zero."))
    if value > bill.due_amount:
        raise ValueError(_("Payment exceeds the outstanding balance."))
    gateway = get_gateway(method)
    result = gateway.initiate(bill=bill, amount=value)
    payment = Payment.objects.create(
        bill=bill,
        method=method,
        amount=value,
        txn_ref=result.txn_id,
        gateway_ref=result.gateway_ref,
        received_by=_actor_id(actor),
    )
    log_action(
        AuditAction.PAYMENT,
        instance=payment,
        changes={"status": "initiated", "gateway": result.provider},
        user=actor,
        request=request,
    )
    return payment


@transaction.atomic
def confirm_online_payment(
    payment: Payment, *, success: bool = True, gateway_ref: str = "", actor=None, request=None
) -> Payment:
    """Confirm/cancel a pending online payment and finalise the receipt."""
    from .gateways import confirm_status

    if payment.bill.status == BillStatus.DRAFT:
        issue_bill(payment.bill, actor=actor, request=request)
    if gateway_ref:
        payment.gateway_ref = gateway_ref
        payment.save(update_fields=["gateway_ref", "updated_at"])
    if success:
        bill = payment.bill
        if bill.due_amount - _dec(payment.amount) < 0:
            raise ValueError(_("Payment exceeds the outstanding balance."))
        MoneyReceipt.objects.get_or_create(
            payment=payment,
            defaults={
                "receipt_no": _next_number(SequenceKind.RECEIPT),
                "amount": payment.amount,
                "issued_by": _actor_id(actor),
            },
        )
        bill.paid_amount = _dec(bill.paid_amount) + _dec(payment.amount)
        bill.save(update_fields=["paid_amount", "updated_at"])
        _refresh_status(bill)
        accounting_hooks.on_payment_recorded(payment, actor=actor, request=request)
        if bill.admission_id:
            settle_admission(bill.admission, actor=actor, request=request)
        log_action(
            AuditAction.PAYMENT,
            instance=payment,
            changes={"status": confirm_status(success)},
            user=actor,
            request=request,
        )
    else:
        payment.delete()
    return payment

