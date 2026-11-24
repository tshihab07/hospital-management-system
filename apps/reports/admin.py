"""Django admin registration for the Reports & Analytics module."""

from __future__ import annotations

from django.contrib import admin

from .models import ReportRun, ReportSchedule


@admin.register(ReportSchedule)
class ReportScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "report_type",
        "frequency",
        "report_format",
        "is_active",
        "next_run",
        "last_run",
    )
    list_filter = ("report_type", "frequency", "report_format", "is_active")
    search_fields = ("name", "recipients")
    readonly_fields = ("created_at", "updated_at", "last_run")


@admin.register(ReportRun)
class ReportRunAdmin(admin.ModelAdmin):
    list_display = (
        "report_type",
        "report_format",
        "status",
        "row_count",
        "period_start",
        "period_end",
        "created_at",
    )
    list_filter = ("report_type", "report_format", "status")
    search_fields = ("schedule__name", "emailed_to")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")
