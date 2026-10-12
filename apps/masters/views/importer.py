"""CSV bulk-import view for masters."""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views import View

from core.mixins import IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin

from .. import importers
from ..forms import CsvImportForm
from ..registry import MASTER_BY_SLUG


class MasterImportView(IHMSLoginRequiredMixin, IHMSPermissionRequiredMixin, View):
    template_name = "masters/import.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.spec = MASTER_BY_SLUG.get(kwargs.get("slug", ""))
        if self.spec is None:
            raise Http404("Unknown master type")

    def get_permission_required(self):
        return (self.spec.add_perm,)

    def get(self, request, *args, **kwargs):
        if request.GET.get("template"):
            response = HttpResponse(
                importers.csv_template(self.spec), content_type="text/csv"
            )
            response["Content-Disposition"] = (
                f'attachment; filename="{self.spec.slug}-template.csv"'
            )
            return response
        form = CsvImportForm()
        return render(request, self.template_name, self._context(form))

    def post(self, request, *args, **kwargs):
        form = CsvImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, self._context(form))

        try:
            result = importers.import_csv(
                self.spec,
                csv_file=form.cleaned_data["csv_file"],
                actor=request.user,
                request=request,
                skip_errors=form.cleaned_data["skip_errors"],
            )
        except ValueError as exc:
            messages.error(request, _("Import aborted: %(error)s") % {"error": exc})
            return render(request, self.template_name, self._context(form))

        if result.errors:
            messages.warning(
                request,
                _("Imported %(ok)s row(s) with %(bad)s error(s).")
                % {"ok": result.processed, "bad": len(result.errors)},
            )
        else:
            messages.success(
                request,
                _("Import complete: %(created)s created, %(updated)s updated.")
                % {"created": result.created, "updated": result.updated},
            )
        return redirect("masters:master_list", slug=self.spec.slug)

    def _context(self, form):
        return {
            "form": form,
            "spec": self.spec,
            "page_title": _("Import %(label)s") % {"label": self.spec.label_plural},
            "columns": self.spec.import_fields,
        }
