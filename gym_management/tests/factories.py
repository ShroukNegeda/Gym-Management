"""Small factories used by the tests and the seed script."""
import frappe
from frappe.utils import add_days, today


def uid(prefix=""):
    return f"{prefix}{frappe.generate_hash(length=6)}"


def default_company():
    return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")


def make_member(name=None, **kw):
    doc = frappe.get_doc({"doctype": "Gym Member", "member_name": name or uid("Member "), "phone": "01000000000",
                          "email": f"{uid('m')}@example.com", **kw})
    return doc.insert(ignore_permissions=True)


def make_plan(plan_name=None, duration_type="Months", duration_value=1, price=100, classes_included=0, max_freeze_days=14, **kw):
    return frappe.get_doc({
        "doctype": "Membership Plan", "plan_name": plan_name or uid("Plan "), "duration_type": duration_type,
        "duration_value": duration_value, "price": price, "classes_included": classes_included,
        "max_freeze_days": max_freeze_days, "is_active": 1, **kw,
    }).insert(ignore_permissions=True)


def make_employee(name=None):
    company = default_company()
    first = name or uid("Trainer ")
    return frappe.get_doc({
        "doctype": "Employee", "first_name": first, "gender": "Male", "date_of_birth": "1990-01-01",
        "date_of_joining": "2020-01-01", "company": company, "status": "Active",
    }).insert(ignore_permissions=True)


def make_trainer():
    return frappe.get_doc({"doctype": "Gym Trainer", "employee": make_employee().name, "is_active": 1}).insert(ignore_permissions=True)


def make_room(capacity=10, name=None):
    return frappe.get_doc({"doctype": "Gym Room", "room_name": name or uid("Room "), "capacity": capacity, "is_active": 1}).insert(ignore_permissions=True)


def make_class(trainer=None, room=None, capacity=None, duration=60, name=None):
    return frappe.get_doc({
        "doctype": "Gym Class", "class_name": name or uid("Class "), "category": "Yoga",
        "default_trainer": trainer, "default_room": room, "duration_minutes": duration, "default_capacity": capacity,
    }).insert(ignore_permissions=True)


import random

def make_session(gym_class, trainer=None, room=None, capacity=None, days_ahead=1, start_time=None):
    cls = frappe.get_doc("Gym Class", gym_class)

    if not trainer:
        trainer = cls.default_trainer or make_trainer().name
    if not room:
        room = cls.default_room or make_room().name
    if capacity is None:
        capacity = cls.default_capacity

    if not start_time:
        import random
        start_time = f"{random.randint(8, 20):02d}:{random.randint(0, 59):02d}:00"

    return frappe.get_doc({
        "doctype": "Class Session",
        "gym_class": gym_class,
        "trainer": trainer,
        "room": room,
        "capacity": capacity,
        "session_date": add_days(today(), days_ahead),
        "start_time": start_time,
    }).insert(ignore_permissions=True)



def make_membership(member, plan, start_date=None, submit=True, **kw):
    doc = frappe.get_doc({
        "doctype": "Gym Membership", "member": member, "membership_plan": plan,
        "company": default_company(), "start_date": start_date or today(), **kw,
    }).insert(ignore_permissions=True)
    if submit:
        doc.submit()
    return doc
