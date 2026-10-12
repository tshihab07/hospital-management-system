"""Weekly duty roster screens."""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import RosterGenerateForm


def _parse_week(value: str | None) -> dt.date:
    """Return the Monday of the requested week (defaults to this week)."""
    if value:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            pass
    today = timezone.localdate()
    return today - dt.timedelta(days=today.weekday())


class RosterView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "hr/roster.html"
    permission_required = "hr.view_dutyroster"

    def get(self, request, *args, **kwargs):
        week_start = _parse_week(request.GET.get("week"))
        entries = selectors.roster_week(week_start=week_start)
        context = {
            "page_title": _("Duty Roster"),
            "week_start": week_start,
            "week_end": week_start + dt.timedelta(days=6),
            "prev_week": week_start - dt.timedelta(days=7),
            "next_week": week_start + dt.timedelta(days=7),
            "entries": entries,
            "form": RosterGenerateForm(initial={"week_start": week_start}),
            "unpublished": entries.filter(is_published=False).count(),
        }
        return self.render_to_response(context)


class RosterGenerateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "hr.change_dutyroster"

    def post(self, request, *args, **kwargs):
        form = RosterGenerateForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            week_start = data["week_start"]
            weekdays = sorted(int(day) for day in data["weekdays"])
            dates = [week_start + dt.timedelta(days=day) for day in weekdays]
            services.assign_roster(
                staff=data["staff"],
                shift=data["shift"],
                dates=dates,
                notes=data.get("notes", ""),
                actor=request.user,
                request=request,
            )
            messages.success(
                request,
                _("Roster saved for %(count)s day(s).") % {"count": len(dates)},
            )
            return redirect(f"{request.path}?week={week_start.isoformat()}")
        messages.error(request, _("Could not generate the roster. Check the form."))
        return redirect("hr:roster")


class RosterPublishView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "hr.change_dutyroster"

    def post(self, request, *args, **kwargs):
        week_start = _parse_week(request.POST.get("week"))
        count = services.publish_roster(
            week_start=week_start, actor=request.user, request=request
        )
        messages.success(
            request,
            _("Published %(count)s roster entry(ies).") % {"count": count},
        )
        return redirect(f"/hr/roster/?week={week_start.isoformat()}")
