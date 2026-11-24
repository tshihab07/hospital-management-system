"""Write operations for the Accounting module (atomic + audited).

Everything that touches the general ledger lives here:

* chart-of-accounts provisioning,
* balanced journal creation, posting and reversal,
* automatic postings triggered by billing events (bill issued / charges,
  payments, refunds, credit notes, advances),
* pharmacy goods receipts (accounts payable) and
* manual expenses / vendor payments.

Postings are idempotent per source document: re-posting a bill first clears the
previous automatic entry (reversing it if it was already posted) so the ledger
always mirrors the current document without ever editing history.
"""

from __future__ import annotations

import calendar
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from core.audit import AuditAction, log_action, model_to_dict_safe

from .chart import DEFAULT_ACCOUNTS
from .models import (
    Account,
    AccountingPeriod,
    AccountingSequence,
    Expense,
    JournalEntry,
    JournalEntryType,
    JournalLine,
    JournalStatus,
    PartyType,
    SystemAccount,
    VendorPayment,
    _dec,
)

# Source document tags (stored on JournalEntry.source_type).
SOURCE_BILL = "billing.bill"
SOURCE_PAYMENT = "billing.payment"
SOURCE_REFUND = "billing.refund"
SOURCE_CREDIT_NOTE = "billing.creditnote"
SOURCE_ADVANCE = "billing.advance"
SOURCE_GRN = "pharmacy.grn"
SOURCE_EXPENSE = "accounting.expense"
SOURCE_VENDOR_PAYMENT = "accounting.vendorpayment"
SOURCE_PAYROLL = "payroll.run"
SOURCE_PAYROLL_PAYMENT = "payroll.payment"
SOURCE_PAYROLL_ADJUSTMENT = "payroll.adjustment"

# Maps a billing line type to the revenue control account it credits.
BILL_ITEM_REVENUE: dict[str, str] = {
    "consultation": SystemAccount.REVENUE_CONSULTATION,
    "pharmacy": SystemAccount.REVENUE_PHARMACY,
    "lab": SystemAccount.REVENUE_LAB,
    "bed": SystemAccount.REVENUE_BED,
    "nursing": SystemAccount.REVENUE_BED,
    "doctor_visit": SystemAccount.REVENUE_DOCTOR_VISIT,
    "procedure": SystemAccount.REVENUE_PROCEDURE,
    "ot": SystemAccount.REVENUE_OT,
    "implant": SystemAccount.REVENUE_IMPLANT,
    "consumable": SystemAccount.REVENUE_IMPLANT,
    "emergency": SystemAccount.REVENUE_EMERGENCY,
    "package": SystemAccount.REVENUE_PACKAGE,
    "other": SystemAccount.REVENUE_OTHER,
}

