"""Thin views for the Payroll module (RULES Phase 14).

Views validate input, delegate writes to :mod:`apps.payroll.services`, reads to
:mod:`apps.payroll.selectors`, and render a template or redirect. The payslip
PDF uses WeasyPrint; the register and BEFTN file use :mod:`apps.payroll.exports`.
"""

from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from apps.hr.models import Staff
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from . import exports, selectors, services
from .forms import (
    PayrollRunForm,
    PayrollSettingForm,
    SalaryAdjustmentForm,
    TaxBracketFormSet,
    TaxSlabForm,
)
from .models import PayrollRun, PayrollSetting, Payslip, SalaryAdjustment, TaxSlab

# ---------------------------------------------------------------------------
# Permission codenames
# ---------------------------------------------------------------------------
VIEW_RUN = "payroll.view_payrollrun"
ADD_RUN = "payroll.add_payrollrun"
RUN_PAYROLL = "payroll.run_payroll"
APPROVE_RUN = "payroll.approve_payrollrun"
PAY_RUN = "payroll.pay_payrollrun"
EXPORT_BEFTN = "payroll.export_beftn"
VIEW_PAYSLIP = "payroll.view_payslip"
VIEW_ADJUSTMENT = "payroll.view_salaryadjustment"
ADD_ADJUSTMENT = "payroll.add_salaryadjustment"
CHANGE_ADJUSTMENT = "payroll.change_salaryadjustment"
VIEW_SLAB = "payroll.view_taxslab"
MANAGE_SLAB = "payroll.manage_taxslab"
VIEW_SETTINGS = "payroll.view_payrollsetting"
MANAGE_SETTINGS = "payroll.manage_payrollsettings"
VIEW_STAFF = "hr.view_staff"


def _maybe_export(request, response):
    return response if response is not None else None


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
class RunListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "payroll/run_list.html"
    permission_required = VIEW_RUN

    def get(self, request, *args, **kwargs):
        status = request.GET.get("status", "").strip()
        year_raw = request.GET.get("year", "").strip()
        year = int(year_raw) if year_raw.isdigit() else None
        return self.render_to_response(
            {
                "page_title": _("Payroll"),
                "runs": selectors.run_list(status=status, year=year),
                "status": status,
                "year": year,
                "kpis": selectors.dashboard_kpis(),
                "pending_adjustments": selectors.adjustment_list(status="pending")[:6],
            }
        )


class RunCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = RUN_PAYROLL

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "payroll/run_form.html",
            {"form": PayrollRunForm(), "page_title": _("Run payroll")},
        )

    def post(self, request, *args, **kwargs):
        form = PayrollRunForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                run = services.generate_run(
                    year=data["year"],
                    month=int(data["month"]),
                    payment_date=data.get("payment_date"),
                    payment_method=data["payment_method"],
                    notes=data.get("notes", ""),
                    actor=request.user,
                    request=request,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
                return render(
                    request,
                    "payroll/run_form.html",
                    {"form": form, "page_title": _("Run payroll")},
                )
            messages.success(
                request,
                _("Payroll generated for %(n)s employees.") % {"n": run.employee_count},
            )
            return redirect("payroll:run_detail", pk=run.pk)
        return render(
            request,
            "payroll/run_form.html",
            {"form": form, "page_title": _("Run payroll")},
        )


class RunDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "payroll/run_detail.html"
    permission_required = VIEW_RUN

    def get(self, request, pk, *args, **kwargs):
        run = get_object_or_404(PayrollRun, pk=pk)
        return self.render_to_response(
            {
                "page_title": _("Payroll · %(c)s") % {"c": run.code},
                "run": run,
                "payslips": selectors.run_payslips(run),
                "adjustments": run.adjustments.select_related("staff")[:10],
                "beftn": exports.beftn_summary(run),
                "beftn_validation": exports.validate_beftn(run),
            }
        )


class RunActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = VIEW_RUN

    ACTIONS = {
        "approve": (
            services.approve_run,
            APPROVE_RUN,
            _("Payroll approved and locked."),
        ),
        "pay": (services.mark_run_paid, PAY_RUN, _("Payroll marked as paid.")),
        "cancel": (services.cancel_run, RUN_PAYROLL, _("Payroll run cancelled.")),
    }

    def post(self, request, pk, action, *args, **kwargs):
        run = get_object_or_404(PayrollRun, pk=pk)
        handler = self.ACTIONS.get(action)
        if handler is None:
            messages.error(request, _("Unknown action."))
            return redirect("payroll:run_detail", pk=run.pk)
        func, perm, success = handler
        if not request.user.has_perm(perm):
            messages.error(request, _("You do not have permission for this action."))
            return redirect("payroll:run_detail", pk=run.pk)
        try:
            func(run, actor=request.user, request=request)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, success)
        return redirect("payroll:run_detail", pk=run.pk)


