"""CSV bulk-import for masters.

Rows are validated through the master's own :class:`ModelForm`, so imported
data obeys exactly the same rules as the manual entry screens. Records are
matched on a natural key (``code`` when present, otherwise ``name``) and
updated in place when found.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from django.db import transaction

from core.audit import AuditAction, log_action

from .registry import MasterSpec


@dataclass
class ImportResult:
    total: int = 0
    created: int = 0
    updated: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def processed(self) -> int:
        return self.created + self.updated


def _clean_row(row: dict) -> dict:
    cleaned = {}
    for key, value in row.items():
        if key is None:
            continue
        value = (value or "").strip()
        cleaned[key.strip()] = value
    return {k: v for k, v in cleaned.items() if k}


def _natural_key_instance(spec: MasterSpec, data: dict):
    """Locate an existing record to update, or return ``None`` to insert."""
    field_names = {f.name for f in spec.model._meta.fields}
    for key in ("code", "name", "generic_name"):
        if key in field_names and data.get(key):
            lookup = {key: data[key]}
            return spec.model.objects.filter(**lookup).first()
    return None


def _import_row(
    spec: MasterSpec, data: dict, *, actor, request, result: ImportResult, row_no: int
):
    allowed = set(spec.import_fields) or {f.name for f in spec.model._meta.fields}
    payload = {k: v for k, v in data.items() if k in allowed}

    # Fill columns the CSV did not provide so optional/defaulted fields do not
    # raise "this field is required" errors during validation.
    model_fields = {f.name: f for f in spec.model._meta.fields}
    for name in allowed:
        if name in payload:
            continue
        field = model_fields.get(name)
        if field is None:
            continue
        if field.has_default():
            payload[name] = field.get_default()
        elif field.blank:
            payload[name] = ""

    instance = _natural_key_instance(spec, payload)
    form = spec.form(data=payload, instance=instance)

    if not form.is_valid():
        messages = "; ".join(
            f"{name}: {', '.join(errs)}" for name, errs in form.errors.items()
        )
        result.errors.append((row_no, messages))
        return

    obj = form.save()
    action = AuditAction.UPDATE if instance else AuditAction.CREATE
    log_action(
        action,
        instance=obj,
        changes=payload,
        user=actor,
        request=request,
    )
    if instance:
        result.updated += 1
    else:
        result.created += 1


@transaction.atomic
def import_csv(
    spec: MasterSpec, *, csv_file, actor=None, request=None, skip_errors: bool = True
) -> ImportResult:
    """Import ``csv_file`` into the master described by ``spec``.

    When ``skip_errors`` is false the first invalid row aborts the whole
    import (transaction rolls back). Otherwise invalid rows are reported and
    the valid ones are committed.
    """
    result = ImportResult()

    raw = csv_file.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))

    for row_no, row in enumerate(reader, start=2):  # row 1 is the header
        data = _clean_row(row)
        if not data:
            continue
        result.total += 1
        try:
            _import_row(
                spec, data, actor=actor, request=request, result=result, row_no=row_no
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator
            result.errors.append((row_no, str(exc)))
        if result.errors and not skip_errors:
            raise ValueError(result.errors[-1][1])
    return result


def csv_template(spec: MasterSpec) -> str:
    """Return a CSV template (header + one sample row) for ``spec``."""
    fields = spec.import_fields or [f.name for f in spec.model._meta.fields]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(fields)
    writer.writerow(["..." for _ in fields])
    return buffer.getvalue()
