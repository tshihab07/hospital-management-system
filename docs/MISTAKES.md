# IHMS — Mistakes & Deviations Log

Every time we deviate from `docs/RULES.md`, `docs/PRD.md`,
`docs/ARCHITECTURE.md` or the user's explicit instructions, it goes here,
followed by a review and a correction. Keep newest at the bottom.

Format:
- **ID / date / batch** · what happened · why · corrective action · status.

---

## M-001 · B0 · `LOGIN_REDIRECT_URL` pointed at a non-existent namespace
- **What:** `config/settings/base.py` set `LOGIN_REDIRECT_URL = "dashboard:home"`,
  but no `dashboard` URL namespace exists.
- **Why:** leftover from the initial scaffold guess before the custom panel
  namespace (`panel`) was chosen.
- **Fix:** changed to `LOGIN_REDIRECT_URL = "panel:home"`.
- **Status:** ✅ corrected (verified: post-login 302 → `/admin/`).

## M-002 · B0 · Template used `ihms_tags` filter without loading the library
- **What:** `templates/accounts/profile.html` used `|ihms_datetime` but only
  `{% load i18n %}`, causing `TemplateSyntaxError: Invalid filter`.
- **Why:** Django does not inherit loaded template tags from parent templates.
- **Fix:** added `{% load i18n ihms_tags %}` at the top of the template.
- **Status:** ✅ corrected (profile now returns 200).
- **Preventive rule:** every template that uses an `ihms_tags` filter/tag must
  `{% load ihms_tags %}` itself — never rely on `layouts/app.html`.

## M-003 · B0 · `templates/errors/*.html` sit in a subfolder Django won't auto-find
- **What:** Django only auto-resolves top-level `403.html`/`404.html`/`500.html`.
  Our files live at `templates/errors/403.html`, etc.
- **Why:** error templates grouped under `errors/` for tidiness.
- **Fix:** explicit `handler403/404/500 = "core.views.handlerXXX"` in
  `config/urls.py` render `errors/*.html` with the right status code.
- **Status:** ✅ corrected (unknown URL returns 404 with our template).

## M-004 · B1 · Scaffold left empty `selectors/` and `services/` packages shadowing new modules
- **What:** `apps/accounts/selectors/__init__.py` and `services/__init__.py`
  (empty dirs from the initial scaffold) shadowed the new
  `apps/accounts/selectors.py` / `services.py`. Python imports the *package*
  in preference to the module, so `selectors.user_list` raised
  `AttributeError` and every list view returned 500.
- **Why:** the scaffold pre-created empty package directories for planned
  modules; the filenames chosen collided with them.
- **Fix:** removed the empty `selectors/` and `services/` directories.
- **Status:** ✅ corrected (all pages 200; 15 tests pass).
- **Preventive rule:** when adding a `<name>.py` module, check no empty
  `<name>/` package of the same name exists in the app.

## M-005 · B1 · `log_action` crashed on Django's bare `HttpRequest` from `force_login`
- **What:** `AuditLog` creation did `request.method[:10]`; Django's
  `force_login()` sends a bare `HttpRequest()` (with `method = None`) to the
  `user_logged_in` signal, so audit logging raised
  `TypeError: 'NoneType' object is not subscriptable` during tests.
- **Why:** assumed `request.method`/`path`/`META` always exist.
- **Fix:** `core/audit.py` now uses
  `getattr(request, "method", "") or ""` (and the same guards for `path`
  and `META`).
- **Status:** ✅ corrected (login/audit logging works in tests).
- **Preventive rule:** never assume request attributes are present in the
  audit helper — signals may pass synthetic requests.

## M-008 · B4 · Stray `09 Science/` tree recreated while writing a management command
- **What:** while writing `seed_doctors.py` the path was typed as
  `.../03. Python Programming/09 Science/tmp_seed.py`, creating a brand-new
  `09 Science/` directory outside the project.
- **Why:** same free-typing root cause as M-006 / M-007.
- **Fix:** the stray tree was removed in the same turn and the file rewritten
  to the real path; a directory listing confirmed only the expected
  `01 … 09 Data Science …` entries remain.
- **Preventive rule (third strike):** for every Write, paste the absolute path
  from a just-executed `ls`/`glob` result. If in doubt, `cd` is forbidden but
  `bash` with `workdir` + a relative path for the append/verification step is
  strongly preferred over typing the absolute path by hand.

