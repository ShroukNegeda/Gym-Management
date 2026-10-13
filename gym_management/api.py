"""Whitelisted API. Permission rules of the underlying DocTypes always apply
(documents are created/saved with the caller's permissions, never ignore_permissions)."""
import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_first_day, getdate, now_datetime, today

from gym_management import utils


# ---------------------------------------------------------------- classes
@frappe.whitelist()
def book_class(session, member):
    """Book ``member`` into ``session``. Returns the booking and whether it was confirmed or waitlisted."""
    doc = frappe.get_doc({"doctype": "Class Booking", "class_session": session, "member": member})
    doc.insert()
    return {"booking": doc.name, "status": doc.status, "membership": doc.membership}


@frappe.whitelist()
def cancel_booking(booking):
    doc = frappe.get_doc("Class Booking", booking)
    doc.status = "Cancelled"
    doc.save()
    return {"booking": doc.name, "status": doc.status, "late_cancellation": cint(doc.late_cancellation)}


@frappe.whitelist()
def mark_attendance(booking, status):
    if status not in ("Attended", "No Show"):
        frappe.throw(_("Status must be Attended or No Show."))
    doc = frappe.get_doc("Class Booking", booking)
    doc.status = status
    doc.save()
    return {"booking": doc.name, "status": doc.status}


@frappe.whitelist()
def get_available_sessions(date_from, date_to):
    """Upcoming, non-cancelled sessions in the range with the spots left."""
    rows = frappe.get_list(
        "Class Session",
        filters={"status": "Scheduled", "session_date": ["between", [getdate(date_from), getdate(date_to)]],
                 "starts_on": [">=", now_datetime()]},
        fields=["name", "gym_class", "trainer", "trainer_name", "room", "session_date", "start_time", "end_time",
                "capacity", "booked_count"],
        order_by="session_date asc, start_time asc",
    )
    for r in rows:
        r["spots_left"] = max(cint(r.capacity) - cint(r.booked_count), 0)
    return rows


# ---------------------------------------------------------------- front desk
@frappe.whitelist()
def search_members(txt):
    txt = (txt or "").strip()
    if not txt:
        return []
    fields = ["name", "member_name", "phone", "status", "photo"]
    exact = frappe.get_list("Gym Member", filters={"name": txt}, fields=fields, limit=1)  # QR codes carry the member ID
    if exact:
        return exact
    like = f"%{txt}%"
    return frappe.get_list(
        "Gym Member",
        or_filters=[["member_name", "like", like], ["phone", "like", like], ["email", "like", like], ["name", "like", like]],
        fields=fields, limit=10, order_by="member_name asc",
    )


@frappe.whitelist()
def get_member_access(member):
    """Everything the front desk needs to decide whether to let someone in."""
    doc = frappe.get_doc("Gym Member", member)  # permission checked
    res = utils.resolve_membership(member, today())
    allowed = res.code == "ok" and doc.status != "Blacklisted"
    message = res.message or _("Membership is valid.")
    if doc.status == "Blacklisted":
        message = _("{0} is blacklisted.").format(doc.member_name)
    out = {
        "member": doc.name, "member_name": doc.member_name, "photo": doc.photo, "phone": doc.phone,
        "allowed": allowed, "code": res.code, "message": message, "membership": res.membership or res.current,
    }
    ms = out["membership"]
    if ms:
        out.update(frappe.db.get_value("Gym Membership", ms, ["membership_plan", "end_date", "classes_total", "classes_remaining"], as_dict=True))
    out["bookings_today"] = frappe.get_list(
        "Class Booking",
        filters={"member": member, "status": "Booked", "session_date": today()},
        fields=["name", "class_session"],
    )
    for b in out["bookings_today"]:
        s = frappe.db.get_value("Class Session", b.class_session, ["gym_class", "start_time"], as_dict=True)
        b.update(s)
    return out


@frappe.whitelist()
def check_in(member, method="Front Desk", class_booking=None):
    doc = frappe.get_doc({"doctype": "Gym Check In", "member": member, "method": method,
                          "class_booking": class_booking or None})
    doc.insert()
    return {"check_in": doc.name, "membership": doc.membership}


# ---------------------------------------------------------------- dashboard
@frappe.whitelist()
def get_dashboard_data():
    frappe.only_for(("Gym Manager", "System Manager"))
    t = getdate(today())
    month_start = get_first_day(t)

    active_members = frappe.db.count("Gym Member", {"status": "Active"})
    expiring = frappe.get_all(
        "Gym Membership",
        filters={"docstatus": 1, "status": "Active", "end_date": ["between", [t, add_days(t, 7)]]},
        fields=["name", "member", "member_name", "end_date", "membership_plan"], order_by="end_date asc", limit=20,
    )
    sessions = frappe.get_all(
        "Class Session",
        filters={"session_date": t, "status": ["!=", "Cancelled"]},
        fields=["name", "gym_class", "trainer_name", "start_time", "capacity", "booked_count", "status"],
        order_by="start_time asc",
    )
    for s in sessions:
        s["fill_rate"] = round(100 * cint(s.booked_count) / cint(s.capacity), 1) if cint(s.capacity) else 0

    by_day = frappe.db.sql(
        """select posting_date, sum(base_net_total) as invoiced,
                  sum(base_grand_total - outstanding_amount) as collected
           from `tabSales Invoice`
           where docstatus=1 and ifnull(gym_membership,'')!='' and posting_date between %s and %s
           group by posting_date order by posting_date""",
        (month_start, t), as_dict=True,
    )
    return {
        "active_members": active_members,
        "expiring_count": len(expiring),
        "expiring": expiring,
        "sessions": sessions,
        "revenue_invoiced": flt(sum(flt(r.invoiced) for r in by_day)),
        "revenue_collected": flt(sum(flt(r.collected) for r in by_day)),
        "revenue_by_day": [{"date": str(r.posting_date), "invoiced": flt(r.invoiced)} for r in by_day],
        "currency": frappe.db.get_default("currency"),
    }