# Maps a payment mode to the asset account money lands in.
MODE_ASSET_ACCOUNT: dict[str, str] = {
    "cash": SystemAccount.CASH,
    "bank": SystemAccount.BANK,
    "card": SystemAccount.CARD,
    "bkash": SystemAccount.MFS,
    "nagad": SystemAccount.MFS,
    "rocket": SystemAccount.MFS,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _money(value) -> Decimal:
    return _dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _actor_id(actor):
    return actor if getattr(actor, "pk", None) else None


def _next_entry_number() -> str:
    now = timezone.localtime()
    seq, _ = AccountingSequence.objects.select_for_update().get_or_create(year=now.year)
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    prefix = settings.IHMS.get("JOURNAL_PREFIX", "JE")
    width = int(settings.IHMS.get("JOURNAL_NUMBER_WIDTH", 5))
    return f"{prefix}-{now.year}-{seq.last_number:0{width}d}"


def ensure_period(day) -> AccountingPeriod | None:
    """Return (creating if needed) the monthly fiscal period containing ``day``."""
    if day is None:
        return None
    period = AccountingPeriod.objects.filter(
        start_date__lte=day, end_date__gte=day
    ).first()
    if period is not None:
        return period
    last_day = calendar.monthrange(day.year, day.month)[1]
    start = day.replace(day=1)
    end = day.replace(day=last_day)
    return AccountingPeriod.objects.create(
        name=f"{day.year}-{day.month:02d}",
        start_date=start,
        end_date=end,
    )


# ---------------------------------------------------------------------------
# Chart of accounts provisioning
# ---------------------------------------------------------------------------
@transaction.atomic
def seed_chart_of_accounts(*, actor=None) -> dict:
    """Create the default hospital chart of accounts (idempotent).

    Returns ``{"created": n, "existing": n}``.
    """
    created = 0
    existing = 0
    by_code: dict[str, Account] = {}
    for (
        code,
        name,
        name_bn,
        acc_type,
        _parent,
        is_group,
        key,
        opening,
    ) in DEFAULT_ACCOUNTS:
        account = Account.objects.filter(code=code).first()
        if account is None:
            account = Account.objects.create(
                code=code,
                name=name,
                name_bn=name_bn,
                account_type=acc_type,
                is_group=is_group,
                system_key=key,
                opening_balance=_dec(opening),
                created_by=_actor_id(actor),
            )
            created += 1
        else:
            existing += 1
        by_code[code] = account
    # Second pass: wire up parents now that every account exists.
    for code, _name, _bn, _type, parent_code, *_rest in DEFAULT_ACCOUNTS:
        if (
            parent_code
            and by_code.get(code)
            and by_code[code].parent_id != by_code[parent_code].pk
        ):
            by_code[code].parent = by_code[parent_code]
            by_code[code].save(update_fields=["parent", "updated_at"])
    return {"created": created, "existing": existing}


def get_system_account(key: str) -> Account:
    """Return the control account for ``key``, provisioning the chart if needed."""
    account = Account.objects.filter(system_key=key).first()
    if account is None:
        seed_chart_of_accounts()
        account = Account.objects.filter(system_key=key).first()
    if account is None:
        raise ValueError(
            _("Accounting control account '%(key)s' is not configured.") % {"key": key}
        )
    return account


def _asset_account_for_method(method: str) -> Account:
    key = MODE_ASSET_ACCOUNT.get(method, SystemAccount.CASH)
    return get_system_account(key)


# ---------------------------------------------------------------------------
# Journals
# ---------------------------------------------------------------------------
def _build_lines(entry: JournalEntry, lines: list[dict]) -> Decimal:
    """Persist ``lines`` on ``entry`` and return the total debit."""
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for row in lines:
        debit = _money(row.get("debit", 0))
        credit = _money(row.get("credit", 0))
        if debit < 0 or credit < 0:
            raise ValueError(_("Journal line amounts cannot be negative."))
        if debit == 0 and credit == 0:
            raise ValueError(_("A journal line needs a debit or a credit amount."))
        account = row["account"]
        if account.is_group:
            raise ValueError(
                _("'%(name)s' is a group account and cannot be posted to.")
                % {"name": account}
            )
        JournalLine.objects.create(
            journal=entry,
            account=account,
            description=row.get("description", ""),
            debit=debit,
            credit=credit,
            party_type=row.get("party_type", ""),
            party_id=str(row.get("party_id", "") or ""),
            department=row.get("department"),
            doctor=row.get("doctor"),
            bill=row.get("bill"),
        )
        total_debit += debit
        total_credit += credit
    if total_debit != total_credit:
        raise ValueError(
            _("Journal is not balanced: debit %(d)s ≠ credit %(c)s.")
            % {
                "d": f"{total_debit:.2f}",
                "c": f"{total_credit:.2f}",
            }
        )
    if total_debit <= 0:
        raise ValueError(_("A journal entry must have a non-zero amount."))
    return total_debit


def create_journal_entry(
    *,
    date=None,
    lines: list[dict],
    entry_type: str = JournalEntryType.MANUAL,
    memo: str = "",
    reference: str = "",
    source_type: str = "",
    source_id: str = "",
    actor=None,
    request=None,
    post: bool = True,
) -> JournalEntry:
    """Create, balance-check and (optionally) post a journal entry."""
    day = date or timezone.localdate()
    period = ensure_period(day)
    if period is not None and period.is_closed:
        raise ValueError(_("The accounting period for this date is closed."))
    entry = JournalEntry.objects.create(
        entry_no=_next_entry_number(),
        date=day,
        entry_type=entry_type,
        status=JournalStatus.DRAFT,
        memo=memo,
        reference=reference,
        period=period,
        source_type=source_type,
        source_id=str(source_id or ""),
        created_by=_actor_id(actor),
    )
    total = _build_lines(entry, lines)
    entry.total_debit = total
    entry.total_credit = total
    entry.save(update_fields=["total_debit", "total_credit", "updated_at"])
    if post:
        post_journal_entry(entry, actor=actor, request=request)
    log_action(
        AuditAction.CREATE,
        instance=entry,
        changes=model_to_dict_safe(entry),
        user=actor,
        request=request,
    )
    return entry


@transaction.atomic
def post_journal_entry(
    entry: JournalEntry, *, actor=None, request=None
) -> JournalEntry:
    """Post a draft entry, locking it against further edits."""
    if entry.status == JournalStatus.POSTED:
        return entry
    if entry.status == JournalStatus.REVERSED:
        raise ValueError(_("A reversed journal cannot be posted again."))
    entry.recompute(save=False)
    if not entry.is_balanced:
        raise ValueError(_("Journal is not balanced and cannot be posted."))
    if entry.period is not None and entry.period.is_closed:
        raise ValueError(_("The accounting period is closed."))
    entry.status = JournalStatus.POSTED
    entry.posted_by = _actor_id(actor)
    entry.posted_at = timezone.now()
    entry.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])
    log_action(
        AuditAction.APPROVE,
        instance=entry,
        changes={"status": JournalStatus.POSTED},
        user=actor,
        request=request,
    )
    return entry


