"""Scheduled jobs."""
import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, now_datetime, today

from gym_management import utils


def hourly():
    complete_past_sessions()


def daily():
    update_membership_statuses()
    send_expiry_reminders()
    process_auto_renewals()


def complete_past_sessions():
    frappe.db.sql(
        "update `tabClass Session` set status='Completed' where status='Scheduled' and ends_on < %s",
        now_datetime(),
    )


def update_membership_statuses():
    """Expire past-end memberships and move memberships in/out of Frozen."""
    t = getdate(today())
    touched = set()

    for row in frappe.get_all(
        "Gym Membership",
        filters={"docstatus": 1, "status": ["in", ["Active", "Frozen"]], "end_date": ["<", t]},
        fields=["name", "member"],
    ):
        frappe.db.set_value("Gym Membership", row.name, "status", "Expired", update_modified=False)
        touched.add(row.member)

    live = frappe.get_all(
        "Gym Membership",
        filters={"docstatus": 1, "status": ["in", ["Active", "Frozen"]], "end_date": [">=", t]},
        fields=["name", "member", "status"],
    )
    frozen_now = set(
        frappe.get_all(
            "Membership Freeze",
            filters={"parenttype": "Gym Membership", "freeze_from": ["<=", t], "freeze_to": [">=", t]},
            pluck="parent",
        )
    )
    for row in live:
        target = "Frozen" if row.name in frozen_now else "Active"
        if row.status != target:
            frappe.db.set_value("Gym Membership", row.name, "status", target, update_modified=False)
            touched.add(row.member)

    # memberships that start today change who the member's "current" membership is
    touched.update(
        frappe.get_all("Gym Membership", filters={"docstatus": 1, "start_date": t}, pluck="member")
    )
    for member in touched:
        utils.refresh_member(member)


def send_expiry_reminders():
    days = cint(utils.get_settings().expiry_reminder_days)
    if not days:
        return
    t = getdate(today())
    rows = frappe.get_all(
        "Gym Membership",
        filters={
            "docstatus": 1, "status": "Active", "auto_renew": 0, "reminder_sent": 0,
            "end_date": ["between", [t, add_days(t, days)]],
        },
        fields=["name", "member", "member_name", "end_date"],
    )
    for row in rows:
        if frappe.db.exists("Gym Membership", {"renewed_from": row.name, "docstatus": ["<", 2]}):
            continue  # already renewed
        utils.notify_member(
            row.member,
            _("Your gym membership expires on {0}").format(frappe.format(row.end_date, "Date")),
            _("Hi {0}, membership {1} expires on {2}. Visit the front desk to renew.").format(
                row.member_name, row.name, frappe.format(row.end_date, "Date")),
        )
        frappe.db.set_value("Gym Membership", row.name, "reminder_sent", 1, update_modified=False)


def process_auto_renewals():
    t = getdate(today())
    rows = frappe.get_all(
        "Gym Membership",
        filters={
            "docstatus": 1, "auto_renew": 1, "status": ["in", ["Active", "Expired"]],
            "end_date": ["between", [add_days(t, -7), t]],
        },
        pluck="name",
    )
    for name in rows:
        try:
            frappe.get_doc("Gym Membership", name).renew(submit=True)
        except Exception:
            frappe.log_error(title=f"Gym Management: auto-renewal failed for {name}")
