"""Shared helpers: membership resolution, locking reads, class credits, notifications.

Concurrency note (see DECISIONS.md R4): every read that decides capacity / credits uses
``SELECT ... FOR UPDATE``. A plain SELECT inside a REPEATABLE READ transaction may see a
stale snapshot and miss a booking committed by another request a moment earlier.
"""
import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, getdate, today

MANAGER = "Gym Manager"
FRONT_DESK = "Front Desk"
TRAINER = "Trainer"
STAFF_ROLES = {MANAGER, FRONT_DESK, "System Manager"}

# bookings that occupy a spot in a session
OCCUPYING = ("Booked", "Attended", "No Show")


def get_settings():
    return frappe.get_single("Gym Settings")


# ------------------------------------------------------------------ dates
def compute_base_end_date(start_date, duration_type, duration_value, validity_days=None):
    """Inclusive end date, before any freeze days are added."""
    start = getdate(start_date)
    value = cint(duration_value)
    if duration_type == "Days":
        return add_days(start, value - 1)
    if duration_type == "Months":
        return add_days(add_months(start, value), -1)
    return add_days(start, cint(validity_days or 90) - 1)  # Class Pack


# ------------------------------------------------------------------ members
def ensure_member_allowed(member):
    status = frappe.db.get_value("Gym Member", member, "status")
    if status == "Blacklisted":
        frappe.throw(_("Gym Member {0} is blacklisted.").format(frappe.bold(member)), title=_("Not allowed"))


def resolve_membership(member, on_date=None):
    """Work out which membership (if any) lets ``member`` in on ``on_date``.

    Returns a dict:
      code        ok | frozen | expired | cancelled | not_started | none
      membership  name of the usable membership (only when code == ok)
      current     name of the membership that represents the member right now (ok or frozen)
      message     human readable explanation when not ok
    Dates drive the result (not the stored status) so it is correct for future session
    dates and does not depend on the scheduler having run.
    """
    on_date = getdate(on_date or today())
    member_label = frappe.db.get_value("Gym Member", member, "member_name") or member
    result = frappe._dict(
        code="none", membership=None, current=None,
        message=_("{0} has no membership.").format(member_label),
    )
    rows = frappe.get_all(
        "Gym Membership",
        filters={"member": member, "docstatus": ["in", [1, 2]]},
        fields=["name", "start_date", "end_date", "docstatus"],
        order_by="end_date desc, creation desc",
    )
    if not rows:
        return result

    freezes = {}
    live = [r.name for r in rows if r.docstatus == 1]
    if live:
        for f in frappe.get_all(
            "Membership Freeze",
            filters={"parent": ["in", live], "parenttype": "Gym Membership"},
            fields=["parent", "freeze_from", "freeze_to"],
        ):
            freezes.setdefault(f.parent, []).append(f)

    problem = None
    for r in rows:
        if r.docstatus == 2:
            p = ("cancelled", _("Membership {0} is cancelled.").format(r.name))
        elif on_date < getdate(r.start_date):
            p = ("not_started", _("Membership {0} starts on {1}.").format(r.name, frappe.format(r.start_date, "Date")))
        elif on_date > getdate(r.end_date):
            p = ("expired", _("Membership {0} expired on {1}.").format(r.name, frappe.format(r.end_date, "Date")))
        elif any(getdate(f.freeze_from) <= on_date <= getdate(f.freeze_to) for f in freezes.get(r.name, [])):
            fr = next(f for f in freezes[r.name] if getdate(f.freeze_from) <= on_date <= getdate(f.freeze_to))
            p = ("frozen", _("Membership {0} is frozen until {1}.").format(r.name, frappe.format(fr.freeze_to, "Date")))
            result.current = result.current or r.name
        else:
            return frappe._dict(code="ok", membership=r.name, current=r.name, message="")
        # a frozen membership is the most useful thing to report to the front desk
        problem = p if p[0] == "frozen" else (problem or p)
    result.code, result.message = problem
    return result