@transaction.atomic
def reverse_journal_entry(
    entry: JournalEntry, *, date=None, memo: str = "", actor=None, request=None
) -> JournalEntry:
    """Post a mirrored entry that reverses a posted journal, then mark it reversed."""
    if entry.status != JournalStatus.POSTED:
        raise ValueError(_("Only posted journals can be reversed."))
    reversal = JournalEntry.objects.create(
        entry_no=_next_entry_number(),
        date=date or entry.date,
        entry_type=JournalEntryType.REVERSAL,
        status=JournalStatus.DRAFT,
        memo=memo or _("Reversal of %(no)s") % {"no": entry.entry_no},
        reference=entry.reference,
        period=ensure_period(date or entry.date),
        source_type=entry.source_type,
        source_id=entry.source_id,
        reversal_of=entry,
        created_by=_actor_id(actor),
    )
    total = Decimal("0")
    for line in entry.lines.all():
        total += _money(line.debit) + _money(line.credit)
        JournalLine.objects.create(
            journal=reversal,
            account=line.account,
            description=line.description,
            debit=line.credit,
            credit=line.debit,
            party_type=line.party_type,
            party_id=line.party_id,
            department=line.department,
            doctor=line.doctor,
            bill=line.bill,
        )
    reversal.total_debit = reversal.lines.aggregate(t=Sum("debit"))["t"] or Decimal("0")
    reversal.total_credit = reversal.lines.aggregate(t=Sum("credit"))["t"] or Decimal(
        "0"
    )
    reversal.save(update_fields=["total_debit", "total_credit", "updated_at"])
    post_journal_entry(reversal, actor=actor, request=request)
    entry.status = JournalStatus.REVERSED
    entry.save(update_fields=["status", "updated_at"])
    log_action(
        AuditAction.UPDATE,
        instance=entry,
        changes={"status": JournalStatus.REVERSED, "reversal": reversal.entry_no},
        user=actor,
        request=request,
    )
    return reversal


def _clear_source_journals(
    source_type: str, source_id, *, actor=None, request=None, only_drafts: bool = False
) -> None:
    """Remove outstanding automatic journals for a source document.

    Posted entries are reversed (never deleted); drafts are deleted outright.
    """
    qs = (
        JournalEntry.objects.filter(source_type=source_type, source_id=str(source_id))
        .exclude(status=JournalStatus.REVERSED)
        .exclude(entry_type=JournalEntryType.REVERSAL)
    )
    for entry in qs:
        if entry.status == JournalStatus.DRAFT:
            entry.lines.all().delete()
            entry.delete(hard=True)
        elif not only_drafts:
            reverse_journal_entry(entry, actor=actor, request=request)


# ---------------------------------------------------------------------------
# Attribution helpers (department / doctor analytics)
# ---------------------------------------------------------------------------
def _department_by_type(type_value: str):
    from apps.masters.models import Department

    dept = Department.objects.filter(type=type_value).order_by("pk").first()
    return dept


