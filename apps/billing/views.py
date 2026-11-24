"""Thin views for the Billing & Payments module (RULES Phase 12).

Views validate input, delegate writes to :mod:`apps.billing.services` and reads
to :mod:`apps.billing.selectors`, then render a template or redirect.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, View
from django.views.generic.base import TemplateResponseMixin

from apps.accounting import integration as accounting_hooks
from apps.masters.models import HospitalProfile
from apps.patients.models import Patient
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from . import selectors, services
from .forms import (
    AdvanceForm,
    BillForm,
    CreditNoteForm,
    DiscountForm,
    OnlinePaymentForm,
    PackageBillForm,
    PaymentForm,
    RefundForm,
)
from .gateways import GatewayError
from .models import Bill, BillStatus, CreditNote, CreditNoteStatus, Payment, Refund

VIEW_BILL = "billing.view_bill"
ADD_BILL = "billing.add_bill"
CHANGE_BILL = "billing.change_bill"
VIEW_PAYMENT = "billing.view_payment"
ADD_PAYMENT = "billing.add_payment"
VIEW_ADVANCE = "billing.view_advance"
ADD_ADVANCE = "billing.add_advance"
VIEW_REFUND = "billing.view_refund"
ADD_REFUND = "billing.add_refund"
CHANGE_REFUND = "billing.change_refund"
VIEW_PACKAGE = "billing.view_servicepackage"
ADD_PACKAGE = "billing.add_servicepackage"
VIEW_CREDIT = "billing.view_creditnote"
ADD_CREDIT = "billing.add_creditnote"
CHANGE_CREDIT = "billing.change_creditnote"


def _decimal_or_zero(value):
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _get_bill(pk) -> Bill:
    return get_object_or_404(Bill.objects.select_related("patient", "admission"), pk=pk)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "billing/dashboard.html"
    permission_required = VIEW_BILL

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Billing · Dashboard"),
                "kpis": selectors.billing_dashboard(),
                "open_bills": selectors.open_bills()[:10],
                "unbilled": selectors.unbilled_source_counts(),
            }
        )


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------
class BillListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "billing/bill_list.html"
    context_object_name = "bills"
    paginate_by = 25
    permission_required = VIEW_BILL

    def get_queryset(self):
        self.status = self.request.GET.get("status", "")
        self.bill_type = self.request.GET.get("bill_type", "")
        self.search = self.request.GET.get("search", "")
        return selectors.bill_list(
            status=self.status, bill_type=self.bill_type, search=self.search
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Bills")
        context["status"] = self.status
        context["bill_type"] = self.bill_type
        context["search"] = self.search
        context["statuses"] = BillStatus.choices
        return context


class BillCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_BILL

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "billing/bill_form.html",
            {"form": BillForm(), "page_title": _("New bill")},
        )

    def post(self, request, *args, **kwargs):
        form = BillForm(request.POST)
        if form.is_valid():
            bill = services.create_bill(
                form.cleaned_data["patient"],
                bill_type=form.cleaned_data["bill_type"],
                admission=form.cleaned_data.get("admission"),
                vat_rate=form.cleaned_data.get("vat_rate") or 0,
                notes=form.cleaned_data.get("notes", ""),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Bill created."))
            return redirect("billing:bill_detail", pk=bill.pk)
        return render(
            request,
            "billing/bill_form.html",
            {"form": form, "page_title": _("New bill")},
        )


class BillDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "billing/bill_detail.html"
    permission_required = VIEW_BILL

    def get(self, request, *args, **kwargs):
        bill = selectors.bill_detail(_get_bill(kwargs["pk"]))
        return self.render_to_response(
            {
                "page_title": _("Bill · %(no)s") % {"no": bill.bill_no},
                "bill": bill,
                "payment_form": PaymentForm(
                    bill=bill, initial={"amount": bill.due_amount}
                ),
                "online_form": OnlinePaymentForm(bill=bill),
                "discount_form": DiscountForm(initial={"amount": bill.discount}),
                "credit_form": CreditNoteForm(bill=bill),
                "can_change": request.user.has_perm(CHANGE_BILL),
                "can_pay": request.user.has_perm(ADD_PAYMENT),
                "can_pay_online": request.user.has_perm(ADD_PAYMENT),
                "can_credit": request.user.has_perm(ADD_CREDIT),
            }
        )


class BillActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = CHANGE_BILL

    def post(self, request, *args, **kwargs):
        bill = _get_bill(kwargs["pk"])
        action = kwargs["action"]
        try:
            if action == "issue":
                services.issue_bill(bill, actor=request.user, request=request)
                messages.success(request, _("Bill issued."))
            elif action == "vat":
                services.calculate_vat(
                    bill,
                    rate=_decimal_or_zero(request.POST.get("vat_rate")),
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("VAT recalculated."))
            elif action == "post_lab":
                services.post_lab_charges(
                    bill.patient, actor=request.user, request=request
                )
                messages.success(request, _("Laboratory charges posted."))
            elif action == "post_pharmacy":
                services.post_pharmacy_charges(
                    bill.patient, actor=request.user, request=request
                )
                messages.success(request, _("Pharmacy charges posted."))
            elif action == "post_ot":
                services.post_ot_charges(
                    bill.patient, actor=request.user, request=request
                )
                messages.success(request, _("OT charges posted."))
            elif action == "post_ipd":
                if bill.admission_id:
                    services.post_ipd_charges(
                        bill.admission, actor=request.user, request=request
                    )
                    messages.success(request, _("IPD daily charges posted."))
            elif action == "post_opd":
                services.post_opd_charges(
                    bill.patient, actor=request.user, request=request
                )
                messages.success(request, _("OPD consultation charges posted."))
            elif action == "cancel":
                bill.status = BillStatus.CANCELLED
                bill.save(update_fields=["status", "updated_at"])
                accounting_hooks.on_bill_cancelled(
                    bill, actor=request.user, request=request
                )
                messages.success(request, _("Bill cancelled."))
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("billing:bill_detail", pk=bill.pk)


class DiscountActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = CHANGE_BILL

    def post(self, request, *args, **kwargs):
        bill = _get_bill(kwargs["pk"])
        action = kwargs["action"]
        try:
            if action == "apply":
                form = DiscountForm(request.POST)
                if not form.is_valid():
                    messages.error(request, _("Invalid discount."))
                else:
                    services.apply_discount(
                        bill,
                        amount=form.cleaned_data["amount"],
                        reason=form.cleaned_data.get("reason", ""),
                        actor=request.user,
                        request=request,
                    )
                    messages.success(request, _("Discount updated."))
            elif action == "approve":
                services.decide_discount(
                    bill, approved=True, actor=request.user, request=request
                )
                messages.success(request, _("Discount approved."))
            elif action == "reject":
                services.decide_discount(
                    bill, approved=False, actor=request.user, request=request
                )
                messages.success(request, _("Discount rejected."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("billing:bill_detail", pk=bill.pk)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class PaymentListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "billing/payment_list.html"
    context_object_name = "payments"
    paginate_by = 25
    permission_required = VIEW_PAYMENT

    def get_queryset(self):
        self.method = self.request.GET.get("method", "")
        self.search = self.request.GET.get("search", "")
        return selectors.payment_list(method=self.method, search=self.search)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Payments")
        context["method"] = self.method
        context["search"] = self.search
        return context


class PaymentCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_PAYMENT

    def post(self, request, *args, **kwargs):
        bill = _get_bill(kwargs["pk"])
        form = PaymentForm(request.POST, bill=bill)
        if not form.is_valid():
            messages.error(request, _("Please review the payment details."))
            return redirect("billing:bill_detail", pk=bill.pk)
        try:
            payment = services.collect_payment(
                bill,
                method=form.cleaned_data["method"],
                amount=form.cleaned_data["amount"],
                txn_ref=form.cleaned_data.get("txn_ref", ""),
                gateway_ref=form.cleaned_data.get("gateway_ref", ""),
                actor=request.user,
                request=request,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("billing:bill_detail", pk=bill.pk)
        messages.success(request, _("Payment recorded."))
        return redirect("billing:receipt", pk=payment.pk)


class ReceiptView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "billing/receipt.html"
    permission_required = VIEW_PAYMENT

    def get(self, request, *args, **kwargs):
        payment = get_object_or_404(
            Payment.objects.select_related("bill__patient", "receipt", "received_by"),
            pk=kwargs["pk"],
        )
        return self.render_to_response(
            {
                "page_title": _("Money receipt · %(no)s")
                % {"no": getattr(payment.receipt, "receipt_no", "")},
                "payment": payment,
                "receipt": getattr(payment, "receipt", None),
                "bill": payment.bill,
                "hospital": HospitalProfile.load(),
                "pdf_mode": False,
            }
        )


class ReceiptPdfView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = VIEW_PAYMENT

    def get(self, request, *args, **kwargs):
        from django.http import HttpResponse
        from django.template.loader import render_to_string

        payment = get_object_or_404(
            Payment.objects.select_related("bill__patient", "receipt", "received_by"),
            pk=kwargs["pk"],
        )
        try:
            from weasyprint import HTML
        except ImportError:  # pragma: no cover
            return redirect("billing:receipt", pk=payment.pk)
        html = render_to_string(
            "billing/receipt.html",
            {
                "payment": payment,
                "receipt": getattr(payment, "receipt", None),
                "bill": payment.bill,
                "hospital": HospitalProfile.load(),
                "pdf_mode": True,
            },
            request=request,
        )
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="receipt-{payment.pk}.pdf"'
        return response


# ---------------------------------------------------------------------------
# Advances
# ---------------------------------------------------------------------------
class AdvanceListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "billing/advance_list.html"
    context_object_name = "advances"
    paginate_by = 25
    permission_required = VIEW_ADVANCE

    def get_queryset(self):
        return selectors.advances()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Advances")
        return context


class AdvanceCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_ADVANCE

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "billing/advance_form.html",
            {"form": AdvanceForm(), "page_title": _("New advance")},
        )

    def post(self, request, *args, **kwargs):
        form = AdvanceForm(request.POST)
        if form.is_valid():
            try:
                services.add_advance(
                    form.cleaned_data["patient"],
                    amount=form.cleaned_data["amount"],
                    method=form.cleaned_data["method"],
                    admission=form.cleaned_data.get("admission"),
                    txn_ref=form.cleaned_data.get("txn_ref", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Advance recorded."))
                return redirect("billing:advance_list")
            except ValueError as exc:
                messages.error(request, str(exc))
        return render(
            request,
            "billing/advance_form.html",
            {"form": form, "page_title": _("New advance")},
        )


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
class RefundListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "billing/refund_list.html"
    context_object_name = "refunds"
    paginate_by = 25
    permission_required = VIEW_REFUND

    def get_queryset(self):
        self.status = self.request.GET.get("status", "")
        return selectors.refund_list(status=self.status)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Refunds")
        context["status"] = self.status
        return context


class RefundCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_REFUND

    def _bill(self, request):
        pk = request.POST.get("bill") or request.GET.get("bill")
        return _get_bill(pk) if pk else None

    def get(self, request, *args, **kwargs):
        bill = self._bill(request)
        return render(
            request,
            "billing/refund_form.html",
            {
                "form": RefundForm(bill=bill),
                "bill": bill,
                "page_title": _("New refund"),
            },
        )

    def post(self, request, *args, **kwargs):
        bill = self._bill(request)
        form = RefundForm(request.POST, bill=bill)
        if form.is_valid():
            try:
                services.create_refund(
                    amount=form.cleaned_data["amount"],
                    reason=form.cleaned_data["reason"],
                    method=form.cleaned_data["method"],
                    bill=form.cleaned_data.get("bill"),
                    payment=form.cleaned_data.get("payment"),
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Refund requested."))
                return redirect("billing:refund_list")
            except ValueError as exc:
                messages.error(request, str(exc))
        return render(
            request,
            "billing/refund_form.html",
            {"form": form, "bill": bill, "page_title": _("New refund")},
        )


class RefundActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = CHANGE_REFUND

    def post(self, request, *args, **kwargs):
        refund = get_object_or_404(
            Refund.objects.select_related("bill"), pk=kwargs["pk"]
        )
        action = kwargs["action"]
        try:
            if action == "approve":
                services.decide_refund(
                    refund, approved=True, actor=request.user, request=request
                )
                messages.success(request, _("Refund approved."))
            elif action == "reject":
                services.decide_refund(
                    refund, approved=False, actor=request.user, request=request
                )
                messages.success(request, _("Refund rejected."))
            elif action == "process":
                services.process_refund(
                    refund,
                    txn_ref=request.POST.get("txn_ref", ""),
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Refund processed."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("billing:refund_list")


# ---------------------------------------------------------------------------
# Patient ledger
# ---------------------------------------------------------------------------
class LedgerView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "billing/ledger.html"
    permission_required = VIEW_BILL

    def get(self, request, *args, **kwargs):
        patient = None
        ledger = None
        pk = kwargs.get("pk") or request.GET.get("patient")
        if pk:
            patient = get_object_or_404(Patient, pk=pk)
            ledger = selectors.patient_ledger(patient)
        return self.render_to_response(
            {
                "page_title": _("Patient ledger"),
                "patient": patient,
                "ledger": ledger,
                "patients": Patient.objects.order_by("full_name_en"),
            }
        )


# ---------------------------------------------------------------------------
# Online payment gateway
# ---------------------------------------------------------------------------
class OnlinePaymentView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Initiate a gateway payment and bounce to the sandbox checkout."""

    permission_required = ADD_PAYMENT

    def post(self, request, *args, **kwargs):
        bill = _get_bill(kwargs["pk"])
        form = OnlinePaymentForm(request.POST, bill=bill)
        if not form.is_valid():
            messages.error(request, _("Please review the online payment details."))
            return redirect("billing:bill_detail", pk=bill.pk)
        try:
            payment = services.initiate_online_payment(
                bill,
                method=form.cleaned_data["method"],
                amount=form.cleaned_data["amount"],
                actor=request.user,
                request=request,
            )
        except (ValueError, GatewayError) as exc:
            messages.error(request, str(exc))
            return redirect("billing:bill_detail", pk=bill.pk)
        return redirect("billing:gateway_confirm", txn=payment.txn_ref)


