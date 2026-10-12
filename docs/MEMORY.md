# IHMS — Project Memory

Chronological log of what was implemented, per step. Newest at the bottom.
Companion to `docs/MISTAKES.md` (deviations found & corrected).

## Legend
- **B0, B1, …** = delivery batch.
- ✅ done · 🔄 in progress · ⏳ planned.

---

## B0 — Project bootstrap & custom auth foundation ✅

### Tooling & environment
- Confirmed venv `.venv` (Python 3.12.3, Django 5.2.1).
- Rewrote `requirements.txt`:
  - Runtime: Django, python-dotenv, psycopg[binary], Pillow 10.4.0
    (weasyprint 63.0 requires Pillow<11), redis, celery, django-axes,
    weasyprint, whitenoise, gunicorn, django-widget-tweaks.
  - Dev: pytest, pytest-django, pytest-cov, factory-boy, Faker, freezegun,
    coverage, black, isort, flake8, ruff, bandit, pip-audit,
    django-debug-toolbar, nplusone.
- Installed all packages successfully.

### Settings split
- Deleted monolithic `config/settings.py`; created package:
  `config/settings/{__init__,base,dev,test,staging,prod}.py`.
- `base.py`: env loader (python-dotenv), `_build_database()` honouring
  `USE_REMOTE_DB`/`USE_POOLER`, `AUTH_USER_MODEL = "accounts.User"`, axes,
  i18n (`bn`/BDT/BST), IHMS config dict, `SUPER_ADMIN_*` read from env.
- `test.py`: SQLite in-memory (never touches Supabase).
- Updated `manage.py` (default `config.settings.dev`) and
  `config/wsgi.py` / `config/asgi.py` (default `config.settings.prod`).
- Added `config/celery.py` and Celery import in `config/__init__.py`.

### Database (Supabase PostgreSQL via pooler)
- Verified pooler works: `aws-0-ap-southeast-1.pooler.supabase.com:6543`.
- Direct host does not resolve → always use pooler.
- Pooler needs `prepare_threshold=None` (pgbouncer transaction mode) and
  `DISABLE_SERVER_SIDE_CURSORS=True`.
- `.env`: `USE_REMOTE_DB=True`, `DB_SSLMODE=require`, `DB_CONN_MAX_AGE=0`,
  Redis/Celery blanks (in-memory cache + eager tasks), email console backend.

### `core` app
- `models.py`: `TimeStampedModel`, `SoftDeleteModel`, `ActiveManager`.
- `managers.py`: `SoftDeleteQuerySet`, `SoftDeleteManager`, `AllObjectsManager`.
- `exceptions.py`: `IHMSException` tree + error codes.
- `audit.py`: `AuditAction`, `AuditLog`, `log_action`, `model_to_dict_safe`.
- `signals.py`: login/logout/failed hooks + `register_audit_signals`.
- `middleware.py`: `AuditRequestMiddleware`.
- `context_processors.py`: `ihms_context` + `nav_sections`.
- `mixins.py`, `permissions.py`, `threadlocals.py`, `utils/formatting.py`.
- `navigation.py`: full `NAV_SECTIONS`.
- `templatetags/ihms_tags.py`: `bdt`, `ihms_date`, `ihms_datetime`,
  `has_perm`, `has_any_perm`, `active`, `nav_url`, `is_active_nav`,
  `status_badge`.
- `views.py`: `health`, `root_redirect`, `handler403/404/500`.
- Management commands: `seed_superadmin`, `wait_for_db`.

### `apps.accounts` app
- `apps.py` (label `accounts`), `managers.py` (`UserManager`),
  `models.py` (custom `User`), `signals.py` (store login IP).
- `forms.py`: `LoginForm`, `ProfileForm`, password forms.
- `views/{__init__,auth,password,profile}.py`.
- `urls.py` (app_name `accounts`): login, logout, profile,
  password_change, password_reset[+done/confirm/complete].

### `apps.adminpanel` app
- `apps.py` (label `adminpanel`).
- `views/dashboard.py`: `DashboardHomeView` (placeholder KPIs).
- `urls.py` (app_name `panel`, `home`).

### Templates
- `layouts/{base,app,auth,sidebar,topbar}.html`
- `components/{messages,toast,status_badge,kpi_card,empty_state}.html`
- `errors/{base_error,403,404,500}.html`
- `registration/{login,password_reset_*,password_reset_email,password_reset_subject,password_change_form}.html`
- `dashboard/home.html`, `accounts/profile.html`

