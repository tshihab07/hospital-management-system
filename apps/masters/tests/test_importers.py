"""CSV import tests."""

from __future__ import annotations

import io

import pytest

from apps.masters import importers
from apps.masters.models import Drug
from apps.masters.registry import MASTER_BY_SLUG

pytestmark = pytest.mark.django_db


class _Upload:
    """Minimal file-like object exposing ``read``."""

    def __init__(self, text: str):
        self._buffer = io.StringIO(text)

    def read(self):
        return self._buffer.read()


def test_csv_template_has_headers():
    template = importers.csv_template(MASTER_BY_SLUG["drugs"])
    header = template.splitlines()[0]
    assert "generic_name" in header
    assert "unit_price" in header


def test_import_creates_drugs():
    csv = "generic_name,brand_name,form,strength,unit_price\nNapa,Acme,tablet,500mg,1.50\nZithro,Acme,tablet,250mg,9.00\n"
    result = importers.import_csv(MASTER_BY_SLUG["drugs"], csv_file=_Upload(csv))
    assert result.created == 2
    assert result.errors == []
    assert Drug.objects.count() == 2


def test_import_updates_on_duplicate_natural_key():
    csv1 = "generic_name,brand_name,form,strength,unit_price\nNapa,Acme,tablet,500mg,1.50\n"
    importers.import_csv(MASTER_BY_SLUG["drugs"], csv_file=_Upload(csv1))
    csv2 = "generic_name,brand_name,form,strength,unit_price\nNapa,Acme,tablet,500mg,2.00\n"
    result = importers.import_csv(MASTER_BY_SLUG["drugs"], csv_file=_Upload(csv2))
    assert result.updated == 1
    assert Drug.objects.count() == 1
    assert Drug.objects.get().unit_price == 2


def test_import_reports_bad_rows_and_continues():
    csv = "generic_name,brand_name,form,strength,unit_price\n,Acme,tablet,500mg,1.50\nGood,Acme,tablet,250mg,9.00\n"
    result = importers.import_csv(
        MASTER_BY_SLUG["drugs"], csv_file=_Upload(csv), skip_errors=True
    )
    assert result.created == 1
    assert len(result.errors) == 1
    assert result.errors[0][0] == 2
