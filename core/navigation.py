"""Sidebar navigation definition.

Routes are referenced by URL name. Items whose route is not yet implemented
resolve to ``#`` via the ``nav_url`` template tag, so the shell never crashes
while the project is being built up phase by phase.
"""

from __future__ import annotations

NAV_SECTIONS: list[dict] = [
    {
        "label": "Control Tower",
        "icon": "layout-dashboard",
        "items": [
            {"label": "Dashboard", "url": "panel:home", "icon": "layout-dashboard"},
            {"label": "Analytics", "url": "reports:dashboard", "icon": "bar-chart-3"},
        ],
    },
    {
        "label": "Front Desk",
        "icon": "users",
        "items": [
            {"label": "Patients", "url": "patients:list", "icon": "users"},
            {"label": "Registration", "url": "patients:create", "icon": "user-plus"},
            {
                "label": "Appointments",
                "url": "opd:appointment_list",
                "icon": "calendar-check",
            },
            {
                "label": "Book Appointment",
                "url": "opd:appointment_book",
                "icon": "calendar-plus",
            },
            {"label": "OPD Queue", "url": "opd:queue", "icon": "list-ordered"},
            {"label": "Doctors", "url": "opd:doctor_list", "icon": "stethoscope"},
        ],
    },
    {
        "label": "Clinical",
        "icon": "stethoscope",
        "items": [
            {
                "label": "IPD / Admissions",
                "url": "ipd:admission_list",
                "icon": "bed-double",
            },
            {"label": "Bed Map", "url": "ipd:bed_map", "icon": "layout-grid"},
            {"label": "Emergency", "url": "icu:emergency_list", "icon": "siren"},
            {"label": "ICU / CCU", "url": "icu:record_list", "icon": "activity"},
            {
                "label": "Operation Theatre",
                "url": "ot:surgery_list",
                "icon": "scissors",
            },
            {"label": "Discharge", "url": "ipd:discharge_list", "icon": "log-out"},
        ],
    },
    {
        "label": "EMR & CPOE",
        "icon": "clipboard-list",
        "items": [
            {
                "label": "Encounters",
                "url": "emr:encounter_list",
                "icon": "clipboard-list",
            },
            {
                "label": "Open Encounter",
                "url": "emr:encounter_open",
                "icon": "plus",
            },
            {
                "label": "Prescriptions",
                "url": "emr:prescription_list",
                "icon": "pill",
            },
            {
                "label": "SOAP Templates",
                "url": "emr:soap_template_list",
                "icon": "file-text",
            },
        ],
    },
    {
        "label": "Diagnostics",
        "icon": "flask-conical",
        "items": [
            {"label": "Lab Orders", "url": "lab:order_list", "icon": "flask-conical"},
            {"label": "Samples", "url": "lab:sample_list", "icon": "barcode"},
            {"label": "Results", "url": "lab:result_list", "icon": "clipboard-check"},
            {"label": "Radiology", "url": "lab:radiology_list", "icon": "scan"},
        ],
    },
    {
        "label": "Pharmacy & Store",
        "icon": "pill",
        "items": [
            {"label": "Dispense", "url": "pharmacy:dispense", "icon": "pill"},
            {"label": "Stock", "url": "pharmacy:stock_list", "icon": "package"},
            {
                "label": "Expiry Alerts",
                "url": "pharmacy:expiry_alerts",
                "icon": "alert-triangle",
            },
            {
                "label": "Purchase Orders",
                "url": "pharmacy:po_list",
                "icon": "shopping-cart",
            },
            {"label": "GRN", "url": "pharmacy:grn_list", "icon": "truck"},
            {"label": "Vendors", "url": "pharmacy:vendor_list", "icon": "building-2"},
        ],
    },
    {
        "label": "Finance",
        "icon": "wallet",
        "items": [
            {"label": "Billing", "url": "billing:bill_list", "icon": "receipt"},
            {"label": "Payments", "url": "billing:payment_list", "icon": "banknote"},
            {"label": "Accounts", "url": "accounting:ledger", "icon": "book-open"},
            {
                "label": "Trial Balance",
                "url": "accounting:trial_balance",
                "icon": "scale",
            },
            {"label": "Payroll", "url": "payroll:run_list", "icon": "wallet-cards"},
        ],
    },
    {
        "label": "People",
        "icon": "user-cog",
        "items": [
            {"label": "Doctors", "url": "opd:doctor_list", "icon": "stethoscope"},
            {"label": "Staff", "url": "hr:staff_list", "icon": "id-card"},
            {"label": "Shifts", "url": "hr:shift_list", "icon": "clock"},
            {"label": "Roster", "url": "hr:roster", "icon": "calendar-range"},
            {"label": "Attendance", "url": "hr:attendance_list", "icon": "fingerprint"},
            {"label": "Leave", "url": "hr:leave_list", "icon": "plane"},
            {
                "label": "Doctor Performance",
                "url": "hr:doctor_performance",
                "icon": "trending-up",
            },
        ],
    },
    {
        "label": "Administration",
        "icon": "settings",
        "items": [
            {"label": "Users", "url": "accounts:user_list", "icon": "users-round"},
            {
                "label": "Roles & Permissions",
                "url": "accounts:role_list",
                "icon": "shield-check",
            },
            {"label": "Master Data", "url": "masters:home", "icon": "database"},
            {"label": "Audit Log", "url": "accounts:audit_log", "icon": "history"},
            {
                "label": "Settings",
                "url": "masters:hospital_profile",
                "icon": "settings-2",
            },
        ],
    },
]