def refresh_member(member):
    """Keep Gym Member.active_membership / status in step with the memberships."""
    res = resolve_membership(member, today())
    current_status = frappe.db.get_value("Gym Member", member, "status")
    updates = {"active_membership": res.current}
    if current_status != "Blacklisted":
        if res.code in ("ok", "frozen"):
            updates["status"] = "Active"
        elif current_status == "Active" or (current_status == "Prospect" and res.code in ("expired", "cancelled")):
            updates["status"] = "Inactive"
    frappe.db.set_value("Gym Member", member, updates, update_modified=False)


# ------------------------------------------------------------------ locking reads
def lock_session(name):
    rows = frappe.db.sql(
        """select name, capacity, booked_count, status, session_date, starts_on
           from `tabClass Session` where name=%s for update""",
        name, as_dict=True,
    )
    if not rows:
        frappe.throw(_("Class Session {0} not found.").format(name))
    return rows[0]


def lock_membership(name):
    rows = frappe.db.sql(
        """select name, classes_total, classes_remaining
           from `tabGym Membership` where name=%s for update""",
        name, as_dict=True,
    )
    if not rows:
        frappe.throw(_("Gym Membership {0} not found.").format(name))
    return rows[0]


def adjust_session_counter(name, delta):
    frappe.db.sql(
        "update `tabClass Session` set booked_count = greatest(booked_count + %s, 0) where name=%s",
        (delta, name),
    )
    row = frappe.db.get_value("Class Session", name, ["capacity", "booked_count"], as_dict=True)
    # live "remaining spots" on open Class Booking forms
    frappe.publish_realtime("gym_session_update", {"name": name, **row}, after_commit=True)


# ------------------------------------------------------------------ class credits
def consume_credit(membership):
    m = lock_membership(membership)
    if not cint(m.classes_total):
        return  # unlimited
    if cint(m.classes_remaining) <= 0:
        frappe.throw(_("No classes remaining on membership {0}.").format(membership), title=_("No class credits"))
    frappe.db.set_value("Gym Membership", membership, "classes_remaining", cint(m.classes_remaining) - 1, update_modified=False)


def release_credit(membership):
    m = lock_membership(membership)
    if not cint(m.classes_total):
        return
    new_value = min(cint(m.classes_remaining) + 1, cint(m.classes_total))
    frappe.db.set_value("Gym Membership", membership, "classes_remaining", new_value, update_modified=False)


def has_credit(membership):
    m = lock_membership(membership)
    return (not cint(m.classes_total)) or cint(m.classes_remaining) > 0


# ------------------------------------------------------------------ roles / trainers
def is_trainer_only(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return False
    roles = set(frappe.get_roles(user))
    return TRAINER in roles and not (roles & STAFF_ROLES)


def get_user_trainers(user=None):
    user = user or frappe.session.user
    employees = frappe.get_all("Employee", filters={"user_id": user}, pluck="name")
    if not employees:
        return []
    return frappe.get_all("Gym Trainer", filters={"employee": ["in", employees]}, pluck="name")


# ------------------------------------------------------------------ notifications
def notify_member(member, subject, message, sms=None):
    """E-mail the member and, when enabled in Gym Settings, send a short SMS too.

    ``sms`` is the SMS text (defaults to the subject). A failure in either channel is logged
    and never blocks the business operation that triggered the notification."""
    email = frappe.db.get_value("Gym Member", member, "email")
    if email:
        try:
            frappe.sendmail(recipients=[email], subject=subject, message=message,
                            reference_doctype="Gym Member", reference_name=member)
        except Exception:
            frappe.log_error(title="Gym Management: could not queue notification")
    try:
        from gym_management import sms as sms_module

        sms_module.send_member_sms(member, sms or subject)
    except Exception:
        frappe.log_error(title="Gym Management: could not queue SMS")