def _item_attribution(item, bill) -> tuple:
    """Best-effort ``(department, doctor)`` for a bill item."""
    from apps.masters.models import DepartmentType

    item_type = item.item_type
    department = None
    doctor = None
    try:
        if item_type == "consultation":
            from apps.opd.models import Appointment

            appt = (
                Appointment.objects.select_related("doctor__department")
                .filter(pk=item.source_id)
                .first()
            )
            if appt and appt.doctor:
                doctor = appt.doctor
                department = appt.doctor.department
        elif item_type == "lab":
            from apps.lab.models import LabCharge

            charge = (
                LabCharge.objects.select_related("order__doctor")
                .filter(pk=item.source_id)
                .first()
            )
            if charge and charge.order and charge.order.doctor:
                doctor = charge.order.doctor
                department = getattr(doctor, "department", None)
            if department is None:
                department = _department_by_type(DepartmentType.LAB)
        elif item_type == "pharmacy":
            department = _department_by_type(DepartmentType.PHARMACY)
        elif item_type in ("bed", "nursing", "doctor_visit"):
            if bill.admission_id and bill.admission.doctor_id:
                doctor = bill.admission.doctor
            department = _department_by_type(DepartmentType.IPD)
        elif item_type in ("ot", "implant", "consumable"):
            if bill.admission_id and bill.admission.doctor_id:
                doctor = bill.admission.doctor
            department = _department_by_type(DepartmentType.OT)
        elif item_type == "emergency":
            department = _department_by_type(DepartmentType.EMERGENCY)
        elif item_type in ("procedure", "package"):
            department = _department_by_type(DepartmentType.OPD)
    except Exception:  # pragma: no cover - attribution is best-effort only
        return None, None
    return department, doctor


# ---------------------------------------------------------------------------
# Auto-posting: billing events
# ---------------------------------------------------------------------------
def post_bill_journal(bill, *, actor=None, request=None) -> JournalEntry | None:
    """Post (or refresh) the revenue entry for a bill.

    Debit Accounts Receivable; credit the per-service revenue accounts and
    output VAT; debit Discount Allowed. Only applies while the bill is unpaid —
    once money has moved, corrections go through a credit note.
    """
    if bill.status in ("cancelled", "draft"):
        return None
    if _dec(bill.paid_amount) > 0:
        return None
    _clear_source_journals(SOURCE_BILL, bill.pk, actor=actor, request=request)

    ar = get_system_account(SystemAccount.AR)
    lines: list[dict] = []
    if _dec(bill.total) > 0:
        lines.append(
            {
                "account": ar,
                "debit": _dec(bill.total),
                "description": _("Bill %(no)s") % {"no": bill.bill_no},
                "party_type": PartyType.PATIENT,
                "party_id": bill.patient_id,
                "bill": bill,
            }
        )
    # Group revenue by control account with department/doctor attribution.
    grouped: dict[int, dict] = {}
    for item in bill.items.all():
        key = BILL_ITEM_REVENUE.get(item.item_type, SystemAccount.REVENUE_OTHER)
        account = get_system_account(key)
        department, doctor = _item_attribution(item, bill)
        bucket = grouped.setdefault(
            account.pk,
            {
                "account": account,
                "amount": Decimal("0"),
                "department": department,
                "doctor": doctor,
            },
        )
        bucket["amount"] += _dec(item.amount)
        if bucket["department"] is None and department is not None:
            bucket["department"] = department
        if bucket["doctor"] is None and doctor is not None:
            bucket["doctor"] = doctor
    for bucket in grouped.values():
        amount = _money(bucket["amount"])
        if amount == 0:
            continue
        lines.append(
            {
                "account": bucket["account"],
                "credit" if amount > 0 else "debit": abs(amount),
                "description": _("Revenue · %(no)s") % {"no": bill.bill_no},
                "department": bucket["department"],
                "doctor": bucket["doctor"],
                "bill": bill,
            }
        )
    if _dec(bill.vat) > 0:
        lines.append(
            {
                "account": get_system_account(SystemAccount.VAT_PAYABLE),
                "credit": _dec(bill.vat),
                "description": _("Output VAT · %(no)s") % {"no": bill.bill_no},
                "bill": bill,
            }
        )
    if _dec(bill.discount) > 0:
        lines.append(
            {
                "account": get_system_account(SystemAccount.DISCOUNT),
                "debit": _dec(bill.discount),
                "description": _("Discount · %(no)s") % {"no": bill.bill_no},
                "bill": bill,
            }
        )
    if not lines:
        return None
    return create_journal_entry(
        date=bill.issued_at.date() if bill.issued_at else timezone.localdate(),
        lines=lines,
        entry_type=JournalEntryType.AUTO,
        memo=_("Bill %(no)s") % {"no": bill.bill_no},
        reference=bill.bill_no,
        source_type=SOURCE_BILL,
        source_id=bill.pk,
        actor=actor,
        request=request,
    )


def clear_bill_journal(bill, *, actor=None, request=None) -> None:
    """Reverse the automatic revenue journal for a cancelled bill."""
    _clear_source_journals(SOURCE_BILL, bill.pk, actor=actor, request=request)