### Static
- `static/js/tailwind.config.js` (Clinical Indigo tokens)
- `static/js/app.js` (theme toggle, HTMX CSRF, Alpine stores, toasts)
- `static/css/ihms.css` (CSS vars, focus ring, tabular, skeleton)
- `static/img/favicon.svg`

### URL wiring
- `config/urls.py`:
  - `/django-admin/` → stock Django admin
  - `/admin/` → custom `panel` (app_name `panel`)
  - `/accounts/` → `accounts`
  - `/i18n/setlang/`, `/health/`, `/` (root redirect)
  - custom `handler403/404/500`; media + debug toolbar in DEBUG only.
- `LOGIN_REDIRECT_URL = "panel:home"`.

### Verification (B0)
- `manage.py check` → no issues.
- `makemigrations core accounts axes` → `core.0001_initial`,
  `accounts.0001_initial`, axes migrations.
- `migrate` applied to Supabase (contenttypes, auth, accounts, admin, axes,
  core, sessions) — all OK.
- `seed_superadmin` → created `tshihab07` (`tushar.shihab13@gmail.com`).
- Smoke test via test client: health 200, root→login, login_get 200,
  panel anon→login, login_post→`/admin/`, panel auth 200 (renders),
  profile 200, unknown→404, logout GET→405 (POST-only, expected).

### Tracking docs
- Created `docs/MEMORY.md` (this file) and `docs/MISTAKES.md`.

---

## B1 — RBAC & control tower core ✅

### Models
- `accounts.Role` (`TimeStampedModel`): `name` (unique), `description`,
  `is_system`, `permissions` M2M → `auth.Permission` (+ `permission_count`).
  Maps to ARCHITECTURE `ROLE` / `ROLE_PERMISSION`; reuses Django's permission
  catalogue so codenames are `<app_label>.<action>_<model>` (SKILLS-04).
- `User.roles` M2M → `Role` (maps to ARCHITECTURE `USER_ROLE`).
- `User` helpers: `role_names`, `primary_role`, `has_role(*names)`.

### Role-aware permissions
- `apps/accounts/backends.py::RolePermissionBackend` extends `ModelBackend`
  and unions every permission granted by the user's roles into
  `get_all_permissions` / `has_perm`. Registered after `ModelBackend` in
  `AUTHENTICATION_BACKENDS`. (Django resolves perms via backends, not via
  `User.has_perm`, so a model override would not have worked.)

### Selectors & services (RULES §2.2)
- `selectors.py`: `user_list`, `role_list`, `audit_log_list`,
  `permission_catalog` (permissions grouped by app label).
- `services.py` (all `@transaction.atomic` + audit): `create_user`,
  `update_user`, `set_user_password`, `set_user_active`, `create_role`,
  `update_role`, `delete_role` (system roles protected). Diffs via
  `model_to_dict_safe` + `_diff`.

### Forms
- `UserCreateForm` / `UserUpdateForm` (roles M2M, `password1/2` w/
  `validate_password`), `AdminSetPasswordForm`, `RoleForm`
  (`ModelMultipleChoiceField` checkboxes grouped in the template),
  `UserFilterForm`, `AuditFilterForm`.

### Views & URLs (`apps/accounts/views/{users,roles,audit}.py`)
- Users: list (filter/paginate), create, update, detail, toggle-active
  (POST, blocks self-deactivation), set-password.
- Roles: list, create, update, detail, delete (system roles blocked).
- Audit: list (filters), detail.
- Permissions enforced via `IHMSLoginRequiredMixin +
  IHMSPermissionRequiredMixin` (`accounts.view_user|add_user|change_user|
  view_role|change_role|delete_role`, `core.view_auditlog`).
- URL names match the existing nav: `accounts:user_list`, `accounts:role_list`,
  `accounts:audit_log`, etc.

### Templates
- `components/{form_field,pagination}.html`.
- `accounts/{user_list,user_form,user_detail,user_set_password,
  role_list,role_form,role_detail,role_confirm_delete,
  audit_log,audit_detail}.html`.

### Seed data
- `apps/accounts/management/commands/seed_roles.py`: idempotent creation of
  9 default roles (Super Admin, Hospital Admin, Auditor, Doctor, Nurse,
  Receptionist, Accountant, Lab Technician, Pharmacist) with `--sync` to
  refresh grants. Ran → 9 created.
- `seed_superadmin` now attaches the Super Admin role when seeded.

### Config
- `pytest.ini` (DJANGO_SETTINGS_MODULE=config.settings.test).
- `AUTHENTICATION_BACKENDS` gained `apps.accounts.backends.RolePermissionBackend`.

