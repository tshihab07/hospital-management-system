"""Appointment booking, list, detail, queue and lifecycle (RULES Phase 4)."""

from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, View
from django.views.generic.base import TemplateResponseMixin

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import selectors, services
from ..forms import (AppointmentBookingForm, AppointmentFilterForm,
                     RescheduleForm, SlotPreviewForm)
from ..models import Appointment


def _block_data(doctor, appt_date):
    """Return (blocks, radio_choices) for a doctor/date."""
    blocks = selectors.available_blocks(doctor, appt_date)
    choices = [
        (
            slot.pk,
            _("%(label)s · %(left)s seat(s) left")
            % {"label": slot.label, "left": left},
        )
        for slot, left in blocks
    ]
    return blocks, choices


class AppointmentListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView
):
    template_name = "opd/appointment_list.html"
    context_object_name = "appointments"
    paginate_by = 30
    permission_required = "opd.view_appointment"

    def get_queryset(self):
        self.filter_form = AppointmentFilterForm(self.request.GET or None)
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        self.appt_date = data.get("appt_date") or timezone.localdate()
        return selectors.appointment_list(
            appt_date=self.appt_date,
            doctor=data.get("doctor") or None,
            status=data.get("status") or "",
            search=data.get("q") or "",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_title"] = _("Appointments")
        context["appt_date"] = self.appt_date
        return context


class AppointmentBookingView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "opd/appointment_book.html"
    permission_required = "opd.add_appointment"

    def _context(self, booking, preview_form, blocks=None):
        return {
            "page_title": _("Book Appointment"),
            "form": booking,
            "preview_form": preview_form,
            "blocks": blocks or [],
        }

    def get(self, request, *args, **kwargs):
        booking = AppointmentBookingForm()
        preview_form = SlotPreviewForm(request.GET or None)
        blocks = []
        if request.GET and preview_form.is_valid():
            doctor = preview_form.cleaned_data.get("doctor")
            appt_date = preview_form.cleaned_data.get("appt_date")
            if doctor and appt_date:
                booking.initial["doctor"] = doctor
                booking.initial["appt_date"] = appt_date
                blocks, choices = _block_data(doctor, appt_date)
                booking.fields["slot"].choices = choices
        return self.render_to_response(self._context(booking, preview_form, blocks))

    def post(self, request, *args, **kwargs):
        booking = AppointmentBookingForm(request.POST)
        preview_form = SlotPreviewForm()
        if booking.is_valid():
            data = booking.cleaned_data
            doctor, appt_date, slot_id = (
                data["doctor"],
                data["appt_date"],
                data.get("slot"),
            )
            blocks, choices = _block_data(doctor, appt_date)
            booking.fields["slot"].choices = choices
            valid_slot_ids = {pk for pk, _label in choices}
            if not slot_id:
                booking.add_error("slot", _("Please choose a time block."))
            elif slot_id not in valid_slot_ids:
                booking.add_error("slot", _("That time block is no longer available."))
            else:
                from ..models import AvailabilitySlot

                slot = get_object_or_404(AvailabilitySlot, pk=slot_id)
                try:
                    appointment = services.book_appointment(
                        patient=data["patient"],
                        doctor=doctor,
                        appt_date=appt_date,
                        slot=slot,
                        visit_type=data["visit_type"],
                        notes=data.get("notes", ""),
                        actor=request.user,
                        request=request,
                    )
                except ValueError as exc:
                    booking.add_error(None, str(exc))
                else:
                    messages.success(
                        request,
                        _("Appointment booked. Token #%(token)s.")
                        % {"token": appointment.token_no},
                    )
                    return redirect("opd:appointment_detail", pk=appointment.pk)
            messages.error(request, _("Please review the highlighted fields."))
            return self.render_to_response(self._context(booking, preview_form, blocks))
        return self.render_to_response(self._context(booking, preview_form))


class AppointmentDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, DetailView
):
    model = Appointment
    template_name = "opd/appointment_detail.html"
    context_object_name = "appointment"
    permission_required = "opd.view_appointment"

    def get_queryset(self):
        return Appointment.objects.select_related(
            "doctor", "patient", "slot", "created_by"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Appointment #%(token)s") % {
            "token": self.object.token_no
        }
        context["priority"] = self.object
        return context