class RunBankFileView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = EXPORT_BEFTN

    def get(self, request, pk, *args, **kwargs):
        run = get_object_or_404(PayrollRun, pk=pk)
        try:
            return exports.beftn_response(run)
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("payroll:run_detail", pk=run.pk)


class RegisterView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "payroll/register.html"
    permission_required = VIEW_RUN

    def get(self, request, pk, *args, **kwargs):
        run = get_object_or_404(PayrollRun, pk=pk)
        export = _maybe_export(request, exports.register_response(request, run))
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Payroll register · %(c)s") % {"c": run.code},
                "run": run,
                "payslips": selectors.run_payslips(run),
                "headers": selectors.REGISTER_HEADERS,
            }
        )


# ---------------------------------------------------------------------------
# Payslips
# ---------------------------------------------------------------------------
class PayslipDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "payroll/payslip_detail.html"
    permission_required = VIEW_PAYSLIP

    def get(self, request, pk, *args, **kwargs):
        slip = get_object_or_404(Payslip.objects.select_related("run", "staff"), pk=pk)
        earnings, deductions = selectors.payslip_lines(slip)
        return self.render_to_response(
            {
                "page_title": _("Payslip · %(n)s") % {"n": slip.name},
                "slip": slip,
                "earnings": earnings,
                "deductions": deductions,
                "pdf_mode": False,
            }
        )


class PayslipPdfView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = VIEW_PAYSLIP

    def get(self, request, pk, *args, **kwargs):
        from django.http import HttpResponse
        from django.template.loader import render_to_string

        from apps.masters.models import HospitalProfile

        slip = get_object_or_404(Payslip.objects.select_related("run", "staff"), pk=pk)
        earnings, deductions = selectors.payslip_lines(slip)
        context = {
            "slip": slip,
            "earnings": earnings,
            "deductions": deductions,
            "hospital": HospitalProfile.load(),
            "pdf_mode": True,
        }
        try:
            from weasyprint import HTML
        except ImportError:  # pragma: no cover
            return redirect("payroll:payslip_detail", pk=slip.pk)
        html = render_to_string("payroll/payslip_pdf.html", context, request=request)
        pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="payslip-{slip.employee_code}-{slip.run.code}.pdf"'
        )
        return response


# ---------------------------------------------------------------------------
# Salary structure
# ---------------------------------------------------------------------------
class SalaryStructureView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "payroll/salary_structure.html"
    permission_required = VIEW_STAFF

    def get(self, request, *args, **kwargs):
        search = request.GET.get("search", "").strip()
        staff_qs = Staff.objects.filter(is_active=True).select_related(
            "department", "designation"
        )
        if search:
            staff_qs = staff_qs.filter(
                Q(name_en__icontains=search)
                | Q(name_bn__icontains=search)
                | Q(employee_code__icontains=search)
            )
        staff_qs = staff_qs.order_by("employee_code")
        from apps.accounting.exports import export_response

        export = export_response(
            request,
            filename="salary-structure",
            title=_("Salary structure"),
            headers=exports.SALARY_STRUCTURE_HEADERS,
            rows=exports.salary_structure_rows(staff_qs),
        )
        if export is not None:
            return export
        return self.render_to_response(
            {
                "page_title": _("Salary structure"),
                "staff_members": staff_qs,
                "search": search,
            }
        )


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------
class AdjustmentListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "payroll/adjustment_list.html"
    permission_required = VIEW_ADJUSTMENT

    def get(self, request, *args, **kwargs):
        status = request.GET.get("status", "").strip()
        return self.render_to_response(
            {
                "page_title": _("Salary adjustments"),
                "adjustments": selectors.adjustment_list(status=status),
                "status": status,
            }
        )


class AdjustmentCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_ADJUSTMENT

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "payroll/adjustment_form.html",
            {"form": SalaryAdjustmentForm(), "page_title": _("New adjustment")},
        )

    def post(self, request, *args, **kwargs):
        form = SalaryAdjustmentForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.create_adjustment(
                staff=data["staff"],
                year=data["year"],
                month=data["month"],
                kind=data["kind"],
                amount=data["amount"],
                reason=data["reason"],
                actor=request.user,
                request=request,
            )
            messages.success(request, _("Salary adjustment recorded."))
            return redirect("payroll:adjustment_list")
        return render(
            request,
            "payroll/adjustment_form.html",
            {"form": form, "page_title": _("New adjustment")},
        )


class AdjustmentActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = CHANGE_ADJUSTMENT

    def post(self, request, pk, action, *args, **kwargs):
        adjustment = get_object_or_404(SalaryAdjustment, pk=pk)
        try:
            if action == "post":
                services.post_adjustment(
                    adjustment, actor=request.user, request=request
                )
                messages.success(request, _("Adjustment journal posted."))
            elif action == "cancel":
                services.cancel_adjustment(
                    adjustment, actor=request.user, request=request
                )
                messages.success(request, _("Adjustment cancelled."))
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("payroll:adjustment_list")


# ---------------------------------------------------------------------------
# Tax slabs
# ---------------------------------------------------------------------------
class TaxSlabListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "payroll/tax_slab_list.html"
    permission_required = VIEW_SLAB

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Income-tax slabs"),
                "slabs": selectors.tax_slabs(),
            }
        )


class TaxSlabCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = MANAGE_SLAB

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "payroll/tax_slab_form.html",
            {
                "form": TaxSlabForm(),
                "bracket_formset": TaxBracketFormSet(),
                "page_title": _("New tax slab"),
            },
        )

    def post(self, request, *args, **kwargs):
        form = TaxSlabForm(request.POST)
        formset = TaxBracketFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            slab = form.save()
            _save_brackets(slab, formset)
            messages.success(request, _("Tax slab created."))
            return redirect("payroll:tax_slab_list")
        return render(
            request,
            "payroll/tax_slab_form.html",
            {
                "form": form,
                "bracket_formset": formset,
                "page_title": _("New tax slab"),
            },
        )


class TaxSlabUpdateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = MANAGE_SLAB

    def get(self, request, pk, *args, **kwargs):
        slab = get_object_or_404(TaxSlab, pk=pk)
        formset = TaxBracketFormSet(
            initial=[
                {
                    "band_amount": b.band_amount,
                    "rate": b.rate,
                    "label": b.label,
                }
                for b in slab.brackets.all()
            ]
        )
        return render(
            request,
            "payroll/tax_slab_form.html",
            {
                "form": TaxSlabForm(instance=slab),
                "bracket_formset": formset,
                "slab": slab,
                "page_title": _("Edit tax slab"),
            },
        )

    def post(self, request, pk, *args, **kwargs):
        slab = get_object_or_404(TaxSlab, pk=pk)
        form = TaxSlabForm(request.POST, instance=slab)
        formset = TaxBracketFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            form.save()
            slab.brackets.all().delete()
            _save_brackets(slab, formset)
            from core.audit import AuditAction, log_action

            log_action(
                AuditAction.UPDATE,
                instance=slab,
                changes=form.changed_data,
                user=request.user,
                request=request,
            )
            messages.success(request, _("Tax slab updated."))
            return redirect("payroll:tax_slab_list")
        return render(
            request,
            "payroll/tax_slab_form.html",
            {
                "form": form,
                "bracket_formset": formset,
                "slab": slab,
                "page_title": _("Edit tax slab"),
            },
        )


def _save_brackets(slab, formset):
    order = 0
    for data in formset.cleaned_data:
        if not data or data.get("DELETE"):
            continue
        band_amount = data.get("band_amount")
        rate = data.get("rate")
        if band_amount is None and rate is None:
            continue
        slab.brackets.create(
            order=order,
            band_amount=band_amount,
            rate=rate or 0,
            label=data.get("label", ""),
        )
        order += 1


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class PayrollSettingView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = VIEW_SETTINGS

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "payroll/settings.html",
            {
                "form": PayrollSettingForm(instance=PayrollSetting.load()),
                "page_title": _("Payroll settings"),
            },
        )

    def post(self, request, *args, **kwargs):
        if not request.user.has_perm(MANAGE_SETTINGS):
            messages.error(request, _("You do not have permission to edit settings."))
            return redirect("payroll:settings")
        form = PayrollSettingForm(request.POST, instance=PayrollSetting.load())
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            from core.audit import AuditAction, log_action

            log_action(
                AuditAction.UPDATE,
                instance=obj,
                changes=form.changed_data,
                user=request.user,
                request=request,
            )
            messages.success(request, _("Payroll settings saved."))
            return redirect("payroll:settings")
        return render(
            request,
            "payroll/settings.html",
            {"form": form, "page_title": _("Payroll settings")},
        )
