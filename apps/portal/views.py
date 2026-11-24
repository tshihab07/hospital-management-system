"""Patient Portal views (RULES Phase 15).

Portal pages are mobile-first. Every authenticated page resolves the patient
from ``request.user`` (never from a URL parameter) so records cannot leak
between patients.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from apps.billing.gateways import GatewayError
from apps.billing.models import Bill, Payment
from apps.ipd.models import DischargeSummary
from apps.lab import selectors as lab_selectors
from apps.lab.models import LabReport
from apps.masters.models import HospitalProfile
from apps.opd.models import Appointment
from core.mixins import IHMSLoginRequiredMixin

from . import selectors, services
from .forms import (
    AppointmentBookingForm,
    AppointmentRescheduleForm,
    MedicalRecordRequestForm,
    NotificationPreferenceForm,
    PortalLoginForm,
    PortalPaymentForm,
    PortalProfileForm,
    PortalRegistrationForm,
    PortalVerificationForm,
)
from .models import PortalAction

VERIFY_SESSION_KEY = "portal_pending_user"


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------
class PortalLoginRequiredMixin(IHMSLoginRequiredMixin):
    """Require a signed-in portal user; send anonymous users to portal login."""

    login_url = reverse_lazy("portal:login")


class PortalPatientMixin(PortalLoginRequiredMixin):
    """Resolve ``self.patient`` from the signed-in user or 403."""

    patient = None

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.patient = selectors.patient_for(request.user)
            if self.patient is None:
                raise PermissionDenied(
                    _("This account is not linked to a patient profile.")
                )
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Registration / verification / auth
# ---------------------------------------------------------------------------
class PortalRegisterView(View):
    template_name = "portal/register.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"form": PortalRegistrationForm(), "page_title": _("Create account")},
        )

    def post(self, request):
        form = PortalRegistrationForm(request.POST, request=request)
        if form.is_valid():
            try:
                user, verification, sandbox_code = services.register_portal_account(
                    uhid=form.cleaned_data["uhid"],
                    phone=form.cleaned_data["phone"],
                    email=form.cleaned_data.get("email", ""),
                    password=form.cleaned_data["password1"],
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return render(
                    request,
                    self.template_name,
                    {"form": form, "page_title": _("Create account")},
                )
            request.session[VERIFY_SESSION_KEY] = user.pk
            if sandbox_code:
                messages.info(
                    request,
                    _("Sandbox mode — your verification code is %(code)s")
                    % {"code": sandbox_code},
                )
            return redirect("portal:verify")
        return render(
            request,
            self.template_name,
            {"form": form, "page_title": _("Create account")},
        )


def _pending_user(request):
    from django.contrib.auth import get_user_model

    user_id = request.session.get(VERIFY_SESSION_KEY)
    if not user_id:
        return None
    return get_user_model().objects.filter(pk=user_id, is_active=False).first()


class PortalVerifyView(View):
    template_name = "portal/verify.html"

    def get(self, request):
        user = _pending_user(request)
        if user is None:
            messages.info(request, _("Start by creating a portal account."))
            return redirect("portal:register")
        return render(
            request,
            self.template_name,
            {
                "form": PortalVerificationForm(),
                "destination": services.latest_pending_verification(user)
                and services.latest_pending_verification(user).destination,
                "page_title": _("Verify your account"),
            },
        )

    def post(self, request):
        user = _pending_user(request)
        if user is None:
            messages.info(request, _("Start by creating a portal account."))
            return redirect("portal:register")
        form = PortalVerificationForm(request.POST)
        verification = services.latest_pending_verification(user)
        if verification is not None and form.is_valid():
            try:
                services.verify_portal_account(
                    verification=verification,
                    code=form.cleaned_data["code"],
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                request.session.pop(VERIFY_SESSION_KEY, None)
                messages.success(request, _("Account verified. Please sign in."))
                return redirect("portal:login")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "destination": verification.destination if verification else "",
                "page_title": _("Verify your account"),
            },
        )


class PortalResendView(View):
    def post(self, request):
        user = _pending_user(request)
        if user is not None:
            try:
                _, sandbox_code = services.resend_portal_verification(
                    user=user, request=request
                )
                if sandbox_code:
                    messages.info(
                        request,
                        _("Sandbox mode — your verification code is %(code)s")
                        % {"code": sandbox_code},
                    )
                else:
                    messages.success(request, _("A new code has been sent."))
            except ValueError as exc:
                messages.error(request, str(exc))
        return redirect("portal:verify")


class PortalLoginView(LoginView):
    template_name = "portal/login.html"
    authentication_form = PortalLoginForm
    redirect_authenticated_user = False

    def get_success_url(self):
        return reverse("portal:dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        patient = selectors.patient_for(self.request.user)
        if patient is not None:
            services.log_portal_action(patient, PortalAction.LOGIN, request=self.request)
        return response


class PortalLogoutView(LogoutView):
    next_page = reverse_lazy("portal:login")

    def post(self, request, *args, **kwargs):
        patient = selectors.patient_for(request.user)
        if patient is not None:
            services.log_portal_action(patient, PortalAction.LOGOUT, request=request)
        return super().post(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class PortalDashboardView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/dashboard.html"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("My health"),
                "patient": self.patient,
                "summary": selectors.dashboard_summary(self.patient),
                "appointments": selectors.upcoming_appointments(self.patient)[:5],
                "lab_reports": selectors.released_lab_reports(self.patient)[:5],
                "bills": selectors.outstanding_bills(self.patient)[:5],
            }
        )


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
class AppointmentListView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/appointments.html"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("My appointments"),
                "patient": self.patient,
                "upcoming": selectors.upcoming_appointments(self.patient),
                "past": selectors.past_appointments(self.patient),
            }
        )


class AppointmentBookView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/appointment_form.html"

    def get(self, request, *args, **kwargs):
        initial = {}
        if request.GET.get("doctor"):
            initial["doctor"] = request.GET["doctor"]
        return self.render_to_response(
            {
                "page_title": _("Book appointment"),
                "form": AppointmentBookingForm(initial=initial),
                "doctors": selectors.available_doctors(),
            }
        )

    def post(self, request, *args, **kwargs):
        form = AppointmentBookingForm(request.POST)
        if form.is_valid():
            try:
                services.book_portal_appointment(
                    patient=self.patient,
                    doctor=form.cleaned_data["doctor"],
                    appt_date=form.cleaned_data["appt_date"],
                    slot=form.cleaned_data.get("slot"),
                    visit_type=form.cleaned_data["visit_type"],
                    actor=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, _("Appointment booked."))
                return redirect("portal:appointments")
        return self.render_to_response(
            {
                "page_title": _("Book appointment"),
                "form": form,
                "doctors": selectors.available_doctors(),
            }
        )


def _own_appointment(patient, pk) -> Appointment:
    appointment = get_object_or_404(
        Appointment.objects.select_related("doctor", "patient"), pk=pk
    )
    if appointment.patient_id != patient.pk:
        raise PermissionDenied(_("You cannot modify that appointment."))
    return appointment


class AppointmentCancelView(PortalPatientMixin, View):
    def post(self, request, pk, *args, **kwargs):
        appointment = _own_appointment(self.patient, pk)
        try:
            services.cancel_portal_appointment(
                appointment=appointment,
                reason=request.POST.get("reason", ""),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Appointment cancelled."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("portal:appointments")


class AppointmentRescheduleView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/appointment_form.html"

    def get(self, request, pk, *args, **kwargs):
        appointment = _own_appointment(self.patient, pk)
        return self.render_to_response(
            {
                "page_title": _("Reschedule appointment"),
                "form": AppointmentRescheduleForm(doctor=appointment.doctor),
                "appointment": appointment,
                "reschedule": True,
                "doctors": selectors.available_doctors(),
            }
        )

    def post(self, request, pk, *args, **kwargs):
        appointment = _own_appointment(self.patient, pk)
        form = AppointmentRescheduleForm(request.POST, doctor=appointment.doctor)
        if form.is_valid():
            try:
                services.reschedule_portal_appointment(
                    appointment=appointment,
                    appt_date=form.cleaned_data["appt_date"],
                    slot=form.cleaned_data.get("slot"),
                    actor=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, _("Appointment rescheduled."))
                return redirect("portal:appointments")
        return self.render_to_response(
            {
                "page_title": _("Reschedule appointment"),
                "form": form,
                "appointment": appointment,
                "reschedule": True,
                "doctors": selectors.available_doctors(),
            }
        )


# ---------------------------------------------------------------------------
# Clinical documents
# ---------------------------------------------------------------------------
class LabReportListView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/lab_reports.html"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Lab reports"),
                "patient": self.patient,
                "reports": selectors.released_lab_reports(self.patient),
                "radiology": selectors.released_radiology(self.patient),
            }
        )


class LabReportPdfView(PortalPatientMixin, View):
    def get(self, request, pk, *args, **kwargs):
        report = get_object_or_404(
            LabReport.objects.select_related("order__patient"), pk=pk
        )
        if report.order.patient_id != self.patient.pk or not report.is_released:
            raise PermissionDenied(_("This report is not available."))
        from weasyprint import HTML

        context = {
            "order": report.order,
            "report": report,
            "results": lab_selectors.results_for_order(order=report.order),
            "hospital": HospitalProfile.load(),
            "pdf_mode": True,
        }
        html = render_to_string("lab/report_pdf.html", context, request=request)
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        services.log_portal_action(
            self.patient, PortalAction.DOWNLOAD, request=request, detail=report.report_no
        )
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="report-{report.report_no}.pdf"'
        return response


class DischargeSummaryListView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/discharge_summaries.html"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Discharge summaries"),
                "patient": self.patient,
                "summaries": selectors.discharge_summaries(self.patient),
            }
        )


def _own_discharge_summary(patient, pk) -> DischargeSummary:
    summary = get_object_or_404(
        DischargeSummary.objects.select_related("admission__patient"), pk=pk
    )
    if summary.admission.patient_id != patient.pk:
        raise PermissionDenied(_("This summary is not available."))
    return summary


class DischargeSummaryDetailView(PortalPatientMixin, View):
    def get(self, request, pk, *args, **kwargs):
        summary = _own_discharge_summary(self.patient, pk)
        services.log_portal_action(
            self.patient,
            PortalAction.VIEW,
            request=request,
            detail=f"discharge:{summary.pk}",
        )
        return render(
            request,
            "ipd/discharge_summary.html",
            {
                "admission": summary.admission,
                "discharge_summary": summary,
                "hospital": HospitalProfile.load(),
                "pdf_mode": False,
            },
        )


class DischargeSummaryPdfView(PortalPatientMixin, View):
    def get(self, request, pk, *args, **kwargs):
        summary = _own_discharge_summary(self.patient, pk)
        from weasyprint import HTML

        context = {
            "admission": summary.admission,
            "discharge_summary": summary,
            "hospital": HospitalProfile.load(),
            "pdf_mode": True,
        }
        html = render_to_string("ipd/discharge_summary.html", context, request=request)
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        services.log_portal_action(
            self.patient,
            PortalAction.DOWNLOAD,
            request=request,
            detail=f"discharge:{summary.pk}",
        )
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="discharge-{summary.admission.ip_number or summary.pk}.pdf"'
        )
        return response


# ---------------------------------------------------------------------------
# Bills & payment
# ---------------------------------------------------------------------------
class BillListView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/bills.html"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("My bills"),
                "patient": self.patient,
                "outstanding": selectors.outstanding_bills(self.patient),
                "history": selectors.patient_bills(self.patient),
                "outstanding_total": selectors.outstanding_total(self.patient),
                "paid_total": selectors.paid_total(self.patient),
            }
        )


def _own_bill(patient, pk) -> Bill:
    bill = get_object_or_404(Bill.objects.select_related("patient"), pk=pk)
    if bill.patient_id != patient.pk:
        raise PermissionDenied(_("You cannot view that bill."))
    return bill


class BillDetailView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/bill_detail.html"

    def get(self, request, pk, *args, **kwargs):
        bill = _own_bill(self.patient, pk)
        return self.render_to_response(
            {
                "page_title": _("Bill %(no)s") % {"no": bill.bill_no},
                "patient": self.patient,
                "bill": bill,
                "items": bill.items.all(),
                "payments": bill.payments.all(),
                "payment_form": PortalPaymentForm(bill=bill),
            }
        )


class BillPayView(PortalPatientMixin, View):
    def post(self, request, pk, *args, **kwargs):
        bill = _own_bill(self.patient, pk)
        form = PortalPaymentForm(request.POST, bill=bill)
        if not form.is_valid():
            messages.error(request, _("Please review the payment details."))
            return redirect("portal:bill_detail", pk=bill.pk)
        try:
            payment = services.initiate_portal_payment(
                bill=bill,
                method=form.cleaned_data["method"],
                amount=form.cleaned_data["amount"],
                patient=self.patient,
                actor=request.user,
                request=request,
            )
        except (ValueError, GatewayError) as exc:
            messages.error(request, str(exc))
            return redirect("portal:bill_detail", pk=bill.pk)
        return redirect("portal:gateway_confirm", txn=payment.txn_ref)


class PortalGatewayConfirmView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/gateway_confirm.html"

    def _payment(self, request, txn) -> Payment:
        payment = get_object_or_404(
            Payment.objects.select_related("bill__patient"), txn_ref=txn
        )
        if payment.bill.patient_id != self.patient.pk:
            raise PermissionDenied(_("You cannot confirm that payment."))
        return payment

    def get(self, request, txn, *args, **kwargs):
        payment = self._payment(request, txn)
        return self.render_to_response(
            {
                "page_title": _("Confirm payment"),
                "payment": payment,
                "bill": payment.bill,
            }
        )

    def post(self, request, txn, *args, **kwargs):
        payment = self._payment(request, txn)
        success = request.POST.get("result", "success") == "success"
        try:
            services.confirm_portal_payment(
                payment=payment,
                success=success,
                gateway_ref=request.POST.get("gateway_ref", ""),
                actor=request.user,
                request=request,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("portal:bill_detail", pk=payment.bill_id)
        if success:
            messages.success(request, _("Payment successful."))
        else:
            messages.info(request, _("Payment cancelled."))
        return redirect("portal:bill_detail", pk=payment.bill_id)


# ---------------------------------------------------------------------------
# Profile / notifications / record requests
# ---------------------------------------------------------------------------
class ProfileView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/profile.html"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("My profile"),
                "patient": self.patient,
                "form": PortalProfileForm(instance=self.patient),
            }
        )

    def post(self, request, *args, **kwargs):
        form = PortalProfileForm(request.POST, instance=self.patient)
        if form.is_valid():
            services.update_portal_profile(
                patient=self.patient,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Profile updated."))
            return redirect("portal:profile")
        return self.render_to_response(
            {"page_title": _("My profile"), "patient": self.patient, "form": form}
        )


class NotificationPreferenceView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/notifications.html"

    def _form(self, request):
        preference = selectors.notification_preference(self.patient)
        return NotificationPreferenceForm(instance=preference)

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {"page_title": _("Notifications"), "form": self._form(request)}
        )

    def post(self, request, *args, **kwargs):
        preference = selectors.notification_preference(self.patient)
        form = NotificationPreferenceForm(request.POST, instance=preference)
        if form.is_valid():
            services.save_notification_preference(
                patient=self.patient, data=form.cleaned_data, request=request
            )
            messages.success(request, _("Notification preferences saved."))
            return redirect("portal:notifications")
        return self.render_to_response(
            {"page_title": _("Notifications"), "form": form}
        )


class RecordRequestListView(PortalPatientMixin, TemplateResponseMixin, View):
    template_name = "portal/record_requests.html"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Medical records"),
                "patient": self.patient,
                "requests": selectors.record_requests(self.patient),
                "form": MedicalRecordRequestForm(),
            }
        )

    def post(self, request, *args, **kwargs):
        form = MedicalRecordRequestForm(request.POST)
        if form.is_valid():
            services.create_record_request(
                patient=self.patient,
                data=form.cleaned_data,
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Your request has been submitted."))
            return redirect("portal:record_requests")
        return self.render_to_response(
            {
                "page_title": _("Medical records"),
                "patient": self.patient,
                "requests": selectors.record_requests(self.patient),
                "form": form,
            }
        )