---

## M-007 · B3 · Same stray-path bug; new malformed variants typed during file writes
- **What:** despite M-006's rule, additional malformed paths were used during
  B3, e.g. `.../09/Data Science/...` and `.../09 Data Science/04/BackendDevelopment/...`
  and a bare `09` directory. Each created a stray tree that was deleted.
- **Why:** the same root cause as M-006 (typing the long absolute path fast).
- **Fix:** every stray tree removed; verified parent dir shows exactly the
  expected `01 AnalyticalDashboards … 04 BackendDevelopment …` set. All B3
  files verified under the real project root.
- **Status:** ✅ corrected (no stray files remain).
- **Preventive rule (reinforced):** never free-type the absolute path. Copy it
  from `ls`/`glob`/env output once per call, or use `bash` with `workdir` +
  relative path when writing content.

---

## M-006 · B1/B2 · Files repeatedly written/deleted to a wrong path missing `Data ` + project folder
- **What:** several `write`/`edit` calls targeted the malformed path
  `.../09 Science/04 BackendDevelopment` (missing `Data ` and the project
  directory) instead of the real project root. Stray files/dirs were created
  and had to be `rm`-ed each time.
- **Why:** the correct root is long and the shortened path is easy to type by
  accident when in a hurry.
- **Fix:** deleted the stray `09 Science` tree after each occurrence; all
  current files live under the correct root.
- **Status:** ✅ corrected (no stray files remain).
- **Preventive rule:** the only valid base is
  `.../09 Data Science/04 BackendDevelopment/Django_506_20260924_HospitalManagementSystem/`.
  Re-read the target path before every write/edit; prefer absolute paths
  copied from a `glob`/`ls` result.

## M-009 · B5 · Stray `09 Science/` tree recreated again while writing HR views
- **What:** writing `shifts.py` / `roster.py` targeted
  `.../09 Science/hr_views_shifts.py` and `.../09 Science/hr_views_roster.py`,
  creating a stray `09 Science/` directory twice.
- **Why:** free-typing the long absolute path (same root cause as M-006/7/8).
- **Fix:** stray tree `rm -rf`-ed each time; switched to staging files in
  `/tmp/opencode/` then `cp`-ing them with `bash` `workdir` + a **relative**
  destination path — this avoided the long-path typing entirely.
- **Status:** ✅ corrected (no stray files remain).
- **Preventive rule (fourth strike — now the default workflow):** for multi-file
  batches, write to `/tmp/opencode/<name>` and `cp` with a relative path via
  `bash workdir`. Reserve the Write tool's absolute path for single files only,
  pasted from a just-run `ls`/`glob`.

## M-010 · B5 · `_, created = ...` in `import_attendance_rows` shadowed gettext `_`
- **What:** `apps/hr/services.py` aliases `gettext as _` at module level, but
  inside `import_attendance_rows` a loop did `_, created = upsert_attendance(...)`.
  Python treats `_` as a **function-local** name for the whole function, so on a
  later row the `raise ValueError(_("Unknown employee code…"))` tried to *call*
  an `Attendance` object → `TypeError: 'Attendance' object is not callable`.
- **Why:** reusing `_` as an unused-tuple slot in a function that also calls `_()`.
- **Fix:** renamed to `_record` (and `_created` in `_balance_for`).
- **Status:** ✅ corrected (import test now passes).
- **Preventive rule:** never use `_` as a throwaway name in a module that does
  `gettext as _`; use a descriptive name.

## M-011 · B5 · `seed_hr` violated the unique `Designation.code` constraint
- **What:** creating a missing designation with only `name=` left `code=""`,
  but `Designation.code` is unique and `masters` already had a `''` code, so the
  second insert failed with `IntegrityError: duplicate key … code=()`.
- **Why:** assumed `code` was optional/nullable-unique like the doctor fields.
- **Fix:** `seed_hr` now reuses existing designations (case-insensitive) and,
  when creating one, derives a unique code from the name's initials with a
  numeric suffix on collision.
- **Status:** ✅ corrected (seed completes: 5 staff, 30 roster, 30 attendance).
- **Preventive rule:** before seeding a FK target, check its unique/blank
  constraints; seed idempotently and reuse existing rows.