### Verification (B1)
- `manage.py check` → no issues.
- `migrate accounts` applied `accounts.0002_role_user_roles`.
- `seed_roles` → 9 roles; `seed_superadmin` re-run OK.
- Smoke test (dev/remote DB): all admin pages 200; role+user created with
  role-aware perm checks; non-superuser with `view_user` can list but gets
  403 on create/role pages; toggle + set-password + audit rows OK;
  system-role delete blocked; role/user/audit detail pages 200.
- `pytest apps/accounts/tests` → **15 passed** (models, backend, views).

### Notes / decisions
- Custom `Role` + Django `auth.Permission` chosen over a bespoke `Permission`
  model (ARCHITECTURE's `PERMISSION` table is realised by `auth.Permission`;
  `module` = `content_type.app_label`, `action` = codename prefix).
- 2FA still deferred.

---

## B2 — Master data & configuration ✅
New app `apps.masters` (label `masters`), registered in `LOCAL_APPS`.

### Models (`apps/masters/models/` package)
- `base.py`: `MasterModel(TimeStampedModel)` (adds `is_active`), `NamedMaster`
  (unique `name`), `CodedMaster` (adds unique `code`).
- `organization.py`: `Department` (type/head), `Designation` (category),
  `Ward` (type/floor/department), `BedType` (daily_rate), `Bed`
  (ward/bed_no/bed_type/rate override/status + `uniq_bed_per_ward`).
- `clinical.py`: `Drug` (generic/brand/form/strength/unit/price/reorder +
  `uniq_drug_variant`), `LabTest`, `RadiologyTest`, `Procedure`, `Diagnosis`
  (ICD-10 codes).
- `config.py`: `TaxConfig` (VAT/AIT/…), `PaymentMethod`, `NotificationTemplate`
  (bilingual), `HospitalProfile` singleton (`load()` helper).

### Registry, selectors, services, forms, importers
- `registry.py`: `MasterSpec` dataclass + `MASTERS` list + `MASTER_BY_SLUG` /
  `MASTER_GROUPS`, driving the generic list/form/import screens and nav.
- `selectors.master_queryset(spec, search, is_active)` (select_related on FKs).
- `services`: `create_master`, `update_master` (diff audit), `toggle_master_active`,
  `delete_master` — all `@transaction.atomic` + `log_action`.
- `forms.py`: `StyledModelForm` base (auto input classes) + a form per master
  + `CsvImportForm`.
- `importers.py`: `import_csv` (validates rows through the master's ModelForm,
  upserts on natural key, fills defaulted/blank columns), `csv_template`.

### Views & URLs (`app_name = "masters"`, mounted at `/masters/`)
- Generic `master_list/master_create/master_update/master_delete/
  master_toggle` keyed by `<slug>`; `MastersHomeView`, `HospitalProfileView`,
  `MasterImportView` (`?template=1` downloads a CSV template).
- Per-master permission checks derived from the spec
  (`masters.view_*|add_*|change_*|delete_*`); toggle is POST-only.

### Templates & tags
- `templates/masters/{home,master_list,master_form,master_confirm_delete,
  import,hospital_profile}.html`.
- `ihms_tags` gained `change_perm`/`delete_perm`/`add_perm` model→codename filters.

### Seed data & roles
- `apps/masters/management/commands/seed_masters.py` — idempotent baseline:
  departments, designations, wards/bed types/beds, drugs, lab/radiology tests,
  procedures, ICD-10 diagnoses, taxes, payment methods, notification templates
  and the hospital profile.
- `seed_roles.py`: `masters` added to Hospital Admin; Doctor gets read access
  to clinical masters.

### Verification (B2)
- `manage.py check` → no issues; `makemigrations/migrate masters` applied
  (`masters.0001_initial`, 14 models).
- `seed_masters` → created 9 depts, 10 designations, 3 wards, 5 bed types,
  19 beds, 10 drugs, 8 lab tests, 5 radiology, 5 procedures, 10 diagnoses,
  4 taxes, 5 payments, 2 notification templates + hospital profile.
- `seed_roles --sync` → 9 refreshed.
- Smoke test (dev/remote DB): `/masters/`, departments, drugs, beds, drug
  new, import, import template, hospital profile → all 200.
- `pytest` → **37 passed** (22 new masters tests + 15 accounts).

### Notes / decisions
- Hospital-level VAT/tax treated as configuration data (`TaxConfig`), not the
  financial `TAX` table from ARCHITECTURE (that arrives with billing).
- Masters are retired via `is_active` (not soft-delete); delete is hard and
  surfaces `ProtectedError` as a friendly message.