def post_payment_journal(payment, *, actor=None, request=None) -> JournalEntry | None:
    """Debit cash/bank (or patient advance), credit Accounts Receivable."""
    if JournalEntry.objects.filter(
        source_type=SOURCE_PAYMENT,
        source_id=str(payment.pk),
        status=JournalStatus.POSTED,
    ).exists():
        return None
    amount = _dec(payment.amount)
    if amount <= 0:
        return None
    # Detect an advance adjustment (settled from a patient deposit).
    advance_used = False
    if payment.txn_ref:
        from apps.billing.models import Advance

        advance_used = Advance.objects.filter(advance_no=payment.txn_ref).exists()
    if not advance_used and payment.notes.startswith("Advance adjustment"):
        advance_used = True
    debit_account = (
        get_system_account(SystemAccount.PATIENT_ADVANCE)
        if advance_used
        else _asset_account_for_method(payment.method)
    )
    bill = payment.bill
    lines = [
        {
            "account": debit_account,
            "debit": amount,
            "description": _("Payment · %(no)s") % {"no": bill.bill_no},
            "party_type": PartyType.PATIENT,
            "party_id": bill.patient_id,
            "bill": bill,
        },
        {
            "account": get_system_account(SystemAccount.AR),
            "credit": amount,
            "description": _("Receipt · %(no)s") % {"no": bill.bill_no},
            "party_type": PartyType.PATIENT,
            "party_id": bill.patient_id,
            "bill": bill,
        },
    ]
    return create_journal_entry(
        date=payment.paid_at.date() if payment.paid_at else timezone.localdate(),
        lines=lines,
        entry_type=JournalEntryType.AUTO,
        memo=_("Payment for %(no)s") % {"no": bill.bill_no},
        reference=payment.txn_ref or bill.bill_no,
        source_type=SOURCE_PAYMENT,
        source_id=payment.pk,
        actor=actor,
        request=request,
    )


def post_refund_journal(refund, *, actor=None, request=None) -> JournalEntry | None:
    """Debit Accounts Receivable, credit cash/bank (money leaves the hospital)."""
    if JournalEntry.objects.filter(
        source_type=SOURCE_REFUND, source_id=str(refund.pk), status=JournalStatus.POSTED
    ).exists():
        return None
    amount = _dec(refund.amount)
    if amount <= 0:
        return None
    bill = refund.bill
    lines = [
        {
            "account": get_system_account(SystemAccount.AR),
            "debit": amount,
            "description": _("Refund %(no)s") % {"no": refund.refund_no},
            "party_type": PartyType.PATIENT,
            "party_id": bill.patient_id if bill else "",
            "bill": bill,
        },
        {
            "account": _asset_account_for_method(refund.method),
            "credit": amount,
            "description": _("Refund paid · %(no)s") % {"no": refund.refund_no},
        },
    ]
    return create_journal_entry(
        date=refund.refunded_at.date() if refund.refunded_at else timezone.localdate(),
        lines=lines,
        entry_type=JournalEntryType.AUTO,
        memo=_("Refund %(no)s") % {"no": refund.refund_no},
        reference=refund.refund_no,
        source_type=SOURCE_REFUND,
        source_id=refund.pk,
        actor=actor,
        request=request,
    )


def post_credit_note_journal(note, *, actor=None, request=None) -> JournalEntry | None:
    """Debit Sales Returns (contra revenue), credit Accounts Receivable."""
    if JournalEntry.objects.filter(
        source_type=SOURCE_CREDIT_NOTE,
        source_id=str(note.pk),
        status=JournalStatus.POSTED,
    ).exists():
        return None
    amount = _dec(note.amount)
    if amount <= 0:
        return None
    bill = note.bill
    lines = [
        {
            "account": get_system_account(SystemAccount.SALES_RETURN),
            "debit": amount,
            "description": _("Credit note %(no)s") % {"no": note.note_no},
        },
        {
            "account": get_system_account(SystemAccount.AR),
            "credit": amount,
            "description": _("Credit note %(no)s") % {"no": note.note_no},
            "party_type": PartyType.PATIENT,
            "party_id": bill.patient_id,
            "bill": bill,
        },
    ]
    return create_journal_entry(
        date=note.issued_at.date() if note.issued_at else timezone.localdate(),
        lines=lines,
        entry_type=JournalEntryType.AUTO,
        memo=_("Credit note %(no)s") % {"no": note.note_no},
        reference=note.note_no,
        source_type=SOURCE_CREDIT_NOTE,
        source_id=note.pk,
        actor=actor,
        request=request,
    )


