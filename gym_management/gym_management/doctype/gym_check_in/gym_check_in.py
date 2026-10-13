import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate, now_datetime, today

from gym_management import utils


class GymCheckIn(Document):
    def validate(self):
        if not self.check_in_time:
            self.check_in_time = now_datetime()
        if self.check_out_time and get_datetime(self.check_out_time) < get_datetime(self.check_in_time):
            frappe.throw(_("Check-out time cannot be before check-in time."))
        if self.is_new():
            self.validate_access()
        self.validate_class_booking()

    def after_insert(self):
        if self.class_booking:
            booking = frappe.get_doc("Class Booking", self.class_booking)
            if booking.status == "Booked":
                booking.status = "Attended"
                booking.save(ignore_permissions=True)  # front desk checks people in, trainers/managers own bookings

    # ------------------------------------------------------------------
    def validate_access(self):
        utils.ensure_member_allowed(self.member)
        res = utils.resolve_membership(self.member, getdate(self.check_in_time))
        if not res.membership:
            frappe.throw(res.message, title=_("Check-in blocked"))
        self.membership = res.membership

    def validate_class_booking(self):
        if not self.class_booking:
            return
        b = frappe.db.get_value("Class Booking", self.class_booking,
                                ["member", "status", "session_date"], as_dict=True)
        if b.member != self.member:
            frappe.throw(_("Class Booking {0} belongs to a different member.").format(self.class_booking))
        if b.status not in ("Booked", "Attended"):
            frappe.throw(_("Class Booking {0} is {1}.").format(self.class_booking, b.status))
        if getdate(b.session_date) != getdate(self.check_in_time):
            frappe.throw(_("Class Booking {0} is for {1}, not for the check-in date.").format(
                self.class_booking, frappe.format(b.session_date, "Date")))
