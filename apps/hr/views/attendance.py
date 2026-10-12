"""Attendance capture (manual + biometric import)."""

from __future__ import annotations

import csv
import io

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import AttendanceFilterForm, AttendanceForm, AttendanceImportForm
from ..models import Attendance


class AttendanceListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "hr/attendance_list.html"
    context_object_name = "records"
    paginate_by = 40
    permission_required = "hr.view_attendance"

    def get_queryset(self):
        self.filter_form = AttendanceFilterForm(self.request.GET or None)
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        date_from = data.get("date_from") or timezone.localdate().replace(day=1)
        date_to = data.get("date_to") or timezone.localdate()
        self.range = (date_from, date_to)
        return selectors.attendance_list(
            staff=data.get("staff") or None,
            date_from=date_from,
            date_to=date_to,
            source=data.get("source") or "",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_title"] = _("Attendance")
        context["date_from"], context["date_to"] = self.range
        context["summary"] = selectors.attendance_summary(
            date_from=self.range[0], date_to=self.range[1]
        )
        return context


class AttendanceUpsertView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "hr/attendance_form.html"
    permission_required = "hr.change_attendance"

    def _context(self, form):
        return {"page_title": _("Mark Attendance"), "form": form}

    def get(self, request, *args, **kwargs):
        instance = None
        if kwargs.get("pk"):
            instance = get_object_or_404(Attendance, pk=kwargs["pk"])
        form = AttendanceForm(instance=instance)
        return self.render_to_response(self._context(form))

    def post(self, request, *args, **kwargs):
        instance = None
        if kwargs.get("pk"):
            instance = get_object_or_404(Attendance, pk=kwargs["pk"])
        form = AttendanceForm(request.POST, instance=instance)
        if form.is_valid():
            data = form.cleaned_data
            services.upsert_attendance(
                staff=data["staff"],
                att_date=data["att_date"],
                status=data["status"],
                check_in=data.get("check_in"),
                check_out=data.get("check_out"),
                source=data.get("source"),
                device_id=data.get("device_id", ""),
                remarks=data.get("remarks", ""),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Attendance saved."))
            return redirect("hr:attendance_list")
        return self.render_to_response(self._context(form))


class AttendanceImportView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    """Bulk-upsert attendance from a biometric device CSV export."""

    template_name = "hr/attendance_import.html"
    permission_required = "hr.change_attendance"

    def _context(self, form, summary=None):
        return {
            "page_title": _("Import Biometric Attendance"),
            "form": form,
            "summary": summary,
        }

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self._context(AttendanceImportForm()))

    def post(self, request, *args, **kwargs):
        form = AttendanceImportForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            try:
                text = uploaded.read().decode("utf-8-sig")
                rows = list(csv.DictReader(io.StringIO(text)))
            except (UnicodeDecodeError, csv.Error) as exc:
                messages.error(request, _("Could not read CSV: %(err)s") % {"err": exc})
                return self.render_to_response(self._context(form))

            summary = services.import_attendance_rows(
                rows=rows,
                device_id=form.cleaned_data.get("device_id", ""),
                actor=request.user,
                request=request,
            )
            messages.success(
                request,
                _(
                    "Imported — created %(created)s, updated %(updated)s, errors %(errors)s."
                )
                % {
                    "created": summary["created"],
                    "updated": summary["updated"],
                    "errors": len(summary["errors"]),
                },
            )
            return self.render_to_response(
                self._context(AttendanceImportForm(), summary)
            )
        return self.render_to_response(self._context(form))
