"""Thin views for the Operation Theatre module (RULES Phase 9).

Views validate input, delegate all writes to :mod:`apps.ot.services` and all
reads to :mod:`apps.ot.selectors`, then render a template or redirect.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from . import selectors, services
from .forms import (AnesthesiaForm, CancelSurgeryForm, ConsumableForm,
                    ImplantForm, IntraOpNoteForm, OTRoomForm, PostOpNoteForm,
                    PreOpChecklistForm, RoomFilterForm, SurgeryFilterForm,
                    SurgeryForm, SurgeryRescheduleForm, TeamMemberForm,
                    UtilizationFilterForm)
from .models import OTRoom, Surgery


def _surgery(pk) -> Surgery:
    return get_object_or_404(
        Surgery.objects.select_related("patient", "surgeon", "ot_room"), pk=pk
    )


def _parse_date(value, default):
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Surgery listing / CRUD
# ---------------------------------------------------------------------------
class SurgeryListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "ot/surgery_list.html"
    permission_required = "ot.view_surgery"

    def get(self, request, *args, **kwargs):
        data = request.GET
        room_id = data.get("room") or None
        surgeries = selectors.surgery_list(
            q=data.get("q", ""),
            status=data.get("status", ""),
            priority=data.get("priority", ""),
            room=room_id,
            date_from=_parse_date(data.get("date_from"), None),
            date_to=_parse_date(data.get("date_to"), None),
        )
        return self.render_to_response(
            {
                "page_title": _("Operation Theatre · Surgeries"),
                "surgeries": surgeries,
                "today": selectors.todays_surgeries(),
                "filters": SurgeryFilterForm(initial=data),
            }
        )


class SurgeryCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.add_surgery"

    def get(self, request, *args, **kwargs):
        from django.shortcuts import render

        initial = {"scheduled_date": timezone.localdate()}
        return render(
            request,
            "ot/surgery_form.html",
            {"page_title": _("Schedule surgery"), "form": SurgeryForm(initial=initial)},
        )

    def post(self, request, *args, **kwargs):
        from django.shortcuts import render

        form = SurgeryForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                surgery = services.schedule_surgery(
                    patient=data["patient"],
                    surgeon=data["surgeon"],
                    ot_room=data["ot_room"],
                    scheduled_date=data["scheduled_date"],
                    start_time=data["start_time"],
                    end_time=data["end_time"],
                    procedure_name=data["procedure_name"],
                    priority=data["priority"],
                    admission=data.get("admission"),
                    diagnosis=data.get("diagnosis", ""),
                    notes=data.get("notes", ""),
                    actor=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request, _("Surgery %(no)s scheduled.") % {"no": surgery.surgery_no}
                )
                return redirect("ot:surgery_detail", pk=surgery.pk)
        return render(
            request,
            "ot/surgery_form.html",
            {"page_title": _("Schedule surgery"), "form": form},
        )


class SurgeryDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "ot/surgery_detail.html"
    permission_required = "ot.view_surgery"

    def get(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        return self.render_to_response(
            {
                "page_title": surgery.surgery_no,
                "surgery": surgery,
                "team": surgery.team.select_related("doctor", "staff"),
                "implants": surgery.implants.all(),
                "consumables": surgery.consumables.all(),
                "checklist": getattr(surgery, "preop_checklist", None),
                "anesthesia": getattr(surgery, "anesthesia", None),
                "intraop": getattr(surgery, "intraop_note", None),
                "postop": getattr(surgery, "postop_note", None),
                "team_form": TeamMemberForm(),
                "implant_form": ImplantForm(),
                "consumable_form": ConsumableForm(),
            }
        )


class SurgeryRescheduleView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.change_surgery"

    def get(self, request, *args, **kwargs):
        from django.shortcuts import render

        surgery = _surgery(kwargs["pk"])
        form = SurgeryRescheduleForm(
            initial={
                "scheduled_date": surgery.scheduled_date,
                "start_time": surgery.start_time,
                "end_time": surgery.end_time,
                "ot_room": surgery.ot_room,
            }
        )
        return render(
            request,
            "ot/surgery_reschedule.html",
            {"page_title": _("Reschedule surgery"), "surgery": surgery, "form": form},
        )

    def post(self, request, *args, **kwargs):
        from django.shortcuts import render

        surgery = _surgery(kwargs["pk"])
        form = SurgeryRescheduleForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                services.reschedule_surgery(
                    surgery=surgery,
                    scheduled_date=data["scheduled_date"],
                    start_time=data["start_time"],
                    end_time=data["end_time"],
                    ot_room=data["ot_room"],
                    actor=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, _("Surgery rescheduled."))
                return redirect("ot:surgery_detail", pk=surgery.pk)
        return render(
            request,
            "ot/surgery_reschedule.html",
            {"page_title": _("Reschedule surgery"), "surgery": surgery, "form": form},
        )


class SurgeryCancelView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.cancel_surgery"

    def post(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        form = CancelSurgeryForm(request.POST)
        reason = form.cleaned_data["reason"] if form.is_valid() else ""
        services.cancel_surgery(
            surgery=surgery, reason=reason, actor=request.user, request=request
        )
        messages.success(request, _("Surgery cancelled."))
        return redirect("ot:surgery_detail", pk=surgery.pk)


class SurgeryActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Start / complete / confirm a surgery."""

    permission_required = "ot.change_surgery"

    def post(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        action = kwargs["action"]
        try:
            if action == "start":
                services.start_surgery(
                    surgery=surgery, actor=request.user, request=request
                )
                messages.success(request, _("Surgery started."))
            elif action == "complete":
                services.complete_surgery(
                    surgery=surgery, actor=request.user, request=request
                )
                messages.success(request, _("Surgery completed."))
            elif action == "confirm":
                services.set_surgery_status(
                    surgery=surgery,
                    status="confirmed",
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Surgery confirmed."))
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("ot:surgery_detail", pk=surgery.pk)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
class OTCalendarView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "ot/calendar.html"
    permission_required = "ot.view_surgery"

    def get(self, request, *args, **kwargs):
        week_start = _parse_date(request.GET.get("week_start"), None)
        calendar = selectors.week_calendar(week_start=week_start)
        return self.render_to_response(
            {
                "page_title": _("OT calendar"),
                "calendar": calendar,
                "prev_week": (calendar["week_start"] - timedelta(days=7)).isoformat(),
                "next_week": (calendar["week_start"] + timedelta(days=7)).isoformat(),
                "day_start": 8,
                "day_end": 20,
            }
        )


# ---------------------------------------------------------------------------
# Checklist / notes
# ---------------------------------------------------------------------------
class PreOpChecklistView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.change_surgery"

    def get(self, request, *args, **kwargs):
        from django.shortcuts import render

        surgery = _surgery(kwargs["pk"])
        checklist = getattr(surgery, "preop_checklist", None)
        return render(
            request,
            "ot/checklist_form.html",
            {
                "page_title": _("Pre-op checklist"),
                "surgery": surgery,
                "form": PreOpChecklistForm(instance=checklist),
            },
        )

    def post(self, request, *args, **kwargs):
        from django.shortcuts import render

        surgery = _surgery(kwargs["pk"])
        checklist = getattr(surgery, "preop_checklist", None)
        form = PreOpChecklistForm(request.POST, instance=checklist)
        if form.is_valid():
            services.save_preop_checklist(
                surgery=surgery,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Pre-op checklist saved."))
            return redirect("ot:surgery_detail", pk=surgery.pk)
        return render(
            request,
            "ot/checklist_form.html",
            {"page_title": _("Pre-op checklist"), "surgery": surgery, "form": form},
        )


class AnesthesiaView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.change_surgery"

    def get(self, request, *args, **kwargs):
        from django.shortcuts import render

        surgery = _surgery(kwargs["pk"])
        return render(
            request,
            "ot/anesthesia_form.html",
            {
                "page_title": _("Anaesthesia record"),
                "surgery": surgery,
                "form": AnesthesiaForm(instance=getattr(surgery, "anesthesia", None)),
            },
        )

    def post(self, request, *args, **kwargs):
        from django.shortcuts import render

        surgery = _surgery(kwargs["pk"])
        form = AnesthesiaForm(request.POST)
        if form.is_valid():
            services.record_anesthesia(
                surgery=surgery,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Anaesthesia record saved."))
            return redirect("ot:surgery_detail", pk=surgery.pk)
        return render(
            request,
            "ot/anesthesia_form.html",
            {"page_title": _("Anaesthesia record"), "surgery": surgery, "form": form},
        )


class IntraOpNoteView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.change_surgery"

    def _render(self, request, surgery, form):
        from django.shortcuts import render

        return render(
            request,
            "ot/intraop_form.html",
            {"page_title": _("Intra-op note"), "surgery": surgery, "form": form},
        )

    def get(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        return self._render(
            request,
            surgery,
            IntraOpNoteForm(instance=getattr(surgery, "intraop_note", None)),
        )

    def post(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        form = IntraOpNoteForm(request.POST)
        if form.is_valid():
            services.record_intraop_note(
                surgery=surgery,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Intra-op note saved."))
            return redirect("ot:surgery_detail", pk=surgery.pk)
        return self._render(request, surgery, form)


class PostOpNoteView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.change_surgery"

    def _render(self, request, surgery, form):
        from django.shortcuts import render

        return render(
            request,
            "ot/postop_form.html",
            {"page_title": _("Post-op note"), "surgery": surgery, "form": form},
        )

    def get(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        return self._render(
            request,
            surgery,
            PostOpNoteForm(instance=getattr(surgery, "postop_note", None)),
        )

    def post(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        form = PostOpNoteForm(request.POST)
        if form.is_valid():
            services.record_postop_note(
                surgery=surgery,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Post-op note saved."))
            return redirect("ot:surgery_detail", pk=surgery.pk)
        return self._render(request, surgery, form)


# ---------------------------------------------------------------------------
# Team / implants / consumables
# ---------------------------------------------------------------------------
class TeamCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.change_surgery"

    def post(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        form = TeamMemberForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.add_team_member(
                surgery=surgery,
                role=data["role"],
                doctor=data.get("doctor"),
                staff=data.get("staff"),
                name=data.get("name", ""),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Team member added."))
        else:
            messages.error(request, _("Could not add team member."))
        return redirect("ot:surgery_detail", pk=surgery.pk)


class ImplantCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.add_implant"

    def post(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        form = ImplantForm(request.POST)
        if form.is_valid():
            services.record_implant(
                surgery=surgery,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Implant recorded and tracked to patient."))
        else:
            messages.error(request, _("Could not record implant."))
        return redirect("ot:surgery_detail", pk=surgery.pk)


class ConsumableView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.add_surgeryconsumable"

    def post(self, request, *args, **kwargs):
        surgery = _surgery(kwargs["pk"])
        form = ConsumableForm(request.POST)
        if form.is_valid():
            services.record_consumable(
                surgery=surgery,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Consumable captured."))
        else:
            messages.error(request, _("Could not capture consumable."))
        return redirect("ot:surgery_detail", pk=surgery.pk)


# ---------------------------------------------------------------------------
# Rooms / utilization
# ---------------------------------------------------------------------------
class RoomListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "ot/room_list.html"
    permission_required = "ot.view_otroom"

    def get(self, request, *args, **kwargs):
        otr = request.GET.get("room_type", "")
        status = request.GET.get("status", "")
        rooms = OTRoom.objects.all().order_by("name")
        if otr:
            rooms = rooms.filter(room_type=otr)
        if status:
            rooms = rooms.filter(status=status)
        return self.render_to_response(
            {
                "page_title": _("OT rooms"),
                "rooms": rooms,
                "filters": RoomFilterForm(initial=request.GET),
            }
        )


class RoomCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "ot.add_otroom"

    def get(self, request, *args, **kwargs):
        from django.shortcuts import render

        return render(
            request,
            "ot/room_form.html",
            {"page_title": _("Add OT room"), "form": OTRoomForm()},
        )

    def post(self, request, *args, **kwargs):
        from django.shortcuts import render

        form = OTRoomForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("OT room created."))
            return redirect("ot:room_list")
        return render(
            request,
            "ot/room_form.html",
            {"page_title": _("Add OT room"), "form": form},
        )


class UtilizationView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "ot/utilization.html"
    permission_required = "ot.view_surgery"

    def get(self, request, *args, **kwargs):
        today = timezone.localdate()
        start = _parse_date(request.GET.get("start"), today - timedelta(days=29))
        end = _parse_date(request.GET.get("end"), today)
        report = selectors.utilization_report(start=start, end=end)
        return self.render_to_response(
            {
                "page_title": _("OT utilisation"),
                "report": report,
                "filters": UtilizationFilterForm(initial={"start": start, "end": end}),
            }
        )