## B3 — Patient Core ✅
New app `apps.patients` (label `patients`), mounted at `/patients/`.

### Models
- `Patient(SoftDeleteModel)`: UHID (unique, immutable, `editable=False`),
  EN/BN names, DOB or age (validated), gender, blood group, marital status,
  NID, phone/alt/email, addresses, guardian + emergency contact (Relation)
  choices, patient type (General/VIP/Corporate/Staff), photo, notes, active,
  `registered_by`, `portal_user` stub (Phase 15). Custom permission
  `patients.merge_patient`. Indexes on name/phone.
- `PatientSequence`: per-year row-locked counter for UHID (`DHK-YYYY-NNNNNN`).
- `PatientDocument(TimeStampedModel)`: title/category/file/notes/uploaded_by.

### Services (atomic + audit)
- `generate_uhid()` — `select_for_update` on the year row; `_normalise()` folds
  empty form values back to model defaults so optional fields never spam the
  DB with blanks; register/update/soft_delete/restore/add_document/merge.
- `merge_patients()` moves documents to the primary and archives the duplicate.

### Selectors / forms / views
- `patient_list` (UHID/name/phone/NID search + gender/type filters),
  `find_duplicates` (phone+DOB or exact name), `patient_documents`.
- Addresses/registration/duplicate warning (register-anyway confirm),
  document upload, CSV export, soft-delete/restore (POST).
- URL names match nav: `patients:list`, `patients:create`, detail/update/
  delete/restore, export, merge, document_create/document_delete.

### Templates
- `templates/patients/{patient_list,patient_form,patient_detail,patient_merge}.html`.

### Permissions
- `seed_roles --sync`: Hospital Admin gets all `patients.*`; Receptionist
  view/add/change; Doctor view; Nurse view+change; Accountant/Lab/Pharmacist view.

### Verification (B3)
- `check` clean; `migrate` applied `patients.0001_initial`; `seed_patients`
  created 4 samples through the real service (UHID sequence consistent).
- Smoke (dev/remote DB): list, search, create, detail, edit, export, merge →
  all 200.
- `pytest` → **58 passed** (21 new patient tests + 37 prior).

### Notes / decisions
- Registration is a single sectioned form (fast, <90s) rather than a server
  wizard — the duplicate-warning gate provides the multi-step safety.
- Patients soft-delete (archived); merge is a hard tool gated by a custom
  permission and fully audited.


## B4 — OPD & Appointments ✅
New app `apps.opd` (label `opd`), mounted at `/opd/`.

### Deliverables
- Doctor master (basic): user link, department, EN/BN name, qualification,
  specialization, BMDC no (unique), consultation/follow-up fees,
  revenue-share %, active. (Full HR profile stays in Phase 5.)
- Weekly availability: reusable per-day time **blocks** (`AvailabilitySlot`)
  with a max-patient capacity. Unique per doctor/weekday/start.
- Appointment booking with automatic per-day **token** (row-locked
  `DoctorDailyToken`, like UHID). Duplicate active booking + capacity +
  past-date guards.
- Lifecycle: scheduled → arrived → in_consultation → completed, plus
  no_show and cancel (reason + audit). Reschedule cancels the old booking
  and creates a new one linked via `rescheduled_from`.
- OPD queue board with per-doctor summary and one-tap status actions.
- OPD consultation shell (fee captured; full EMR in Phase 6).

### Notifications (email, not SMS)
- Per instruction, SMS was replaced by **email**. Booking sends a
  confirmation; `send_appointment_reminders` sends 24h + 1h reminders
  (`--dry-run` supported). Uses `DEFAULT_FROM_EMAIL`; default backend is the
  console backend until the operator adds SMTP credentials (Gmail app
  password) in `.env`.

### Services (atomic + audit)
- `book_appointment` (fee snapshot, token, confirmation email),
  `cancel_appointment`, `reschedule_appointment`, `set_status`,
  `send_reminders`. Slot row + token row are `select_for_update`-locked.

### Selectors / forms / views
- `selectors.available_blocks`, `appointment_list`, `queue_for`,
  `today_summary`.
- URLs: `opd:doctor_list|doctor_create|doctor_update|doctor_availability|
  availability_toggle|appointment_list|appointment_book|appointment_detail|
  appointment_cancel|appointment_reschedule|appointment_status|queue`.
- Templates `templates/opd/*` (7 files).

### Permissions
- `seed_roles --sync`: Hospital Admin gets all `opd.*`; Doctor/Nurse view +
  change appointments + view doctors; Receptionist view/add/change
  appointments + view doctors; Accountant view-only.

