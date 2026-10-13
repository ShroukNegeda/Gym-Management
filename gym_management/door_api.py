"""REST endpoints for a door-access controller (turnstile / card reader).

The controller authenticates as a normal Frappe user that has the *Front Desk* role, using an
API key + secret (User > API Access > Generate Keys) and the standard header:

    Authorization: token <api_key>:<api_secret>

so every call is permission-checked exactly like a click by a human at the front desk.
Denied entries are an ordinary JSON answer (``allow: false``), never an HTTP error, so the
controller can show the reason on its display.
"""
import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime, today

from gym_management import utils

ALLOWED_ROLES = ("Gym Manager", "Front Desk", "System Manager")
METHODS = ("Front Desk", "QR", "Card")
# card readers and turnstiles retry; a second scan this soon is the same visit, not a new one
DUPLICATE_WINDOW_SECONDS = 60


@frappe.whitelist(methods=["POST"])
def check_access(member, direction="in", method="QR"):
    """Ask whether ``member`` (the Gym Member ID, i.e. the QR/card content) may pass the door.

    direction="in"  - validates the membership; when allowed a Gym Check In is recorded.
    direction="out" - always allowed (nobody is locked inside); closes the open check-in.
    """
    frappe.only_for(ALLOWED_ROLES)
    direction = (direction or "in").strip().lower()
    if direction not in ("in", "out"):
        frappe.throw(_("direction must be 'in' or 'out'."))
    if method not in METHODS:
        frappe.throw(_("method must be one of: {0}").format(", ".join(METHODS)))

    member = (member or "").strip()
    row = frappe.db.get_value("Gym Member", member, ["member_name", "status"], as_dict=True) if member else None
    if not row:
        return _answer(False, "unknown_member", _("Unknown member."), member)

    if direction == "out":
        return _check_out(member, row.member_name)

    if row.status == "Blacklisted":
        return _answer(False, "blacklisted", _("{0} is blacklisted.").format(row.member_name), member, row.member_name)

    # serialise concurrent scans of the same person (two readers, a double tap, a retry)
    frappe.db.get_value("Gym Member", member, "name", for_update=True)

    res = utils.resolve_membership(member, today())
    if not res.membership:
        return _answer(False, res.code, res.message, member, row.member_name)

    recent = frappe.db.get_value(
        "Gym Check In",
        {"member": member, "creation": [">=", add_to_date(now_datetime(), seconds=-DUPLICATE_WINDOW_SECONDS)]},
        "name",
    )
    if recent:
        return _answer(True, "ok", _("Already checked in."), member, row.member_name,
                       membership=res.membership, check_in=recent, duplicate=True)

    check_in = frappe.get_doc({"doctype": "Gym Check In", "member": member, "method": method})
    check_in.insert()
    return _answer(True, "ok", _("Welcome, {0}!").format(row.member_name), member, row.member_name,
                   membership=res.membership, check_in=check_in.name, duplicate=False)


@frappe.whitelist()
def get_active_members():
    """Everyone allowed in right now - for controllers that cache the list and work offline.

    Same rules as ``check_access``: submitted membership covering today, not inside a freeze,
    member not blacklisted.
    """
    frappe.only_for(ALLOWED_ROLES)
    rows = frappe.db.sql(
        """select distinct gm.member as member, m.member_name as member_name, gm.name as membership,
                  gm.end_date as valid_until
           from `tabGym Membership` gm
           join `tabGym Member` m on m.name = gm.member
           where gm.docstatus = 1
             and gm.start_date <= %(today)s and gm.end_date >= %(today)s
             and ifnull(m.status, '') != 'Blacklisted'
             and not exists (
                 select 1 from `tabMembership Freeze` f
                 where f.parent = gm.name and f.parenttype = 'Gym Membership'
                   and f.freeze_from <= %(today)s and f.freeze_to >= %(today)s)
           order by gm.member""",
        {"today": today()}, as_dict=True,
    )
    return {"as_of": str(today()), "count": len(rows), "members": rows}


# ---------------------------------------------------------------------------
def _check_out(member, member_name):
    open_visits = frappe.get_all(
        "Gym Check In",
        filters={"member": member, "check_out_time": ["is", "not set"], "check_in_time": [">=", get_datetime(today())]},
        pluck="name", order_by="check_in_time desc", limit=1,
    )
    if not open_visits:
        return _answer(True, "ok", _("No open check-in; exit allowed."), member, member_name)
    visit = frappe.get_doc("Gym Check In", open_visits[0])
    visit.check_out_time = now_datetime()
    visit.save()
    return _answer(True, "ok", _("Goodbye, {0}!").format(member_name), member, member_name, check_in=visit.name)


def _answer(allow, code, message, member, member_name=None, **extra):
    return {"allow": bool(allow), "code": code, "message": message, "member": member,
            "member_name": member_name, **extra}
