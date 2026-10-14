"""Whitelisted API for personal-training bookings. Documents are created / saved with the caller's own
permissions (never ignore_permissions)."""
import frappe
from frappe import _
from frappe.utils import cint, getdate

from gym_management import personal_training as pt


@frappe.whitelist()
def get_trainer_slots(trainer, session_date, duration_minutes=pt.DEFAULT_DURATION):
    """Free start times (HH:MM:SS) for ``trainer`` on ``session_date``."""
    frappe.has_permission("Personal Training Session", "read", throw=True)
    duration = cint(duration_minutes) or pt.DEFAULT_DURATION
    if not pt.MIN_DURATION <= duration <= pt.MAX_DURATION:
        frappe.throw(_("Duration must be between {0} and {1} minutes.").format(pt.MIN_DURATION, pt.MAX_DURATION))
    return {
        "trainer": trainer, "date": str(getdate(session_date)), "duration_minutes": duration,
        "slots": pt.get_free_slots(trainer, session_date, duration),
    }


@frappe.whitelist(methods=["POST"])
def book_personal_training(member, trainer, session_date, start_time, duration_minutes=pt.DEFAULT_DURATION):
    doc = frappe.get_doc({
        "doctype": "Personal Training Session", "member": member, "trainer": trainer,
        "session_date": session_date, "start_time": start_time, "duration_minutes": duration_minutes,
    })
    doc.insert()
    return {"session": doc.name, "status": doc.status, "starts_on": str(doc.starts_on), "ends_on": str(doc.ends_on)}


@frappe.whitelist(methods=["POST"])
def cancel_personal_training(session):
    doc = frappe.get_doc("Personal Training Session", session)
    doc.status = "Cancelled"
    doc.save()
    return {"session": doc.name, "status": doc.status, "late_cancellation": cint(doc.late_cancellation)}