def clear_credit_note_journal(note, *, actor=None, request=None) -> None:
    """Reverse the automatic journal for a voided credit note."""
    _clear_source_journals(SOURCE_CREDIT_NOTE, note.pk, actor=actor, request=request)


def post_advance_journal(advance, *, actor=None, request=None) -> JournalEntry | None:
    """Debit cash/bank, credit Patient Advances (a liability)."""
    if JournalEntry.objects.filter(
        source_type=SOURCE_ADVANCE,
        source_id=str(advance.pk),
        status=JournalStatus.POSTED,
    ).exists():
        return None
    amount = _dec(advance.amount)
    if amount <= 0:
        return None
    lines = [
        {
            "account": _asset_account_for_method(advance.method),
            "debit": amount,
            "description": _("Advance %(no)s") % {"no": advance.advance_no},
            "party_type": PartyType.PATIENT,
            "party_id": advance.patient_id,
        },
        {
            "account": get_system_account(SystemAccount.PATIENT_ADVANCE),
            "credit": amount,
            "description": _("Patient advance %(no)s") % {"no": advance.advance_no},
            "party_type": PartyType.PATIENT,
            "party_id": advance.patient_id,
        },
    ]
    return create_journal_entry(
        date=advance.paid_at.date() if advance.paid_at else timezone.localdate(),
        lines=lines,
        entry_type=JournalEntryType.AUTO,
        memo=_("Patient advance %(no)s") % {"no": advance.advance_no},
        reference=advance.advance_no,
        source_type=SOURCE_ADVANCE,
        source_id=advance.pk,
        actor=actor,
        request=request,
    )


# ---------------------------------------------------------------------------
# Auto-posting: pharmacy / accounts payable
# ---------------------------------------------------------------------------
def post_grn_journal(grn, *, actor=None, request=None) -> JournalEntry | None:
    """Debit Inventory (pharmacy stock), credit Accounts Payable (vendor)."""
    if JournalEntry.objects.filter(
        source_type=SOURCE_GRN, source_id=str(grn.pk), status=JournalStatus.POSTED
    ).exists():
        return None
    amount = _dec(grn.total_amount)
    if amount <= 0:
        return None
    lines = [
        {
            "account": get_system_account(SystemAccount.INVENTORY),
            "debit": amount,
            "description": _("Goods received · %(no)s") % {"no": grn.grn_number},
        },
        {
            "account": get_system_account(SystemAccount.AP),
            "credit": amount,
            "description": _("Vendor payable · %(no)s") % {"no": grn.grn_number},
            "party_type": PartyType.VENDOR,
            "party_id": grn.vendor_id,
        },
    ]
    return create_journal_entry(
        date=grn.received_date or timezone.localdate(),
        lines=lines,
        entry_type=JournalEntryType.AUTO,
        memo=_("GRN %(no)s") % {"no": grn.grn_number},
        reference=grn.grn_number,
        source_type=SOURCE_GRN,
        source_id=grn.pk,
        actor=actor,
        request=request,
    )


# ---------------------------------------------------------------------------
# Expenses / vendor payments
# ---------------------------------------------------------------------------
@transaction.atomic
def create_expense(
    *,
    category: Account,
    paid_from: Account,
    amount,
    description: str,
    date=None,
    vendor=None,
    reference: str = "",
    actor=None,
    request=None,
) -> Expense:
    value = _money(amount)
    if value <= 0:
        raise ValueError(_("Expense amount must be greater than zero."))
    day = date or timezone.localdate()
    expense = Expense.objects.create(
        date=day,
        category=category,
        paid_from=paid_from,
        amount=value,
        description=description,
        vendor=vendor,
        reference=reference,
        created_by=_actor_id(actor),
    )
    party_type = PartyType.VENDOR if vendor is not None else ""
    entry = create_journal_entry(
        date=day,
        lines=[
            {
                "account": category,
                "debit": value,
                "description": description,
            },
            {
                "account": paid_from,
                "credit": value,
                "description": description,
                "party_type": party_type,
                "party_id": vendor.pk if vendor is not None else "",
            },
        ],
        entry_type=JournalEntryType.AUTO,
        memo=_("Expense · %(desc)s") % {"desc": description},
        reference=reference,
        source_type=SOURCE_EXPENSE,
        source_id=expense.pk,
        actor=actor,
        request=request,
    )
    expense.journal = entry
    expense.save(update_fields=["journal", "updated_at"])
    log_action(
        AuditAction.CREATE,
        instance=expense,
        changes=model_to_dict_safe(expense),
        user=actor,
        request=request,
    )
    return expense