### Verification (B4)
- `check` clean; `opd.0001_initial` migrated; `seed_doctors` (3 doctors,
  14 weekly blocks each, 3 sample appointments today).
- Smoke (dev/remote DB): 11 OPD URLs → all 200; booking preview shows
  blocks; queue lists 3 rows.
- Reminder command `--dry-run` runs clean.
- `pytest` → **85 passed** (27 new OPD tests + 58 prior).

### Notes / decisions
- Availability is modelled as time **blocks** (capacity-limited) rather than
  fixed per-appointment slots; token order drives the queue. Simple, fast,
  and matches the "per time block" wording in RULES.
- Tokens start at 1 per doctor per day and never reset/renumber on cancel.


## B5 — Doctor & Staff Management ✅
New app `apps.hr` (label `hr`), mounted at `/hr/`. Doctors stay in `opd`
(extended, not duplicated); `hr` covers non-doctor staff and HR workflow.

### Deliverables
- `Shift` templates (name/code unique, start/end, `is_night`, active).
- `Staff` full profile: optional `user` O2O, unique `employee_code`, EN/BN
  name, department/designation FKs, contact, joining date, employment type,
  status, default shift, salary structure (basic/house-rent/medical/
  transport/other + computed `gross_salary`), notes, active.
- `DutyRoster` (staff+date unique, shift PROTECT, publish flag/at/by).
- `Attendance` (staff+date unique) with manual + biometric `source`,
  check-in/out, device id, remarks, computed `worked_hours` (overnight-safe).
- Leave: `LeaveType`, `LeaveRequest` (auto day count), `LeaveBalance`
  (per staff/type/year, `remaining_days`), apply → approve/reject/cancel.
- `opd.Doctor` extended with HR profile fields: `employee_code` (unique,
  nullable), `joining_date`, `signature` (image).

### Services (atomic + audit)
- `upsert_attendance`, `import_attendance_rows` (biometric CSV keyed by
  employee code; returns created/updated/errors), `assign_roster`
  (idempotent), `publish_roster`, `compute_leave_days`, `apply_leave`
  (overlap guard), `approve_leave` (consumes balance), `reject_leave`,
  `cancel_leave` (restores balance when approved).

### Selectors / forms / views
- `selectors.staff_list`, `attendance_list`, `attendance_summary`,
  `leave_list`, `pending_leave_count`, `roster_week`,
  `doctor_performance(year, month)` (completed visits + revenue + share).
- URLs: `hr:staff_list|staff_create|staff_update|staff_detail`,
  `shift_list|shift_create|shift_update`, `roster|roster_generate|
  roster_publish`, `attendance_list|attendance_mark|attendance_edit|
  attendance_import`, `leave_type_list|leave_type_create|leave_list|
  leave_apply|leave_detail|leave_decide|leave_cancel`, `doctor_performance`.
- Templates `templates/hr/*` (15 files). Nav "People" updated to the HR
  routes (Doctors → `opd:doctor_list`).

### Permissions
- `seed_roles --sync`: Hospital Admin gets all `hr.*`; new **HR Manager**
  role (full `hr.*`); Doctor/Nurse view staff + roster; Receptionist/
  Accountant view staff.

### Commands
- `seed_hr` — 4 shifts, 4 leave types, 5 staff (reusing existing
  designations, generating unique codes for new ones), 30 roster entries,
  ~30 attendance rows, 2 leave requests (first auto-approved).

### Verification (B5)
- `check` clean; `hr.0001_initial` + `opd.0002` applied on Supabase;
  `seed_roles --sync` (1 created, 10 refreshed); `seed_hr` populated.
- Smoke (dev/remote DB): 19 HR URLs → all 200.
- `pytest` → **113 passed** (28 new HR tests + 85 prior).

### Notes / decisions
- Attendance "biometric" is a CSV import (testable stand-in for a device).
- Leave balance is auto-created on first approval with entitlement from
  `LeaveType.max_days_per_year`.
- Fixed a pre-existing flaky OPD reminder test (`test_1h_reminder_within_
  window`) by freezing time; it failed only when run near midnight because
  `now + 2h` wraps and the booking guard rejected the same-day block.

## B6 — EMR & CPOE (Clinical Core) ✅

New app `apps.emr` (label `emr`), mounted at `/emr/`. Depends on Phase 4
(OPD) and Phase 5 (Doctors); unblocks Lab, Pharmacy, IPD, Billing, ICU, OT.

