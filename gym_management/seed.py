"""Sample data.   bench --site <site> execute gym_management.seed.run

Idempotent: running it twice does not duplicate anything. Needs a completed ERPNext setup
(a Company). Pass create_invoices=0 if the chart of accounts is not ready.
"""
import frappe
from frappe.utils import add_days, today

from gym_management.tests.factories import default_company

SPECIALTIES = ["Yoga", "Strength", "Cardio"]
PLANS = [  # name, type, value, price, classes_included, max_freeze_days
    ("Monthly", "Months", 1, 500, 0, 7),
    ("Quarterly", "Months", 3, 1350, 0, 14),
    ("Annual", "Months", 12, 4800, 0, 30),
    ("10-Class Pack", "Class Pack", 10, 700, 0, 0),
]
ROOMS = [("Studio A", 20), ("Studio B", 12), ("Spin Room", 15)]
TRAINERS = [("Sara Hassan", ["Yoga"]), ("Omar Khaled", ["Strength", "Cardio"])]
CLASSES = [  # name, category, trainer idx, room, minutes, capacity
    ("Morning Yoga", "Yoga", 0, "Studio A", 60, 15),
    ("HIIT Blast", "HIIT", 1, "Studio B", 45, 10),
    ("Spin 45", "Spin", 1, "Spin Room", 45, 12),
]
MEMBERS = ["Ahmed Ali", "Mona Samir", "Youssef Adel", "Nour Ibrahim", "Laila Mostafa", "Karim Fathy"]


def run(create_invoices=1):
    company = default_company()
    if not company:
        frappe.throw("No Company found. Complete the ERPNext setup wizard first.")
    frappe.flags.gym_skip_invoice = not int(create_invoices)

    for s in SPECIALTIES:
        _ensure("Gym Specialty", {"specialty_name": s})
    for name, t, v, price, inc, freeze in PLANS:
        _ensure("Membership Plan", {"plan_name": name, "duration_type": t, "duration_value": v, "price": price,
                                    "classes_included": inc, "max_freeze_days": freeze, "is_active": 1})
    for name, cap in ROOMS:
        _ensure("Gym Room", {"room_name": name, "capacity": cap, "is_active": 1})

    trainers = []
    for full_name, specs in TRAINERS:
        emp = frappe.db.get_value("Employee", {"employee_name": full_name, "company": company})
        if not emp:
            first, last = full_name.split(" ", 1)
            emp = frappe.get_doc({"doctype": "Employee", "first_name": first, "last_name": last, "gender": "Male",
                                  "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-01", "company": company,
                                  "status": "Active"}).insert(ignore_permissions=True).name
        t = frappe.db.get_value("Gym Trainer", {"employee": emp}) or frappe.get_doc({
            "doctype": "Gym Trainer", "employee": emp, "is_active": 1,
            "specialties": [{"specialty": s} for s in specs]}).insert(ignore_permissions=True).name
        trainers.append(t)

    classes = []
    for name, cat, ti, room, minutes, cap in CLASSES:
        classes.append(_ensure("Gym Class", {"class_name": name, "category": cat, "default_trainer": trainers[ti],
                                             "default_room": room, "duration_minutes": minutes, "default_capacity": cap}))

    members = [_ensure("Gym Member", {"member_name": n, "email": n.split()[0].lower() + "@example.com", "phone": "0100000%04d" % i,
                                      "joined_on": today()}, key="member_name") for i, n in enumerate(MEMBERS)]

    # first four members buy plans; the rest stay prospects
    for member, plan in zip(members[:4], ["Monthly", "Quarterly", "Annual", "10-Class Pack"]):
        if not frappe.db.exists("Gym Membership", {"member": member, "docstatus": 1}):
            doc = frappe.get_doc({"doctype": "Gym Membership", "member": member, "membership_plan": plan,
                                  "company": company, "start_date": today()}).insert(ignore_permissions=True)
            doc.submit()

    # a week of sessions at 07:00 / 18:00 / 19:30 (only future ones)
    for day in range(0, 7):
        for cls, start in zip(classes, ["07:00:00", "18:00:00", "19:30:00"]):
            exists = frappe.db.exists("Class Session", {"gym_class": cls, "session_date": add_days(today(), day), "start_time": start})
            if exists:
                continue
            try:
                frappe.get_doc({"doctype": "Class Session", "gym_class": cls, "session_date": add_days(today(), day),
                                "start_time": start}).insert(ignore_permissions=True)
            except frappe.ValidationError:
                pass  # e.g. time already passed today
    frappe.db.commit()
    print("Gym Management sample data ready.")


def _ensure(doctype, values, key=None):
    key = key or {"Gym Specialty": "specialty_name", "Membership Plan": "plan_name", "Gym Room": "room_name",
                  "Gym Class": "class_name"}.get(doctype)
    existing = frappe.db.get_value(doctype, {key: values[key]})
    if existing:
        return existing
    return frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True).name
