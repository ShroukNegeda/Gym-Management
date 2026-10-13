import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, get_first_day, get_last_day, getdate, now_datetime, today

from gym_management import booking, utils

# status -> statuses it may move to
TRANSITIONS = {
    "Booked": {"Attended", "No Show", "Cancelled"},
    "Waitlisted": {"Cancelled"},          # Waitlisted -> Booked only through waitlist promotion
    "Attended": {"No Show", "Booked"},
    "No Show": {"Attended", "Booked"},
    "Cancelled": set(),
}
TRAINER_STATUSES = {"Booked", "Attended", "No Show"}


class ClassBooking(Document):
    def validate(self):
        self._before = self.get_doc_before_save()
        if self.is_new():
            self.validate_new_booking()
        else:
            self.validate_status_change()

    def after_insert(self):
        if self.status == "Booked":
            booking.apply_booked(self)

    def on_update(self):
        before = self._before
        if not before or before.status == self.status:
            return
        if before.status == "Booked" and self.status == "Cancelled":
            booking.release_spot(self, refund_credit=not self.late_cancellation)
            booking.promote_waitlist(self.class_session)
        elif before.status == "Waitlisted" and self.status == "Booked":
            booking.apply_booked(self)
        if self.status == "No Show":
            self.warn_about_no_shows()

    def on_trash(self):
        if self.status in utils.OCCUPYING:
            booking.release_spot(self, refund_credit=self.status == "Booked")
            booking.promote_waitlist(self.class_session)

    # ------------------------------------------------------------------
    def validate_new_booking(self):
        session = frappe.db.get_value(
            "Class Session", self.class_session, ["session_date", "starts_on", "status"], as_dict=True)
        utils.ensure_member_allowed(self.member)
        if session.status != "Scheduled":
            frappe.throw(_("Class Session {0} is {1} and cannot be booked.").format(self.class_session, session.status))
        if get_datetime(session.starts_on) <= now_datetime():
            frappe.throw(_("Class Session {0} has already started.").format(self.class_session))

        # the membership must be usable ON THE SESSION DATE (not just today)
        res = utils.resolve_membership(self.member, session.session_date)
        if not res.membership:
            frappe.throw(res.message, title=_("No active membership"))
        self.membership = res.membership
        self.session_date = session.session_date

        # --- everything below is serialised per session (see DECISIONS.md R4)
        locked = utils.lock_session(self.class_session)
        duplicate = frappe.db.sql(
            """select name from `tabClass Booking`
               where class_session=%s and member=%s and status!='Cancelled' and name!=%s for update""",
            (self.class_session, self.member, self.name or ""),
        )
        if duplicate:
            frappe.throw(_("{0} is already booked (or waitlisted) for this session: {1}.").format(
                frappe.bold(self.member_name or self.member), duplicate[0][0]), title=_("Duplicate booking"))
        if not utils.has_credit(self.membership):
            frappe.throw(_("No classes remaining on membership {0}.").format(self.membership), title=_("No class credits"))

        if cint(locked.booked_count) < cint(locked.capacity):
            self.status = "Booked"
        elif cint(utils.get_settings().enable_waitlist):
            self.status = "Waitlisted"
            frappe.msgprint(_("The session is full: {0} was added to the waitlist.").format(self.member_name or self.member),
                            indicator="orange", alert=True)
        else:
            frappe.throw(_("Class Session {0} is full and the waitlist is disabled.").format(self.class_session), title=_("Session full"))
        self.booked_on = now_datetime()
        self.cancelled_on = None
        self.late_cancellation = 0

    def validate_status_change(self):
        before = self._before
        for field in ("class_session", "member"):
            if before.get(field) != self.get(field):
                frappe.throw(_("{0} cannot be changed. Cancel this booking and create a new one.").format(self.meta.get_label(field)))
        if before.status == self.status:
            return
        allowed = set(TRANSITIONS[before.status])
        if before.status == "Waitlisted" and self.flags.in_waitlist_promotion:
            allowed.add("Booked")
        if self.status not in allowed:
            frappe.throw(_("A booking cannot move from {0} to {1}.").format(before.status, self.status))
        if utils.is_trainer_only() and not self.flags.ignore_permissions and self.status not in TRAINER_STATUSES:
            frappe.throw(_("Trainers can only mark attendance (Attended / No Show)."))

        session_date = frappe.db.get_value("Class Session", self.class_session, "session_date")
        if self.status in ("Attended", "No Show") and getdate(session_date) > getdate(today()):
            frappe.throw(_("Attendance cannot be marked before the session date."))

        if self.status == "Cancelled":
            self.cancelled_on = now_datetime()
            window = cint(utils.get_settings().cancellation_window_hours)
            late = (before.status == "Booked" and not self.flags.session_cancelled
                    and booking.hours_until_session(self.class_session) < window)
            self.late_cancellation = 1 if late else 0
            if late:
                frappe.msgprint(_("Late cancellation (inside the {0}h window): the class credit is not refunded.").format(window),
                                indicator="orange", alert=True)

    def warn_about_no_shows(self):
        limit = cint(utils.get_settings().no_show_limit)
        if not limit or not self.session_date:
            return
        count = frappe.db.count("Class Booking", {
            "member": self.member, "status": "No Show",
            "session_date": ["between", [get_first_day(self.session_date), get_last_day(self.session_date)]],
        })
        if count > limit:
            frappe.msgprint(_("{0} has {1} no-shows this month (limit {2}).").format(
                frappe.bold(self.member_name or self.member), count, limit), indicator="orange", alert=True)