class GatewayConfirmView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    """Sandbox return URL: confirm or cancel a pending online payment."""

    template_name = "billing/gateway_confirm.html"
    permission_required = ADD_PAYMENT

    def get(self, request, *args, **kwargs):
        payment = get_object_or_404(
            Payment.objects.select_related("bill__patient"), txn_ref=kwargs["txn"]
        )
        return self.render_to_response(
            {
                "page_title": _("Gateway checkout"),
                "payment": payment,
                "bill": payment.bill,
            }
        )

    def post(self, request, *args, **kwargs):
        payment = get_object_or_404(
            Payment.objects.select_related("bill"), txn_ref=kwargs["txn"]
        )
        success = request.POST.get("result", "success") == "success"
        try:
            services.confirm_online_payment(
                payment,
                success=success,
                gateway_ref=request.POST.get("gateway_ref", ""),
                actor=request.user,
                request=request,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("billing:bill_detail", pk=payment.bill_id)
        if success:
            messages.success(request, _("Online payment confirmed."))
            return redirect("billing:receipt", pk=payment.pk)
        messages.info(request, _("Online payment cancelled."))
        return redirect("billing:bill_detail", pk=payment.bill_id)


# ---------------------------------------------------------------------------
# Credit notes
# ---------------------------------------------------------------------------
class CreditNoteListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "billing/credit_note_list.html"
    context_object_name = "credit_notes"
    paginate_by = 25
    permission_required = VIEW_CREDIT

    def get_queryset(self):
        self.status = self.request.GET.get("status", "")
        self.search = self.request.GET.get("search", "")
        return selectors.credit_note_list(status=self.status, search=self.search)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Credit notes")
        context["status"] = self.status
        context["search"] = self.search
        context["statuses"] = CreditNoteStatus.choices
        return context


class CreditNoteCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_CREDIT

    def post(self, request, *args, **kwargs):
        bill = _get_bill(kwargs["pk"])
        form = CreditNoteForm(request.POST, bill=bill)
        if form.is_valid():
            try:
                services.create_credit_note(
                    bill,
                    amount=form.cleaned_data["amount"],
                    reason=form.cleaned_data["reason"],
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Credit note created."))
            except ValueError as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, _("Please review the credit note details."))
        return redirect("billing:bill_detail", pk=bill.pk)


class CreditNoteActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = CHANGE_CREDIT

    def post(self, request, *args, **kwargs):
        note = get_object_or_404(CreditNote.objects.select_related("bill"), pk=kwargs["pk"])
        action = kwargs["action"]
        try:
            if action == "issue":
                services.issue_credit_note(note, actor=request.user, request=request)
                messages.success(request, _("Credit note issued."))
            elif action == "void":
                services.void_credit_note(note, actor=request.user, request=request)
                messages.success(request, _("Credit note voided."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("billing:credit_note_list")


# ---------------------------------------------------------------------------
# Service packages
# ---------------------------------------------------------------------------
class PackageListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, ListView):
    template_name = "billing/package_list.html"
    context_object_name = "packages"
    permission_required = VIEW_PACKAGE

    def get_queryset(self):
        return selectors.package_list()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Service packages")
        return context


class PackageBillCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Generate a PACKAGE invoice from a bundled rate card."""

    permission_required = ADD_BILL

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "billing/package_bill_form.html",
            {"form": PackageBillForm(), "page_title": _("Package billing")},
        )

    def post(self, request, *args, **kwargs):
        form = PackageBillForm(request.POST)
        if form.is_valid():
            bill = services.create_package_bill(
                form.cleaned_data["patient"],
                form.cleaned_data["package"],
                vat_rate=form.cleaned_data.get("vat_rate"),
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Package bill generated."))
            return redirect("billing:bill_detail", pk=bill.pk)
        return render(
            request,
            "billing/package_bill_form.html",
            {"form": form, "page_title": _("Package billing")},
        )


# ---------------------------------------------------------------------------
# Daily collection report
# ---------------------------------------------------------------------------
class DailyCollectionView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "billing/daily_collection.html"
    permission_required = VIEW_PAYMENT

    def _day(self, request):
        raw = request.GET.get("day")
        if raw:
            try:
                return timezone.datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                pass
        return timezone.localdate()

    def get(self, request, *args, **kwargs):
        day = self._day(request)
        method = request.GET.get("method", "")
        report = selectors.daily_collection(day=day, method=method)
        if request.GET.get("export") == "csv":
            return self._csv(report)
        return self.render_to_response(
            {
                "page_title": _("Daily collection"),
                "report": report,
                "day": day,
                "method": method,
                "methods": Payment._meta.get_field("method").choices,
            }
        )

    def _csv(self, report):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="collection-{report["day"]}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([_("Method"), _("Count"), _("Total")])
        for row in report["rows"]:
            writer.writerow([row["method"], row["count"], row["total"]])
        writer.writerow([_("Grand total"), report["count"], report["grand_total"]])
        return response
