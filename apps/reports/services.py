"""Write-side services for the Reports & Analytics module (RULES Phase 16).

Responsibilities:

* run an ad-hoc report and persist a :class:`ReportRun` with the rendered file;
* execute a :class:`ReportSchedule` (render + persist + email recipients);
* advance a schedule's ``next_run`` (idempotent, safe to call repeatedly);
* collect due schedules for the ``send_scheduled_reports`` command.

The heavy lifting lives in :mod:`apps.reports.selectors` (data) and
:mod:`apps.reports.exports` (rendering); these functions only orchestrate.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone

from core.audit import AuditAction, log_action

from . import exports, selectors
from .models import ReportFormat, ReportRun, ReportRunStatus, ReportSchedule

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _period_for(schedule: ReportSchedule):
    return selectors.default_range(parameters=schedule.parameters)


def _recipients_for(run: ReportRun) -> list[str]:
    if run.schedule_id and run.schedule:
        return run.schedule.recipient_list
    raw = (run.emailed_to or "").replace(",", "\n")
    return [addr.strip() for addr in raw.splitlines() if addr.strip()]


def send_report_email(run: ReportRun) -> int:
    """Email a generated report to the schedule's recipients.

    Returns the number of recipients the message was addressed to. Failures are
    logged and never raised so a mail outage cannot lose the generated run.
    """
    recipients = _recipients_for(run)
    if not recipients or not run.file:
        return 0
    subject = f"[IHMS] {run.get_report_type_display()}"
    if run.period_start and run.period_end:
        subject += f" · {run.period_start:%d/%m/%Y}–{run.period_end:%d/%m/%Y}"
    body = (
        "Automated report from the Integrated Hospital Management System.\n\n"
        f"Report: {run.get_report_type_display()}\n"
        f"Format: {run.get_report_format_display()}\n"
        f"Rows: {run.row_count}\n"
    )
    message = EmailMessage(subject=subject, body=body, to=recipients)
    try:
        run.file.open("rb")
        message.attach(run.filename, run.file.read(), _content_type(run.report_format))
        run.file.close()
        message.send(fail_silently=False)
    except Exception as exc:  # pragma: no cover - mail backend dependent
        logger.warning("Report email failed for run %s: %s", run.pk, exc)
        return 0
    return len(recipients)


def _content_type(fmt: str) -> str:
    return exports.CONTENT_TYPES.get(fmt, "application/octet-stream")


# ---------------------------------------------------------------------------
# Run generation
# ---------------------------------------------------------------------------
def generate_report(
    report_type: str,
    *,
    report_format: str = ReportFormat.CSV,
    start=None,
    end=None,
    schedule: ReportSchedule | None = None,
    actor=None,
    request=None,
    save: bool = True,
) -> ReportRun:
    """Render ``report_type`` and persist a :class:`ReportRun`."""
    run = ReportRun(
        schedule=schedule,
        report_type=report_type,
        report_format=report_format,
        status=ReportRunStatus.PENDING,
        period_start=start,
        period_end=end,
        created_by=actor,
    )
    if schedule and schedule.recipients:
        run.emailed_to = schedule.recipients
    if save:
        run.save()

    run.started_at = timezone.now()
    try:
        data = selectors.build_report(report_type, start=start, end=end)
        payload = exports.render_report(data, report_format, request=request)
        run.row_count = len(data["rows"])
        run.period_start = data.get("start") or start
        run.period_end = data.get("end") or end
        run.status = ReportRunStatus.SUCCESS
        run.error = ""
    except Exception as exc:  # pragma: no cover - defensive
        run.status = ReportRunStatus.FAILED
        run.error = str(exc)
        run.finished_at = timezone.now()
        if save:
            run.save()
        logger.exception("Report generation failed: %s", report_type)
        return run

    run.finished_at = timezone.now()
    filename = exports.report_filename(data, report_format)
    run.file.save(filename, ContentFile(payload), save=False)
    if save:
        run.save()
    log_action(
        AuditAction.EXPORT,
        instance=run,
        changes={
            "report": report_type,
            "format": report_format,
            "rows": run.row_count,
        },
        user=actor,
        request=request,
    )
    return run


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
def advance_next_run(schedule: ReportSchedule, *, reference=None) -> ReportSchedule:
    """Move a schedule's ``next_run`` forward and stamp ``last_run``."""
    now = reference or timezone.now()
    schedule.last_run = now
    schedule.next_run = schedule.compute_next_run(reference=now)
    schedule.save(update_fields=["last_run", "next_run", "updated_at"])
    return schedule


def run_schedule(
    schedule: ReportSchedule,
    *,
    actor=None,
    request=None,
    send_email: bool = True,
    advance: bool = True,
) -> ReportRun:
    """Generate, persist and (optionally) email a scheduled report."""
    start, end = _period_for(schedule)
    run = generate_report(
        schedule.report_type,
        report_format=schedule.report_format,
        start=start,
        end=end,
        schedule=schedule,
        actor=actor or schedule.created_by,
        request=request,
    )
    if run.status == ReportRunStatus.SUCCESS and send_email:
        run.refresh_from_db()
        send_report_email(run)
    if advance:
        advance_next_run(schedule)
    return run


def due_schedules(*, now=None):
    """Active schedules whose ``next_run`` is due (or unset)."""
    now = now or timezone.now()
    return (
        ReportSchedule.objects.filter(is_active=True)
        .filter(Q(next_run__isnull=True) | Q(next_run__lte=now))
        .order_by("next_run")
    )


def send_scheduled_reports(
    *, now=None, dry_run: bool = False, schedule_id=None
) -> dict:
    """Execute every due schedule (used by the management command).

    Returns ``{"due", "sent", "failed", "skipped", "runs"}``.
    """
    now = now or timezone.now()
    qs = ReportSchedule.objects.filter(is_active=True)
    if schedule_id:
        qs = qs.filter(pk=schedule_id)
    else:
        qs = qs.filter(Q(next_run__isnull=True) | Q(next_run__lte=now))

    stats = {"due": qs.count(), "sent": 0, "failed": 0, "skipped": 0, "runs": []}
    if dry_run:
        return stats

    for schedule in qs:
        try:
            run = run_schedule(schedule, send_email=True)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Scheduled report failed: %s", schedule.pk)
            stats["failed"] += 1
            stats["skipped"] += 1
            continue
        stats["runs"].append(run)
        if run.status == ReportRunStatus.SUCCESS:
            stats["sent"] += 1
        else:
            stats["failed"] += 1
    return stats


def schedule_for_next_run(frequency: str, *, reference=None):
    """Convenience wrapper used when creating a schedule from a form."""
    reference = reference or timezone.now()
    delta = {
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
        "monthly": timedelta(days=30),
    }.get(frequency, timedelta(days=1))
    return reference + delta
