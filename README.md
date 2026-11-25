# IHMS — Integrated Hospital Management System

An on-premise, Django-based Hospital Management System for a Bangladesh-based
hospital. It covers the full patient journey — registration, OPD, EMR/CPOE,
IPD, ICU/ER, OT, laboratory, pharmacy, billing, accounting, payroll, a patient
portal, and analytics.

The build order and acceptance criteria for every module live in
[`docs/RULES.md`](docs/RULES.md); architecture diagrams are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the product requirements are in
[`docs/PRD.md`](docs/PRD.md).

## Feature modules

| Phase | App | Purpose |
| :-- | :-- | :-- |
| 0  | `core` | Base models, audit trail, exceptions, middleware, navigation |
| 1  | `apps.accounts`, `apps.adminpanel` | Custom user, RBAC, control-tower shell |
| 2  | `apps.masters` | Reference/master data (departments, drugs, tests, beds, …) |
| 3  | `apps.patients` | Patient core, UHID, documents, merge |
| 4  | `apps.opd` | Doctors, availability, appointments, queue |
| 5  | `apps.hr` | Staff, shifts, roster, attendance, leave, performance |
| 6  | `apps.emr` | SOAP notes, vitals, CPOE, allergies, drug interactions |
| 7  | `apps.ipd` | Admissions, beds, MAR, intake/output, discharge |
| 8  | `apps.icu` | ICU charting, critical alerts, ER triage, code blue |
| 9  | `apps.ot` | OT rooms, surgery scheduling, checklists, implants |
| 10 | `apps.lab` | Lab/radiology orders, samples, results, reports |
| 11 | `apps.pharmacy` | Stock, dispensing, PR/PO/GRN, transfers, returns |
| 12 | `apps.billing` | Patient ledger, invoices, payments, refunds |
| 13 | `apps.accounting` | Chart of accounts, GL, trial balance, P&L |
| 14 | `apps.payroll` | Salary structures, tax slabs, runs, payslips, BEFTN |
| 15 | `apps.portal` | Patient self-service portal |
| 16 | `apps.reports` | Dashboards, reports, exports, scheduled emails |

## Requirements

- Python 3.12+
- PostgreSQL (Supabase) — or the bundled SQLite test settings
- Redis (optional; Celery runs eagerly without it)

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure the environment
cp .env.example .env        # then edit .env with your values

# 4. Apply migrations and seed initial data
python manage.py migrate
python manage.py seed_roles
python manage.py seed_superadmin
python manage.py seed_masters      # optional demo/master data

# 5. Run the development server
python manage.py runserver
```

The custom admin panel is served at `/admin/`; the Django stock admin at
`/django-admin/`. Health check: `/health/`.

## Testing & quality

```bash
pytest                     # full suite
ruff check .               # lint
black --check .            # formatting
bandit -r apps core        # security scan
```

## Project layout

```
config/            Django project (settings split: base/dev/test/staging/prod)
core/              Shared base models, audit, middleware, navigation, utils
apps/              Feature apps (one per phase, see table above)
templates/         Server-rendered templates (Tailwind design system)
static/            Source static assets
docs/              PRD, architecture, design, rules, memory, mistakes
```

## License

Proprietary — internal project.