class AppointmentCancelView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "opd.change_appointment"

    def post(self, request, *args, **kwargs):
        appointment = get_object_or_404(Appointment, pk=kwargs["pk"])
        try:
            services.cancel_appointment(
                instance=appointment,
                reason=request.POST.get("reason", ""),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Appointment cancelled."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("opd:appointment_detail", pk=appointment.pk)


class AppointmentRescheduleView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "opd/appointment_reschedule.html"
    permission_required = "opd.change_appointment"

    def _context(self, appointment, form, blocks=None):
        return {
            "page_title": _("Reschedule Appointment"),
            "appointment": appointment,
            "form": form,
            "blocks": blocks or [],
        }

    def get(self, request, *args, **kwargs):
        appointment = get_object_or_404(Appointment, pk=kwargs["pk"])
        form = RescheduleForm(request.GET or None)
        if request.GET and form.is_valid() and form.cleaned_data.get("appt_date"):
            appt_date = form.cleaned_data["appt_date"]
            blocks, choices = _block_data(appointment.doctor, appt_date)
            form.fields["slot"].choices = choices
        return self.render_to_response(self._context(appointment, form))

    def post(self, request, *args, **kwargs):
        appointment = get_object_or_404(Appointment, pk=kwargs["pk"])
        form = RescheduleForm(request.POST)
        if form.is_valid():
            appt_date = form.cleaned_data["appt_date"]
            slot_id = form.cleaned_data.get("slot")
            blocks, choices = _block_data(appointment.doctor, appt_date)
            form.fields["slot"].choices = choices
            if not slot_id:
                form.add_error("slot", _("Please choose a time block."))
            else:
                from ..models import AvailabilitySlot

                slot = get_object_or_404(AvailabilitySlot, pk=slot_id)
                try:
                    created = services.reschedule_appointment(
                        instance=appointment,
                        appt_date=appt_date,
                        slot=slot,
                        actor=request.user,
                        request=request,
                    )
                except ValueError as exc:
                    form.add_error(None, str(exc))
                else:
                    messages.success(
                        request,
                        _("Appointment rescheduled. New token #%(token)s.")
                        % {"token": created.token_no},
                    )
                    return redirect("opd:appointment_detail", pk=created.pk)
            return self.render_to_response(self._context(appointment, form, blocks))
        return self.render_to_response(self._context(appointment, form))


class AppointmentStatusView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "opd.change_appointment"

    def post(self, request, *args, **kwargs):
        appointment = get_object_or_404(Appointment, pk=kwargs["pk"])
        status = request.POST.get("status", "")
        try:
            services.set_status(
                instance=appointment,
                status=status,
                actor=request.user,
                request=request,
            )
            messages.success(
                request,
                _("Status changed to “%(status)s”.")
                % {"status": appointment.get_status_display()},
            )
        except (ValueError, KeyError) as exc:
            messages.error(request, str(exc))
        next_url = request.POST.get("next")
        return redirect(next_url or reverse("opd:queue"))


class QueueView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "opd/queue.html"
    permission_required = "opd.view_appointment"

    def _context(self, request):
        from ..models import Doctor

        doctor_id = request.GET.get("doctor") or ""
        appt_date_str = request.GET.get("date") or ""
        try:
            appt_date = (
                date.fromisoformat(appt_date_str)
                if appt_date_str
                else timezone.localdate()
            )
        except ValueError:
            appt_date = timezone.localdate()
        doctor = Doctor.objects.filter(pk=doctor_id).first() if doctor_id else None
        return {
            "page_title": _("OPD Queue"),
            "appointments": selectors.queue_for(doctor, appt_date=appt_date),
            "doctors": Doctor.objects.filter(is_active=True).order_by("name_en"),
            "selected_doctor": doctor,
            "appt_date": appt_date,
            "summary": selectors.today_summary(appt_date=appt_date),
        }

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self._context(request))
