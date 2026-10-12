"""Root URL configuration for IHMS.

  /admin/         → custom IHMS control-tower panel
  /django-admin/  → stock Django admin (internal use)
  /accounts/      → authentication & profile
  /masters/       → master data & configuration
  /patients/      → patient registration & records
  /opd/           → outpatient doctors & appointments
  /hr/            → doctor & staff management
  /emr/           → EMR & CPOE (clinical core)
  /ipd/           → IPD, admission & bed management
  /health/        → liveness probe
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import set_language

from core import views as core_views

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("admin/", include("apps.adminpanel.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("masters/", include("apps.masters.urls")),
    path("patients/", include("apps.patients.urls")),
    path("opd/", include("apps.opd.urls")),
    path("hr/", include("apps.hr.urls")),
    path("emr/", include("apps.emr.urls")),
    path("ipd/", include("apps.ipd.urls")),
    path("i18n/setlang/", set_language, name="set_language"),
    path("health/", core_views.health, name="health"),
    path("", core_views.root_redirect, name="root"),
]

# Custom error handlers (templates live under templates/errors/).
handler403 = "core.views.handler403"
handler404 = "core.views.handler404"
handler500 = "core.views.handler500"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    try:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:  # pragma: no cover
        pass