### Deliverables (models, `apps/emr/models.py`)
- `Encounter` (SoftDelete) — visit aggregate: patient/doctor PROTECT,
  optional `appointment` (SET_NULL) with a conditional **unique-per-
  appointment** constraint, `encounter_date`, `encounter_type`
  (outpatient/followup/emergency/inpatient), `chief_complaint`, `status`
  (open/closed), `closed_at`, `created_by`.
- `SoapNote` (O2O encounter) — subjective/objective/assessment/plan +
  optional `template` + `authored_by`.
- `SoapTemplate` — pre-built SOAP note starters (name unique, active).
- `VisitDiagnosis` — per-encounter diagnosis (coded FK or free text,
  unique primary enforced in service).
- `Vital` — temp/pulse/RR/BP/spO₂/height/weight/pain, `bmi` & `bp_display`
  computed; denormalised `patient` for fast longitudinal queries.
- `ProblemListEntry` — patient-level problem list (`is_active`,
  `resolved_date`, `is_resolved`).
- `Allergy` — patient-level register (drug/food/other, severity).
- `Prescription` (SoftDelete) + `PrescriptionItem` (drug/dose/route/
  frequency/duration/qty/PRN/instructions).
- `LabOrder`+`LabOrderItem`, `RadiologyOrder`+`RadiologyOrderItem`,
  `ProcedureOrder` — CPOE orders (status/priority, soft-delete).
- `ClinicalAttachment` (SoftDelete) — uploaded files (image/report/other).
- `DrugInteractionRule` — basic pairwise interaction rules engine
  (severity, active, `matches()`, unique pair, no self-interaction).

### Services (atomic + audit, `apps/emr/services.py`)
- `open_encounter` (idempotent per appointment), `close_encounter`,
  `save_soap_note` (upsert), `record_vitals`, `add_visit_diagnosis`
  (exclusive primary), `remove_visit_diagnosis`, `add_problem`,
  `resolve_problem`, `add_allergy`, `add_attachment`, `remove_attachment`.
- CPOE: `issue_prescription` (returns `(rx, interactions)`),
  `cancel_prescription`, `create_lab_order`, `create_radiology_order`,
  `create_procedure_order`, `set_order_status`.
- **Rules engine:** `check_drug_interactions(drug_ids)` → active rules whose
  both drugs are present; interaction alerts are advisory (logged + surfaced
  as a warning) but the prescription is still issued.

### Selectors / forms / views
- `selectors`: `encounter_list`, `patient_encounters`, `active_problems`,
  `patient_allergies`, `latest_vitals`, `encounter_orders` (grouped CPOE),
  `prescription_list`, `attachments_for`, `patient_timeline` (merged reverse-
  chronological EMR events), `encounter_summary`.
- `forms`: encounter open/filter, SOAP, vital, visit dx, problem, allergy,
  prescription + `PrescriptionItemFormSet` (dynamic "add row"), lab/radiology
  order (checkbox test selection), procedure order, order status, attachment,
  SOAP template, prescription filter.
- Views (`app_name = "emr"`): `encounter_list|encounter_open|encounter_detail|
  encounter_close|soap_save|vital_create|diagnosis_create|diagnosis_delete`,
  `patient_timeline|problem_list|problem_resolve|allergy_list`,
  `prescription_create|prescription_list|prescription_detail|
  prescription_cancel|prescription_print|prescription_pdf`,
  `lab_order_create|radiology_order_create|procedure_order_create|
  order_status`, `attachment_list|attachment_remove`,
  `soap_template_list|soap_template_create`. Root `/emr/` redirects to
  `/emr/encounters/`.
- `order_status` resolves per-kind change permission via
  `get_permission_required()` (lab/radiology/procedure).
- Closed encounters refuse new CPOE orders (prescription/lab/radiology/
  procedure) — redirect back to the detail view.
- **OPD lifecycle hook**: opening an encounter from an appointment advances it
  along the OPD transition chain (scheduled → arrived → in_consultation);
  closing the encounter best-effort completes the appointment.
- **Prescription PDF**: `prescription_print` renders a print/A4 HTML;
  `prescription_pdf` uses WeasyPrint (`base_url=request.build_absolute_uri`)
  and includes the doctor's signature image (`opd.Doctor.signature`).

### Templates (`templates/emr/*`, 16 files)
Encounter list/open/workspace (SOAP + dx + vitals + CPOE order panels +
sidebar problems/allergies), patient timeline (events link to their source
encounter/prescription/order), problem list, allergy register, prescription
list/form/detail/print, generic order form, `_order_row` & `_prescription_row`
partials, attachment list, SOAP template list/form.

