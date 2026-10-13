import frappe
from frappe import _
from frappe.utils import add_days, date_diff, getdate, today


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Membership"), "fieldname": "name", "fieldtype": "Link", "options": "Gym Membership", "width": 170},
        {"label": _("Member"), "fieldname": "member", "fieldtype": "Link", "options": "Gym Member", "width": 110},
        {"label": _("Member Name"), "fieldname": "member_name", "fieldtype": "Data", "width": 160},
        {"label": _("Plan"), "fieldname": "membership_plan", "fieldtype": "Link", "options": "Membership Plan", "width": 150},
        {"label": _("Start"), "fieldname": "start_date", "fieldtype": "Date", "width": 100},
        {"label": _("Expires"), "fieldname": "end_date", "fieldtype": "Date", "width": 100},
        {"label": _("Days Left"), "fieldname": "days_left", "fieldtype": "Int", "width": 90},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
        {"label": _("Auto Renew"), "fieldname": "auto_renew", "fieldtype": "Check", "width": 90},
        {"label": _("Phone"), "fieldname": "phone", "fieldtype": "Data", "width": 120},
        {"label": _("Email"), "fieldname": "email", "fieldtype": "Data", "width": 180},
    ]


def get_data(filters):
    from_date = getdate(filters.get("from_date") or today())
    to_date = getdate(filters.get("to_date") or add_days(from_date, 30))
    if from_date > to_date:
        frappe.throw(_("From Date cannot be after To Date."))

    conditions = {"docstatus": ["in", [1, 2]], "end_date": ["between", [from_date, to_date]]}
    if filters.get("membership_plan"):
        conditions["membership_plan"] = filters.membership_plan
    if filters.get("status"):
        conditions["status"] = filters.status

    rows = frappe.get_list(
        "Gym Membership", filters=conditions,
        fields=["name", "member", "member_name", "membership_plan", "start_date", "end_date", "status", "auto_renew"],
        order_by="end_date asc",
    )
    contacts = {}
    if rows:
        for m in frappe.get_all("Gym Member", filters={"name": ["in", [r.member for r in rows]]}, fields=["name", "phone", "email"]):
            contacts[m.name] = m
    t = getdate(today())
    for r in rows:
        r.days_left = date_diff(r.end_date, t)
        c = contacts.get(r.member) or {}
        r.phone, r.email = c.get("phone"), c.get("email")
    return rows