@transaction.atomic
def create_vendor_payment(
    *,
    vendor,
    amount,
    method: str = "cash",
    date=None,
    grn=None,
    reference: str = "",
    notes: str = "",
    actor=None,
    request=None,
) -> VendorPayment:
    value = _money(amount)
    if value <= 0:
        raise ValueError(_("Payment amount must be greater than zero."))
    day = date or timezone.localdate()
    payment = VendorPayment.objects.create(
        date=day,
        vendor=vendor,
        amount=value,
        method=method,
        grn=grn,
        reference=reference,
        notes=notes,
        created_by=_actor_id(actor),
    )
    entry = create_journal_entry(
        date=day,
        lines=[
            {
                "account": get_system_account(SystemAccount.AP),
                "debit": value,
                "description": _("Vendor payment"),
                "party_type": PartyType.VENDOR,
                "party_id": vendor.pk,
            },
            {
                "account": _asset_account_for_method(method),
                "credit": value,
                "description": _("Vendor payment"),
            },
        ],
        entry_type=JournalEntryType.AUTO,
        memo=_("Vendor payment · %(v)s") % {"v": vendor},
        reference=reference,
        source_type=SOURCE_VENDOR_PAYMENT,
        source_id=payment.pk,
        actor=actor,
        request=request,
    )
    payment.journal = entry
    payment.save(update_fields=["journal", "updated_at"])
    log_action(
        AuditAction.PAYMENT,
        instance=payment,
        changes=model_to_dict_safe(payment),
        user=actor,
        request=request,
    )
    return payment


# ---------------------------------------------------------------------------
# Auto-posting: payroll
# ---------------------------------------------------------------------------
def post_payroll_journal(run, *, actor=None, request=None) -> JournalEntry | None:
    """Accrue a payroll run to the ledger.

    Debit salaries & wages (earned salary, net of absence/late/unpaid-leave
    deductions) and employer PF; credit PF payable (employee + employer),
    income-tax payable, other payroll deductions payable and net salaries
    payable. Idempotent per run.
    """
    if run.journal_id:
        return run.journal
    existing = JournalEntry.objects.filter(
        source_type=SOURCE_PAYROLL,
        source_id=str(run.pk),
        status=JournalStatus.POSTED,
    ).first()
    if existing is not None:
        return existing

    payslips = list(run.payslips.all())
    if not payslips:
        return None
    salary_expense = sum(
        (p.gross_salary - p.attendance_deduction for p in payslips), Decimal("0")
    )
    employer_pf = sum((p.pf_employer for p in payslips), Decimal("0"))
    employee_pf = sum((p.pf_employee for p in payslips), Decimal("0"))
    tax_total = sum((p.tax for p in payslips), Decimal("0"))
    adj_deduction = sum((p.adjustment_deduction for p in payslips), Decimal("0"))
    net_total = sum((p.net_pay for p in payslips), Decimal("0"))

    lines: list[dict] = []
    if salary_expense > 0:
        lines.append(
            {
                "account": get_system_account(SystemAccount.EXPENSE_SALARY),
                "debit": salary_expense,
                "description": _("Salaries · %(c)s") % {"c": run.code},
                "party_type": PartyType.STAFF,
            }
        )
    if employer_pf > 0:
        lines.append(
            {
                "account": get_system_account(SystemAccount.EXPENSE_STAFF_BENEFITS),
                "debit": employer_pf,
                "description": _("Employer PF · %(c)s") % {"c": run.code},
            }
        )
    pf_total = employee_pf + employer_pf
    if pf_total > 0:
        lines.append(
            {
                "account": get_system_account(SystemAccount.PF_PAYABLE),
                "credit": pf_total,
                "description": _("Provident fund · %(c)s") % {"c": run.code},
            }
        )
    if tax_total > 0:
        lines.append(
            {
                "account": get_system_account(SystemAccount.TAX_PAYABLE),
                "credit": tax_total,
                "description": _("Income tax · %(c)s") % {"c": run.code},
            }
        )
    if adj_deduction > 0:
        lines.append(
            {
                "account": get_system_account(SystemAccount.DEDUCTIONS_PAYABLE),
                "credit": adj_deduction,
                "description": _("Payroll deductions · %(c)s") % {"c": run.code},
            }
        )
    if net_total > 0:
        lines.append(
            {
                "account": get_system_account(SystemAccount.SALARY_PAYABLE),
                "credit": net_total,
                "description": _("Net salaries payable · %(c)s") % {"c": run.code},
            }
        )
    if not lines:
        return None
    entry = create_journal_entry(
        date=run.period_end,
        lines=lines,
        entry_type=JournalEntryType.AUTO,
        memo=_("Payroll %(c)s") % {"c": run.code},
        reference=run.code,
        source_type=SOURCE_PAYROLL,
        source_id=run.pk,
        actor=actor,
        request=request,
    )
    run.journal = entry
    run.save(update_fields=["journal", "updated_at"])
    return entry


