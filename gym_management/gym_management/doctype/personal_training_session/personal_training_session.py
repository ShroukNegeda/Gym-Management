from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, get_time, getdate, now_datetime

from gym_management import personal_training as pt
from gym_management import utils

# status -> statuses it may move to
TRANSITIONS = {"Booked": {"Completed", "No Show", "Cancelled"}, "Completed": set(), "No Show": set(), "Cancelled": set()}
# the time/place of a booking is fixed: to change it, cancel and book again (re-runs every check)
LOCKED_FIELDS = ("member", "trainer", "session_date", "start_time", "duration_minutes")


class PersonalTrainingSession(Document):
    def validate(self):
        self._before = self.get_doc_before_save()
        self.set_times()
        if self.is_new():
            self.validate_new_booking()
        else:
            self.validate_changes()

    def after_insert(self):
        self.notify(
            _("PT booked: {0} {1} {2}").format(self.trainer_label(), frappe.format(self.session_date, "Date"), str(get_time(self.start_time))[:5]),
            _("Your personal training session {0} is booked for {1} at {2} with {3}.").format(
                self.name, frappe.format(self.session_date, "Date"), str(get_time(self.start_time))[:5], self.trainer_label()))

    def on_update(self):
        before = self._before
        if before and before.status != "Cancelled" and self.status == "Cancelled":
            self.notify(
                _("PT cancelled: {0} {1}").format(frappe.format(self.session_date, "Date"), str(get_time(self.start_time))[:5]),
                _("Your personal training session {0} on {1} was cancelled.").format(self.name, frappe.format(self.session_date, "Date")))

    # ------------------------------------------------------------------
    def set_times(self):
        duration = cint(self.duration_minutes) or pt.DEFAULT_DURATION
        if not pt.MIN_DURATION <= duration <= pt.MAX_DURATION:
            frappe.throw(_("Duration must be between {0} and {1} minutes.").format(pt.MIN_DURATION, pt.MAX_DURATION))
        start = datetime.combine(getdate(self.session_date), get_time(self.start_time))
        end = start + timedelta(minutes=duration)
        if end.date() != start.date():
            frappe.throw(_("A session cannot run past midnight."))
        self.duration_minutes = duration
        self.end_time = end.strftime("%H:%M:%S")
        self.starts_on, self.ends_on = start, end

    def validate_new_booking(self):
        utils.ensure_member_allowed(self.member)
        if not frappe.db.get_value("Gym Trainer", self.trainer, "is_active"):
            frappe.throw(_("Trainer {0} is not active.").format(self.trainer))
        if get_datetime(self.starts_on) <= now_datetime():
            frappe.throw(_("Cannot book a session in the past."))

        # the membership must be valid ON THE SESSION DATE (a renewal may start later than today)
        res = utils.resolve_membership(self.member, self.session_date)
        if not res.membership:
            frappe.throw(res.message, title=_("No active membership"))
        self.membership = res.membership

        pt.assert_within_availability(self.trainer, self.session_date, self.start_time, self.end_time)
        # serialise bookings per trainer, then check for clashes with locking reads
        frappe.db.get_value("Gym Trainer", self.trainer, "name", for_update=True)
        pt.assert_no_conflict(self.trainer, self.member, self.session_date, self.start_time, self.end_time, exclude=self.name)

        self.status = "Booked"
        self.booked_on = now_datetime()
        self.cancelled_on = None
        self.late_cancellation = 0

    def validate_changes(self):
        before = self._before
        for field in LOCKED_FIELDS:
            if self._normalise(field, before.get(field)) != self._normalise(field, self.get(field)):
                frappe.throw(_("{0} cannot be changed. Cancel this session and book a new one.").format(self.meta.get_label(field)))
        if before.status == self.status:
            return
        if self.status not in TRANSITIONS[before.status]:
            frappe.throw(_("A session cannot move from {0} to {1}.").format(before.status, self.status))
        if self.status in ("Completed", "No Show") and get_datetime(self.starts_on) > now_datetime():
            frappe.throw(_("A session that has not started yet cannot be marked {0}.").format(self.status))
        if self.status == "Cancelled":
            self.cancelled_on = now_datetime()
            window = cint(utils.get_settings().cancellation_window_hours)
            hours_left = (get_datetime(self.starts_on) - now_datetime()).total_seconds() / 3600
            self.late_cancellation = 1 if hours_left < window else 0

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise(field, value):
        if field == "start_time":
            return str(get_time(value))
        if field == "session_date":
            return str(getdate(value))
        return value

    def trainer_label(self):
        return frappe.db.get_value("Gym Trainer", self.trainer, "trainer_name") or self.trainer

    def notify(self, subject, message):
        utils.notify_member(self.member, subject, message, sms=subject)