### Permissions (`seed_roles --sync`)
- Hospital Admin gets all `emr.*`. **Doctor**: full clinical set (encounter/
  SOAP/vitals/dx/problem/allergy/prescription all orders/attachments/SOAP
  templates). **Nurse**: view encounter/SOAP/vitals+add, view dx/problems/
  allergies/all orders/prescriptions, add allergy/attachment. **Receptionist**:
  view+add encounter. **Lab Technician**: view+change lab & radiology orders.
  **Pharmacist**: view prescriptions.

### Commands / integration
- `seed_emr` — 4 SOAP templates + 2 drug-interaction rules (created only when
  both drugs exist; run after `seed_masters`).
- OPD `appointment_detail.html`: "Open encounter" / "EMR timeline" actions
  replace the old EMR placeholder.
- Nav gains an "EMR & CPOE" section (Encounters, Open Encounter,
  Prescriptions, SOAP Templates).

### Verification (B6)
- `check` clean; `emr.0001_initial` applied on Supabase.
- `seed_emr` (4 templates, 2 rules); `seed_roles --sync`.
- Smoke (dev/remote DB): 14 EMR URLs → all 200, `/admin/` 200.
- `pytest` → **147 passed** (34 new EMR tests + 113 prior).

### Notes / decisions
- Interaction alerts are non-blocking (clinician override expected); the
  alert is recorded in the audit trail on the prescription.
- Drug-interaction matching is FK-based with a single ordered pair; the seeded
  rules use `generic_name` lookups so they only appear when drugs exist.
- Orders (incl. priority/status) reuse the model enums (`OrderPriority`,
  `OrderStatus`) instead of hardcoded form choices.
- Encounter open/close keeps the OPD appointment status in sync
  (→ in_consultation / → completed) best-effort; the linear OPD transition
  chain is respected by arriving a still-scheduled appointment first.
- Routed interaction engine + CPOE now feed Lab/Pharmacy/IPD in later phases.


## B7 — IPD, Admission & Bed Management ✅

New app `apps.ipd` (label `ipd`), mounted at `/ipd/`. Depends on Phase 6 (EMR);
unblocks ICU (P8), OT (P9) and Billing (P12). IP numbers are `IP-YYYY-NNNNN`.

### Deliverables (models, `apps/ipd/models.py`)
- `Ward` (ward_type general/cabin/icu/ccu/hdu, floor, active), `Bed`
  (`bed_no`, `bed_type`, `daily_rate` Decimal(12,2), status
  available/occupied/maintenance; **unique `(ward, bed_no)`**).
- `AdmissionSequence` — per-year counter for IP numbers.
- `Admission` (SoftDelete) — `ip_number` (unique, null while only *requested*),
  patient/doctor PROTECT, optional `encounter` SET_NULL, `bed` SET_NULL,
  `admission_type`, `status` (requested/admitted/discharge_requested/
  discharged/cancelled, default requested), `reason`, `admission_note`,
  `admitted_at`/`discharged_at`, `discharge_reason`, `created_by`; computed
  `is_active_admission`, `current_ward`, `length_of_stay_days`,
  `has_pending_clearances`, `pending_clearance_departments`.
  **Two partial unique constraints** are the DB-level double-booking guard:
  `uniq_bed_active_admission` (bed not null & status not discharged/cancelled)
  and `uniq_patient_active_admission`.
- `BedTransfer` — logs bed *and* ward moves: `from_bed`/`to_bed`, denormalised
  `from_ward`/`to_ward` snapshots, `reason`, `transferred_at/by`.
- `DailyCharge` + `ChargeStatus` (accrued/posted) — `bed_charge` +
  `nursing_charge` + `doctor_visit_charge`, `total` property, unique
  `(admission, charge_date)`.
- `NursingNote` (shift-wise), `MedicationAdministration` (MAR: drug/dose/route/
  action given/omitted/refused, `scheduled_for`/`given_at`/`given_by`, optional
  `prescription_item`), `IntakeOutput` (fluid_type/category/volume/shift).
- `DischargeClearance` (department lab/pharmacy/billing/inventory, `is_cleared`,
  `cleared_by/at`; unique `(admission, department)`).
- `DischargeSummary` (O2O admission) — `discharge_type` routine/lama/death/
  transfer_out, diagnosis/treatment/follow-up/advice, `generated_by`.

### Services (atomic + audit, `apps/ipd/services.py`)
- `generate_ip_number` — row-locked per-year `AdmissionSequence`
  (`IP_PREFIX`/`IP_NUMBER_WIDTH` from `settings.IHMS`, width default 5).
