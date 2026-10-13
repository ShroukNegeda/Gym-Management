import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, date_diff, flt, getdate, today

from gym_management import utils


class GymMembership(Document):
    # ------------------------------------------------------------ lifecycle
    def validate(self):
        if self.docstatus == 0:
            self.validate_member_and_plan()
            self.snapshot_plan()
            self.validate_no_freezes_on_draft()
        self.refresh_computed_fields()

    def before_update_after_submit(self):
        # Frappe does NOT call validate() for "update after submit" saves (e.g. adding a freeze),
        # so the computed fields are refreshed here as well.
        self.refresh_computed_fields()

    def refresh_computed_fields(self):
        if self.docstatus == 1:
            # classes_remaining is changed with SQL by bookings: never write back a stale value
            self.classes_remaining = utils.lock_membership(self.name).classes_remaining
        self.validate_freezes()
        self.end_date = add_days(self.base_end_date, cint(self.total_freeze_days))
        self.validate_no_overlap()
        self.set_status()

    def before_submit(self):
        utils.ensure_member_allowed(self.member)

    def on_submit(self):
        self.create_invoice()
        utils.refresh_member(self.member)

    def on_update_after_submit(self):
        utils.refresh_member(self.member)

    def on_cancel(self):
        # validate() is not run for cancel, so the status is set here
        self.db_set("status", "Cancelled", update_modified=False)
        self.cancel_invoice()
        self.cancel_future_bookings()
        utils.refresh_member(self.member)

    # ------------------------------------------------------------ validation
    def validate_member_and_plan(self):
        utils.ensure_member_allowed(self.member)
        plan = frappe.db.get_value("Membership Plan", self.membership_plan, ["is_active"], as_dict=True)
        if not plan.is_active:
            frappe.throw(_("Membership Plan {0} is not active.").format(self.membership_plan))

    def snapshot_plan(self):
        """Copy what we need from the plan so later plan edits never rewrite sold memberships."""
        plan = frappe.get_cached_doc("Membership Plan", self.membership_plan)
        self.base_end_date = utils.compute_base_end_date(
            self.start_date, plan.duration_type, plan.duration_value, plan.validity_days)
        self.max_freeze_days = cint(plan.max_freeze_days)
        total = cint(plan.classes_included)
        if not total and plan.duration_type == "Class Pack":
            total = cint(plan.duration_value)
        self.classes_total = total  # 0 = unlimited
        self.classes_remaining = total

    def validate_no_freezes_on_draft(self):
        if self.freeze_history:
            frappe.throw(_("Freezes can only be added after the membership is submitted."))

    def validate_freezes(self):
        before = self.get_doc_before_save()
        known = {r.name for r in before.freeze_history} if before else set()
        rows = sorted(self.freeze_history or [], key=lambda r: getdate(r.freeze_from) if r.freeze_from else getdate("1900-01-01"))
        total, previous_to = 0, None
        for row in rows:
            if not (row.freeze_from and row.freeze_to):
                frappe.throw(_("Row {0}: Freeze From and Freeze To are required.").format(row.idx))
            f, t = getdate(row.freeze_from), getdate(row.freeze_to)
            if t <= f:
                frappe.throw(_("Row {0}: Freeze To must be after Freeze From.").format(row.idx))
            if row.name not in known:  # only police rows that are being added now
                if f < getdate(today()):
                    frappe.throw(_("Row {0}: a freeze cannot start in the past.").format(row.idx))
                if f < getdate(self.start_date) or f > getdate(self.end_date):
                    frappe.throw(_("Row {0}: a freeze must start within the membership period.").format(row.idx))
            if previous_to and f <= previous_to:
                frappe.throw(_("Row {0}: freeze periods cannot overlap.").format(row.idx))
            previous_to = t
            row.days = date_diff(t, f) + 1
            total += row.days
        if total > cint(self.max_freeze_days):
            frappe.throw(
                _("Total freeze days ({0}) exceed the {1} days allowed by plan {2}.").format(
                    total, cint(self.max_freeze_days), self.membership_plan),
                title=_("Freeze limit exceeded"))
        self.total_freeze_days = total

    def validate_no_overlap(self):
        """Only one membership may be active for a member at any time."""
        clash = frappe.db.sql(
            """select name from `tabGym Membership`
               where member=%s and docstatus=1 and name!=%s
                 and start_date <= %s and end_date >= %s limit 1""",
            (self.member, self.name or "", self.end_date, self.start_date),
        )
        if clash:
            frappe.throw(
                _("{0} already has membership {1} covering part of {2} - {3}. Only one membership can be active at a time.").format(
                    frappe.bold(self.member_name or self.member), clash[0][0],
                    frappe.format(self.start_date, "Date"), frappe.format(self.end_date, "Date")),
                title=_("Overlapping membership"))

    def set_status(self):
        if self.docstatus == 0:
            self.status = "Draft"
        elif self.docstatus == 2:
            self.status = "Cancelled"
        else:
            t = getdate(today())
            if getdate(self.end_date) < t:
                self.status = "Expired"
            elif any(getdate(r.freeze_from) <= t <= getdate(r.freeze_to) for r in self.freeze_history or []):
                self.status = "Frozen"
            else:
                self.status = "Active"

    # ------------------------------------------------------------ billing
    def create_invoice(self):
        """Create + submit the Sales Invoice exactly once (idempotent under retries).

        The membership row is locked, then we look for an existing invoice via the
        ``gym_membership`` custom field on Sales Invoice - that field is the source of truth,
        so a retried submit (or a crash between invoice creation and linking) cannot bill twice.
        """
        if frappe.flags.get("gym_skip_invoice"):
            return None
        utils.lock_membership(self.name)
        existing = frappe.db.get_value("Sales Invoice", {"gym_membership": self.name, "docstatus": ["!=", 2]})
        if existing:
            self.db_set("sales_invoice", existing, update_modified=False)
            return existing

        plan = frappe.get_cached_doc("Membership Plan", self.membership_plan)
        if flt(plan.price) <= 0:
            return None  # free plan: nothing to bill

        customer = frappe.db.get_value("Gym Member", self.member, "customer")
        income_account = utils.get_settings().default_income_account
        row = {
            "item_code": plan.item,
            "qty": 1,
            "rate": plan.price,
            "description": _("{0} ({1} to {2})").format(
                plan.plan_name, frappe.format(self.start_date, "Date"), frappe.format(self.end_date, "Date")),
        }
        if income_account and frappe.db.get_value("Account", income_account, "company") == self.company:
            row["income_account"] = income_account

        si = frappe.new_doc("Sales Invoice")
        si.customer = customer
        si.company = self.company
        si.posting_date = today()
        si.due_date = today()
        si.gym_membership = self.name
        si.gym_member = self.member
        si.append("items", row)
        si.set_missing_values()
        si.insert(ignore_permissions=True)  # front desk may sell memberships without Accounts permissions
        si.submit()
        self.db_set("sales_invoice", si.name, update_modified=False)
        return si.name

    def cancel_invoice(self):
        invoice = frappe.db.get_value("Sales Invoice", {"gym_membership": self.name, "docstatus": 1})
        if invoice:
            frappe.get_doc("Sales Invoice", invoice).cancel()

    def cancel_future_bookings(self):
        for name in frappe.get_all(
            "Class Booking",
            filters={"membership": self.name, "status": ["in", ["Booked", "Waitlisted"]], "session_date": [">=", today()]},
            pluck="name",
        ):
            booking = frappe.get_doc("Class Booking", name)
            booking.flags.session_cancelled = True  # no late-cancel penalty: the gym is the one cancelling
            booking.status = "Cancelled"
            booking.save(ignore_permissions=True)

    # ------------------------------------------------------------ actions (called from the form)
    @frappe.whitelist()
    def freeze(self, freeze_from, freeze_to, reason=None):
        self.check_permission("write")
        if self.docstatus != 1 or self.status not in ("Active", "Frozen"):
            frappe.throw(_("Only an Active membership can be frozen."))
        self.append("freeze_history", {"freeze_from": freeze_from, "freeze_to": freeze_to, "reason": reason})
        self.save()
        return {"status": self.status, "end_date": str(self.end_date)}

    @frappe.whitelist()
    def renew(self, submit=False):
        """Create (and optionally submit) the next membership, starting right after this one.

        Idempotent: if a renewal already exists it is returned instead of creating another.
        """
        self.check_permission("write")
        if self.docstatus != 1:
            frappe.throw(_("Only submitted memberships can be renewed."))
        existing = frappe.db.get_value("Gym Membership", {"renewed_from": self.name, "docstatus": ["<", 2]})
        if existing:
            return existing
        start = add_days(self.end_date, 1)
        if getdate(start) < getdate(today()):
            start = today()
        new = frappe.new_doc("Gym Membership")
        new.update({
            "member": self.member,
            "membership_plan": self.membership_plan,
            "company": self.company,
            "start_date": start,
            "auto_renew": self.auto_renew,
            "renewed_from": self.name,
        })
        new.insert()
        if cint(submit):
            new.submit()
        return new.name