## M-012 · B4 (found in B5) · Time-dependent flaky OPD reminder test
- **What:** `apps/opd/tests/test_reminders.py::test_1h_reminder_within_window`
  built a same-day slot from `now + 2h`; run late at night `now + 2h` wraps
  past midnight, so `slot.end_time <= now.time()` and the booking guard
  rejected it → intermittent failure (passed all day, failed at 23:xx).
- **Why:** test computed wall-clock times without pinning the clock.
- **Fix:** wrapped the test in `@freeze_time("2026-06-15 10:00:00+06:00")`.
- **Status:** ✅ corrected (suite deterministic: 113 passed).

## M-013 · B6 · Test created an `Appointment` without `token_no`
- **What:** the EMR view test built `Appointment.objects.create(patient=…,
  doctor=…, appt_date=…)` and hit `IntegrityError: NOT NULL constraint
  failed: opd_appointment.token_no`; only the service normally assigns tokens.
- **Why:** direct model creation bypasses `services.book_appointment`, which
  is what allocates the per-doctor daily token.
- **Fix:** pass `token_no=1` in the test factory/appointment helper.
- **Status:** ✅ corrected (145 passed).
- **Preventive rule:** when a model field is populated by a service, either go
  through the service in tests or set the field explicitly; check NOT NULL.

## M-014 · B6 · Two URL patterns sharing one `name`
- **What:** `/emr/` and `/emr/encounters/` both pointed at `EncounterListView`
  with `name="encounter_list"`, making `reverse()` ambiguous (returned the
  last registered).
- **Why:** convenience aliasing without a distinct name.
- **Fix:** root `/emr/` is now a `RedirectView` (`name="home"`); the canonical
  named route is `/emr/encounters/` (`name="encounter_list"`).
- **Status:** ✅ corrected.
- **Preventive rule:** never register two patterns with the same URL name.

## M-015 · B7 · SQLite `create()` returned `str` for `DecimalField` values
- **What:** `DailyCharge.total` summed `bed_charge + nursing_charge +
  doctor_visit_charge`; on a freshly `objects.create()`d row the test saw
  `'1000300500'` (string concatenation) instead of `1800`. Re-fetching via a
  SELECT returned proper `Decimal`s (so the service tests passed).
- **Why:** Django 5 uses `INSERT … RETURNING` on SQLite, and the value handed
  back on the created instance is not run through `from_db_value`, so it stays
  the raw `str`; SELECTs convert via `from_db_value` → `Decimal`.
- **Fix:** coerce in the property: `sum((Decimal(str(v)) for v in values), Decimal("0"))`.
- **Status:** ✅ corrected (178 passed).
- **Preventive rule:** don't assume `Model.objects.create(...)` returns
  type-converted field values on SQLite; re-fetch, or coerce defensively in
  computed properties that will be rendered/summed.

## M-016 · B7 · Wrong `IntegrityError` import path
- **What:** tests did `from django.core.exceptions import IntegrityError` →
  `ImportError` at collection.
- **Why:** `IntegrityError` lives in `django.db`, not `django.core.exceptions`.
- **Fix:** `from django.db import IntegrityError`.
- **Status:** ✅ corrected.
- **Preventive rule:** DB exceptions (`IntegrityError`, `DatabaseError`) come
  from `django.db`.

## M-017 · B7 · Lazy FK pointed at the wrong app (`"emr.Drug"`)
- **What:** `MedicationAdministration.drug = ForeignKey("emr.Drug")` failed
  system check: `app 'emr' doesn't provide model 'drug'`.
- **Why:** `Drug` is defined in `apps.masters`; `apps.emr` merely re-imports it,
  so the lazy reference must use the *defining* app label.
- **Fix:** `ForeignKey("masters.Drug")` (import `Drug` from `apps.masters.models`).
- **Status:** ✅ corrected (`check` clean).
- **Preventive rule:** lazy string FK references must use the app that *defines*
  the model, not one that re-exports it.

---

## Open questions / deliberate deferrals
- **2FA deferred** (B0 decision): RBAC + `django-axes` lockout used instead for
  now; revisit before production sign-off.
- **Celery/Redis optional** with graceful fallback (`CELERY_TASK_ALWAYS_EAGER`).
- **`docs/` is git-ignored** in the current `.gitignore`; if these docs must be
  version-controlled, the ignore rule needs revisiting (pending user call).