def post_payroll_payment_journal(run, *, actor=None, request=None) -> JournalEntry | None:
    """Disburse net salaries: debit Salaries Payable, credit cash/bank."""
    if run.payment_journal_id:
        return run.payment_journal
    if JournalEntry.objects.filter(
        source_type=SOURCE_PAYROLL_PAYMENT,
        source_id=str(run.pk),
        status=JournalStatus.POSTED,
    ).exists():
        return None
    net_total = _dec(run.total_net)
    if net_total <= 0:
        return None
    method = getattr(run, "payment_method", "bank") or "bank"
    entry = create_journal_entry(
        date=run.payment_date or run.period_end,
        lines=[
            {
                "account": get_system_account(SystemAccount.SALARY_PAYABLE),
                "debit": net_total,
                "description": _("Salary payment · %(c)s") % {"c": run.code},
                "party_type": PartyType.STAFF,
            },
            {
                "account": _asset_account_for_method(method),
                "credit": net_total,
                "description": _("Salary payment · %(c)s") % {"c": run.code},
            },
        ],
        entry_type=JournalEntryType.AUTO,
        memo=_("Salary disbursement %(c)s") % {"c": run.code},
        reference=run.code,
        source_type=SOURCE_PAYROLL_PAYMENT,
        source_id=run.pk,
        actor=actor,
        request=request,
    )
    run.payment_journal = entry
    run.save(update_fields=["payment_journal", "updated_at"])
    return entry


def post_salary_adjustment_journal(
    adjustment, *, actor=None, request=None
) -> JournalEntry | None:
    """Post a standalone correction for a locked payroll run."""
    if adjustment.journal_id:
        return adjustment.journal
    amount = _dec(adjustment.amount)
    if amount <= 0:
        return None
    is_earning = getattr(adjustment, "kind", "earning") == "earning"
    salary_account = get_system_account(SystemAccount.EXPENSE_SALARY)
    payable = get_system_account(SystemAccount.SALARY_PAYABLE)
    if is_earning:
        lines = [
            {"account": salary_account, "debit": amount},
            {"account": payable, "credit": amount},
        ]
    else:
        lines = [
            {"account": payable, "debit": amount},
            {
                "account": get_system_account(SystemAccount.DEDUCTIONS_PAYABLE),
                "credit": amount,
            },
        ]
    description = getattr(adjustment, "reason", "") or _("Salary adjustment")
    for line in lines:
        line["description"] = description
        line["party_type"] = PartyType.STAFF
        line["party_id"] = getattr(adjustment, "staff_id", "")
    entry = create_journal_entry(
        date=timezone.localdate(),
        lines=lines,
        entry_type=JournalEntryType.ADJUSTMENT,
        memo=_("Salary adjustment · %(s)s") % {"s": adjustment.staff},
        reference=f"ADJ-{adjustment.pk}",
        source_type=SOURCE_PAYROLL_ADJUSTMENT,
        source_id=adjustment.pk,
        actor=actor,
        request=request,
    )
    adjustment.journal = entry
    adjustment.save(update_fields=["journal", "updated_at"])
    return entry


# ---------------------------------------------------------------------------
# Period close
# ---------------------------------------------------------------------------
@transaction.atomic
def close_period(
    period: AccountingPeriod, *, actor=None, request=None
) -> AccountingPeriod:
    if period.is_closed:
        return period
    period.is_closed = True
    period.closed_by = _actor_id(actor)
    period.closed_at = timezone.now()
    period.save(update_fields=["is_closed", "closed_by", "closed_at", "updated_at"])
    log_action(
        AuditAction.APPROVE,
        instance=period,
        changes={"is_closed": True},
        user=actor,
        request=request,
    )
    return period
