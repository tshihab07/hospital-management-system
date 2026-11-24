"""Thin views for the Pharmacy & Inventory module (RULES Phase 11).

Views validate input, delegate writes to :mod:`apps.pharmacy.services`, reads to
:mod:`apps.pharmacy.selectors`, then render a template or redirect.
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.base import TemplateResponseMixin

from apps.emr.models import Prescription
from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from . import selectors, services
from .forms import (DispenseForm, GRNForm, PurchaseOrderForm, RequisitionForm,
                    ReturnToVendorForm, StockAdjustForm, StockBatchForm,
                    TransferForm, VendorForm)
from .models import (DispenseRecord, GoodsReceiptNote, PurchaseOrder,
                     PurchaseRequisition, StockBatch)

VIEW_STOCK = "pharmacy.view_stockbatch"
ADD_STOCK = "pharmacy.add_stockbatch"
CHANGE_STOCK = "pharmacy.change_stockbatch"


def _int_or_zero(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _decimal_or_zero(value):
    from decimal import Decimal, InvalidOperation

    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError):
        return Decimal("0")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/dashboard.html"
    permission_required = VIEW_STOCK

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Pharmacy · Dashboard"),
                "dashboard": selectors.pharmacy_dashboard(),
                "expiring": selectors.expiring_batches(int(self._days()))[:10],
                "low_stock": selectors.low_stock_drugs()[:10],
            }
        )

    @staticmethod
    def _days():
        from django.conf import settings

        return settings.IHMS.get("PHARMACY_EXPIRY_ALERT_DAYS", 30)


# ---------------------------------------------------------------------------
# Dispensing
# ---------------------------------------------------------------------------
class DispenseListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/dispense_list.html"
    permission_required = "pharmacy.view_dispenserecord"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Pharmacy · Dispensing"),
                "records": selectors.dispense_list()[:200],
                "unbilled": selectors.unbilled_dispenses().count(),
            }
        )


class DispenseCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "pharmacy.add_dispenserecord"

    def _prescription(self, pk):
        return get_object_or_404(
            Prescription.objects.select_related("patient", "doctor"), pk=pk
        )

    def get(self, request, *args, **kwargs):
        prescription = self._prescription(kwargs["pk"])
        return render(
            request,
            "pharmacy/dispense_create.html",
            {
                "page_title": _("Dispense · prescription #%(pk)s")
                % {"pk": prescription.pk},
                "prescription": prescription,
                "items": prescription.items.select_related("drug"),
                "form": DispenseForm(),
            },
        )

    def post(self, request, *args, **kwargs):
        prescription = self._prescription(kwargs["pk"])
        form = DispenseForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Select a store."))
            return redirect("pharmacy:dispense_create", pk=prescription.pk)
        quantities = {
            item.pk: _int_or_zero(request.POST.get(f"qty_{item.pk}", 0))
            for item in prescription.items.all()
        }
        try:
            record = services.dispense_prescription(
                prescription=prescription,
                store=form.cleaned_data["store"],
                quantities=quantities,
                actor=request.user,
                request=request,
                notes=form.cleaned_data.get("notes", ""),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("pharmacy:dispense_create", pk=prescription.pk)
        messages.success(request, _("Dispensed successfully."))
        return redirect("pharmacy:dispense_detail", pk=record.pk)


class DispenseDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/dispense_detail.html"
    permission_required = "pharmacy.view_dispenserecord"

    def get(self, request, *args, **kwargs):
        record = get_object_or_404(
            DispenseRecord.objects.select_related("patient", "store", "prescription"),
            pk=kwargs["pk"],
        )
        return self.render_to_response(
            {
                "page_title": _("Dispense #%(pk)s") % {"pk": record.pk},
                "record": record,
                "items": record.items.select_related("drug", "batch"),
            }
        )


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------
class StockListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/stock_list.html"
    permission_required = VIEW_STOCK

    def get(self, request, *args, **kwargs):
        data = request.GET
        store = selectors.store_list().filter(pk=data.get("store") or 0).first()
        return self.render_to_response(
            {
                "page_title": _("Pharmacy · Stock"),
                "batches": selectors.stock_list(
                    store=store,
                    search=data.get("q", ""),
                    include_expired=data.get("expired") == "1",
                    with_stock=data.get("with_stock") == "1",
                ),
                "stores": selectors.store_list(),
                "selected_store": store,
                "filters": data,
            }
        )


class BatchCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = ADD_STOCK

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "pharmacy/batch_form.html",
            {"page_title": _("Pharmacy · New batch"), "form": StockBatchForm()},
        )

    def post(self, request, *args, **kwargs):
        form = StockBatchForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "pharmacy/batch_form.html",
                {"page_title": _("Pharmacy · New batch"), "form": form},
            )
        cd = form.cleaned_data
        batch = services.add_stock_batch(
            store=cd["store"],
            drug=cd["drug"],
            batch_no=cd["batch_no"],
            quantity=cd["quantity"],
            expiry_date=cd.get("expiry_date"),
            purchase_price=cd.get("purchase_price") or 0,
            mrp=cd.get("mrp") or 0,
            actor=request.user,
            request=request,
        )
        messages.success(request, _("Stock batch saved."))
        return redirect("pharmacy:batch_detail", pk=batch.pk)


class BatchDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/batch_detail.html"
    permission_required = VIEW_STOCK

    def get(self, request, *args, **kwargs):
        batch = get_object_or_404(
            StockBatch.objects.select_related("store", "drug"), pk=kwargs["pk"]
        )
        return self.render_to_response(
            {
                "page_title": _("Batch · %(b)s") % {"b": batch.batch_no},
                "batch": batch,
                "movements": selectors.stock_movements(batch=batch),
                "adjust_form": StockAdjustForm(
                    initial={"new_quantity": batch.quantity}
                ),
                "return_form": ReturnToVendorForm(),
            }
        )


class BatchActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    """Adjust stock or return to vendor for one batch."""

    permission_required = CHANGE_STOCK

    def post(self, request, *args, **kwargs):
        batch = get_object_or_404(StockBatch, pk=kwargs["pk"])
        action = kwargs["action"]
        try:
            if action == "adjust":
                form = StockAdjustForm(request.POST)
                if not form.is_valid():
                    messages.error(request, _("Enter a new quantity and reason."))
                    return redirect("pharmacy:batch_detail", pk=batch.pk)
                services.adjust_stock(
                    batch=batch,
                    new_quantity=form.cleaned_data["new_quantity"],
                    reason=form.cleaned_data["reason"],
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Stock adjusted."))
            elif action == "return":
                form = ReturnToVendorForm(request.POST)
                if not form.is_valid():
                    messages.error(request, _("Enter a valid quantity."))
                    return redirect("pharmacy:batch_detail", pk=batch.pk)
                services.return_to_vendor(
                    batch=batch,
                    quantity=form.cleaned_data["quantity"],
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Returned to vendor."))
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("pharmacy:batch_detail", pk=batch.pk)


class TransferView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = CHANGE_STOCK

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "pharmacy/transfer.html",
            {"page_title": _("Pharmacy · Stock transfer"), "form": TransferForm()},
        )

    def post(self, request, *args, **kwargs):
        form = TransferForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "pharmacy/transfer.html",
                {"page_title": _("Pharmacy · Stock transfer"), "form": form},
            )
        cd = form.cleaned_data
        try:
            services.transfer_stock(
                from_store=cd["from_store"],
                to_store=cd["to_store"],
                drug=cd["drug"],
                quantity=cd["quantity"],
                actor=request.user,
                request=request,
                notes=cd.get("notes", ""),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                "pharmacy/transfer.html",
                {"page_title": _("Pharmacy · Stock transfer"), "form": form},
            )
        messages.success(request, _("Stock transferred."))
        return redirect("pharmacy:stock_list")


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
class ExpiryAlertsView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/expiry_alerts.html"
    permission_required = VIEW_STOCK

    def get(self, request, *args, **kwargs):
        from django.conf import settings

        days = int(settings.IHMS.get("PHARMACY_EXPIRY_ALERT_DAYS", 30))
        return self.render_to_response(
            {
                "page_title": _("Pharmacy · Expiry alerts"),
                "days": days,
                "expiring": selectors.expiring_batches(days),
                "expired": selectors.expired_batches(),
            }
        )


class LowStockView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/low_stock.html"
    permission_required = VIEW_STOCK

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Pharmacy · Low stock"),
                "rows": selectors.low_stock_drugs(),
            }
        )


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------
class VendorListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/vendor_list.html"
    permission_required = "pharmacy.view_vendor"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Pharmacy · Vendors"),
                "vendors": selectors.vendor_list(active_only=False),
            }
        )


class VendorCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "pharmacy.add_vendor"

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "pharmacy/vendor_form.html",
            {"page_title": _("Pharmacy · New vendor"), "form": VendorForm()},
        )

    def post(self, request, *args, **kwargs):
        form = VendorForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "pharmacy/vendor_form.html",
                {"page_title": _("Pharmacy · New vendor"), "form": form},
            )
        form.save()
        messages.success(request, _("Vendor saved."))
        return redirect("pharmacy:vendor_list")


# ---------------------------------------------------------------------------
# Requisitions
# ---------------------------------------------------------------------------
class RequisitionListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    def get_permission_required(self):
        if self.request.method == "POST":
            return ("pharmacy.add_purchaserequisition",)
        return ("pharmacy.view_purchaserequisition",)

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "pharmacy/requisition_list.html",
            {
                "page_title": _("Pharmacy · Requisitions"),
                "requisitions": selectors.requisition_list(
                    status=request.GET.get("status", "")
                ),
                "form": RequisitionForm(),
                "drugs": selectors.drug_options(),
                "vendors": selectors.vendor_list(),
            },
        )

    def post(self, request, *args, **kwargs):
        form = RequisitionForm(request.POST)
        drugs = request.POST.getlist("drug")
        quantities = request.POST.getlist("quantity")
        items = [
            {"drug_id": d, "quantity": _int_or_zero(q)}
            for d, q in zip(drugs, quantities)
            if d and _int_or_zero(q) > 0
        ]
        if not form.is_valid() or not items:
            messages.error(request, _("Provide a store and at least one line item."))
            return redirect("pharmacy:requisition_list")
        services.create_requisition(
            store=form.cleaned_data["store"],
            items=items,
            needed_by=form.cleaned_data.get("needed_by"),
            notes=form.cleaned_data.get("notes", ""),
            actor=request.user,
            request=request,
        )
        messages.success(request, _("Requisition created."))
        return redirect("pharmacy:requisition_list")


class RequisitionActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "pharmacy.change_purchaserequisition"

    def post(self, request, *args, **kwargs):
        requisition = get_object_or_404(PurchaseRequisition, pk=kwargs["pk"])
        action = kwargs["action"]
        try:
            if action == "approve":
                services.set_requisition_status(
                    requisition=requisition,
                    status="approved",
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Requisition approved."))
            elif action == "reject":
                services.set_requisition_status(
                    requisition=requisition,
                    status="rejected",
                    actor=request.user,
                    request=request,
                )
                messages.warning(request, _("Requisition rejected."))
            elif action == "convert":
                vendor = (
                    selectors.vendor_list()
                    .filter(pk=request.POST.get("vendor") or 0)
                    .first()
                )
                if vendor is None:
                    messages.error(request, _("Select a vendor to convert."))
                else:
                    po = services.convert_requisition_to_po(
                        requisition=requisition,
                        vendor=vendor,
                        actor=request.user,
                        request=request,
                    )
                    messages.success(
                        request, _("Converted to %(po)s.") % {"po": po.po_number}
                    )
                    return redirect("pharmacy:po_detail", pk=po.pk)
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("pharmacy:requisition_list")


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------
class POListView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    def get_permission_required(self):
        if self.request.method == "POST":
            return ("pharmacy.add_purchaseorder",)
        return ("pharmacy.view_purchaseorder",)

    def get(self, request, *args, **kwargs):
        return render(
            request,
            "pharmacy/po_list.html",
            {
                "page_title": _("Pharmacy · Purchase orders"),
                "orders": selectors.purchase_order_list(
                    status=request.GET.get("status", "")
                ),
                "form": PurchaseOrderForm(),
                "drugs": selectors.drug_options(),
            },
        )

    def post(self, request, *args, **kwargs):
        form = PurchaseOrderForm(request.POST)
        drugs = request.POST.getlist("drug")
        quantities = request.POST.getlist("quantity")
        prices = request.POST.getlist("unit_price")
        items = []
        for drug, qty, price in zip(drugs, quantities, prices):
            if drug and _int_or_zero(qty) > 0:
                items.append(
                    {
                        "drug_id": drug,
                        "quantity_ordered": _int_or_zero(qty),
                        "unit_price": _decimal_or_zero(price),
                    }
                )
        if not form.is_valid() or not items:
            messages.error(
                request, _("Provide a vendor, store and at least one line item.")
            )
            return redirect("pharmacy:po_list")
        po = services.create_purchase_order(
            vendor=form.cleaned_data["vendor"],
            store=form.cleaned_data["store"],
            items=items,
            notes=form.cleaned_data.get("notes", ""),
            actor=request.user,
            request=request,
        )
        messages.success(
            request, _("Purchase order %(po)s created.") % {"po": po.po_number}
        )
        return redirect("pharmacy:po_detail", pk=po.pk)


class PODetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/po_detail.html"
    permission_required = "pharmacy.view_purchaseorder"

    def get(self, request, *args, **kwargs):
        po = get_object_or_404(
            PurchaseOrder.objects.select_related("vendor", "store"), pk=kwargs["pk"]
        )
        return self.render_to_response(
            {
                "page_title": _("Purchase order · %(po)s") % {"po": po.po_number},
                "po": po,
                "items": po.items.select_related("drug"),
                "grns": po.grns.all(),
            }
        )


class POActionView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "pharmacy.change_purchaseorder"

    def post(self, request, *args, **kwargs):
        po = get_object_or_404(PurchaseOrder, pk=kwargs["pk"])
        action = kwargs["action"]
        try:
            if action == "send":
                services.set_purchase_order_status(
                    purchase_order=po,
                    status="sent",
                    actor=request.user,
                    request=request,
                )
                messages.success(request, _("Purchase order sent."))
            elif action == "cancel":
                services.set_purchase_order_status(
                    purchase_order=po,
                    status="cancelled",
                    actor=request.user,
                    request=request,
                )
                messages.warning(request, _("Purchase order cancelled."))
            elif action == "receive":
                return redirect("pharmacy:grn_create", pk=po.pk)
            else:
                messages.error(request, _("Unknown action."))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("pharmacy:po_detail", pk=po.pk)


# ---------------------------------------------------------------------------
# Goods receipt notes
# ---------------------------------------------------------------------------
class GRNListView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/grn_list.html"
    permission_required = "pharmacy.view_goodsreceiptnote"

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            {
                "page_title": _("Pharmacy · Goods receipts"),
                "grns": selectors.grn_list(),
            }
        )


class GRNCreateView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    permission_required = "pharmacy.add_goodsreceiptnote"

    def _po(self, pk):
        return get_object_or_404(
            PurchaseOrder.objects.select_related("vendor", "store"), pk=pk
        )

    def get(self, request, *args, **kwargs):
        po = self._po(kwargs["pk"])
        return render(
            request,
            "pharmacy/grn_create.html",
            {
                "page_title": _("Receive · %(po)s") % {"po": po.po_number},
                "po": po,
                "items": po.items.select_related("drug"),
                "form": GRNForm(),
            },
        )

    def post(self, request, *args, **kwargs):
        po = self._po(kwargs["pk"])
        form = GRNForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Invalid receipt details."))
            return redirect("pharmacy:grn_create", pk=po.pk)
        item_ids = request.POST.getlist("item_id")
        batch_nos = request.POST.getlist("batch_no")
        expiries = request.POST.getlist("expiry_date")
        quantities = request.POST.getlist("quantity")
        prices = request.POST.getlist("purchase_price")
        mrps = request.POST.getlist("mrp")

        po_items = {str(i.pk): i for i in po.items.select_related("drug")}
        rows = []
        for item_id, batch_no, expiry, qty, price, mrp in zip(
            item_ids, batch_nos, expiries, quantities, prices, mrps
        ):
            po_item = po_items.get(str(item_id))
            if po_item is None or _int_or_zero(qty) <= 0:
                continue
            rows.append(
                {
                    "po_item": po_item,
                    "drug": po_item.drug,
                    "batch_no": batch_no,
                    "expiry_date": expiry or None,
                    "quantity": _int_or_zero(qty),
                    "purchase_price": _decimal_or_zero(price),
                    "mrp": _decimal_or_zero(mrp),
                }
            )
        if not rows:
            messages.error(request, _("Enter at least one received line."))
            return redirect("pharmacy:grn_create", pk=po.pk)
        try:
            grn = services.receive_grn(
                store=po.store,
                purchase_order=po,
                items=rows,
                received_date=form.cleaned_data.get("received_date"),
                notes=form.cleaned_data.get("notes", ""),
                actor=request.user,
                request=request,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("pharmacy:grn_create", pk=po.pk)
        messages.success(
            request, _("Goods received · %(grn)s.") % {"grn": grn.grn_number}
        )
        return redirect("pharmacy:grn_detail", pk=grn.pk)


class GRNDetailView(
    IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, TemplateResponseMixin, View
):
    template_name = "pharmacy/grn_detail.html"
    permission_required = "pharmacy.view_goodsreceiptnote"

    def get(self, request, *args, **kwargs):
        grn = get_object_or_404(
            GoodsReceiptNote.objects.select_related(
                "vendor", "store", "purchase_order"
            ),
            pk=kwargs["pk"],
        )
        return self.render_to_response(
            {
                "page_title": _("GRN · %(grn)s") % {"grn": grn.grn_number},
                "grn": grn,
                "items": grn.items.select_related("drug"),
            }
        )