- `request_admission` (rejects a second active admission for the patient),
  `allocate_bed` (row-lock, bed must be AVAILABLE, mints IP, sets bed OCCUPIED,
  status→admitted), `transfer_bed` (row-lock target, frees old bed, logs
  `BedTransfer`), `mark_discharge_request`, `set_clearance` (update_or_create).
- `discharge` — **blocked (`ValueError`) until Lab+Pharmacy+Billing clearances
  are cleared**; creates `DischargeSummary`, frees the bed, status→discharged.
- `accrue_daily_charges` — idempotent per `(admission, charge_date)`; rates from
  `settings.IHMS` (`IP_DAILY_NURSING_RATE` 300, `IP_DAILY_DOCTOR_VISIT_RATE`
  500) plus the bed's `daily_rate`.
- Care: `record_nursing_note`, `record_mar`, `record_intake_output`.

### Selectors / forms / views
- `selectors`: `admission_list`, `patient_admissions`, `ward_bed_map` (renders
  structured ward/bed dicts incl. occupant + CSS/dot), `bed_status_counts`,
  `bed_kpis`, `occupancy_kpis`, `charge_summary`, `recent_transfers`.
- `forms`: `AdmissionForm`, `BedAllocateForm` (available beds only),
  `BedTransferForm`, `AdmissionFilterForm`, `WardTypeFilterForm`,
  `DischargeRequestForm`, `ClearanceForm`, `DischargeSummaryForm`,
  `NursingNoteForm`, `MarForm`, `IntakeOutputForm` (local `StyledFormMixin`).
- Views (`app_name = "ipd"`): `admission_list|admission_create|admission_detail|
  admission_allocate|admission_transfer`, `discharge_request|
  discharge_clearance|discharge|discharge_summary|discharge_summary_pdf`,
  `bed_map|nursing_note_create|mar_create|intake_output_create`. Root `/ipd/`
  redirects to `/ipd/admissions/`.
- **Discharge summary PDF**: WeasyPrint standalone A4 template with hospital
  branding (`HospitalProfile.load()`) + doctor signature; HTML view doubles as
  the print page.

### Templates (`templates/ipd/*`, 5 files)
`admission_list`, `admission_create`, `admission_detail` (admission info,
charges, clearances, transfers, nursing notes, MAR, intake/output, bed &
discharge panels), `bed_map` (ward grid with status dots/occupancy KPIs),
`discharge_summary` (print/PDF).

### Permissions (`seed_roles --sync`)
- Hospital Admin gets all `ipd.*`. **Doctor**: view/add/change admission,
  transfer, view ward/bed/charges, view/add discharge summary. **Nurse**:
  same as Doctor plus clearance change, nursing note/MAR/intake-output add.
  **Receptionist**: view admission. **Accountant**: view admission/charges/
  discharge summary.

### Commands / integration
- `seed_ipd` — 5 wards (General 10, Cabin 6, ICU 4, CCU 3, HDU 3) = **26 beds**
  with rates; idempotent via `(ward, bed_no)`.
- Nav "Clinical" section already lists IPD / Admissions + Bed Map (`ipd:*`).
- IPD reuses `apps.masters.Drug`, `apps.emr.Route`, `apps.opd.Doctor`.

### Verification (B7)
- `check` clean; `ipd.0001_initial` applied on Supabase.
- `seed_ipd` (5 wards, 26 beds); `seed_roles --sync` (10 roles refreshed).
- Smoke (dev/remote DB): 19/19 checks — 3 list/form/bed-map GETs 200; full
  lifecycle create→allocate(`IP-2026-00001`)→notes/MAR/IO→discharge request→
  3 clearances→discharge→summary 200 + **PDF application/pdf**.
- `pytest` → **178 passed** (31 new IPD tests + 147 prior).

### Notes / decisions
- Clearance departments required for discharge: **lab, pharmacy, billing**;
  `inventory` exists in the enum but is deferred to Phase 11.
- Bed allocation is guarded twice: service-level row lock + bed status, and
  DB-level partial unique constraints (defence in depth).
- `BedTransfer` covers both bed and ward movement; ward names are snapshotted so
  the history survives ward renames.
- Day charges are idempotent per admission+date; a management/command or cron
  can call `accrue_daily_charges()` nightly.
- **Gotcha**: under Django 5 + SQLite, `Model.objects.create()` returns the
  instance with `str` values for `DecimalField`s (INSERT … RETURNING path),
  while re-fetching via a SELECT returns `Decimal`. `DailyCharge.total` coerces
  with `Decimal(str(v))` to stay correct in both cases (see MISTAKES M-015).


