"""Cross-module auto-posting bridges.

Billing and pharmacy call these thin wrappers so that money movements reach the
general ledger without importing accounting internals directly. Every call is
best-effort: if accounting is misconfigured, the originating business operation
must still succeed, so failures are logged rather than raised.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _safe(label: str, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception:  # pragma: no cover - resilience over strictness
        logger.exception("Accounting auto-posting failed: %s", label)
        return None


def on_bill_issued(bill, *, actor=None, request=None):
    from . import services

    return _safe("bill", services.post_bill_journal, bill, actor=actor, request=request)


def on_bill_updated(bill, *, actor=None, request=None):
    from . import services

    return _safe("bill", services.post_bill_journal, bill, actor=actor, request=request)


def on_bill_cancelled(bill, *, actor=None, request=None):
    from . import services

    return _safe(
        "bill_cancel", services.clear_bill_journal, bill, actor=actor, request=request
    )


def on_payment_recorded(payment, *, actor=None, request=None):
    from . import services

    return _safe(
        "payment", services.post_payment_journal, payment, actor=actor, request=request
    )


def on_advance_created(advance, *, actor=None, request=None):
    from . import services

    return _safe(
        "advance", services.post_advance_journal, advance, actor=actor, request=request
    )


def on_refund_processed(refund, *, actor=None, request=None):
    from . import services

    return _safe(
        "refund", services.post_refund_journal, refund, actor=actor, request=request
    )


def on_credit_note_issued(note, *, actor=None, request=None):
    from . import services

    return _safe(
        "credit_note",
        services.post_credit_note_journal,
        note,
        actor=actor,
        request=request,
    )


def on_credit_note_voided(note, *, actor=None, request=None):
    from . import services

    return _safe(
        "credit_note_void",
        services.clear_credit_note_journal,
        note,
        actor=actor,
        request=request,
    )


def on_grn_received(grn, *, actor=None, request=None):
    from . import services

    return _safe("grn", services.post_grn_journal, grn, actor=actor, request=request)


def on_payroll_approved(run, *, actor=None, request=None):
    from . import services

    return _safe(
        "payroll", services.post_payroll_journal, run, actor=actor, request=request
    )


def on_payroll_paid(run, *, actor=None, request=None):
    from . import services

    return _safe(
        "payroll_payment",
        services.post_payroll_payment_journal,
        run,
        actor=actor,
        request=request,
    )


def on_salary_adjustment(adjustment, *, actor=None, request=None):
    from . import services

    return _safe(
        "salary_adjustment",
        services.post_salary_adjustment_journal,
        adjustment,
        actor=actor,
        request=request,
    )
