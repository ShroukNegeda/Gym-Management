from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_time, getdate, now_datetime

from gym_management import booking, personal_training, utils


class ClassSession(Document):
    def validate(self):
        self.apply_class_defaults()
        self.validate_masters()
        self.set_times()
        self.validate_capacity()
        self.validate_overlaps("trainer", _("Trainer {0} already has a session at this time: {1}"))
        self.validate_overlaps("room", _("Room {0} is already used by another session at this time: {1}"))
        personal_training.check_class_session_conflict(self)
        self.validate_status_change()

    def on_update(self):
        before = self.get_doc_before_save()
        if not before:
            return
        if before.status != "Cancelled" and self.status == "Cancelled":
            self.cancel_all_bookings()
        elif self.status == "Scheduled" and cint(self.capacity) > cint(before.capacity):
            booking.promote_waitlist(self.name)  # extra spots -> promote from the waitlist

    # -------------------------------------------------------------
    def apply_class_defaults(self):
        cls = frappe.get_cached_doc("Gym Class", self.gym_class)
        self.trainer = self.trainer or cls.default_trainer
        self.room = self.room or cls.default_room
        if not self.capacity:
            room_cap = frappe.db.get_value("Gym Room", self.room, "capacity") if self.room else None
            self.capacity = cls.default_capacity or room_cap
        if not (self.trainer and self.room and self.capacity):
            frappe.throw(_("Trainer, Room and Capacity are required (set them here or as defaults on the Gym Class)."))

    def validate_masters(self):
        if self.is_new() or self.has_value_changed("trainer"):
            if not frappe.db.get_value("Gym Trainer", self.trainer, "is_active"):
                frappe.throw(_("Trainer {0} is not active.").format(self.trainer))
        if self.is_new() or self.has_value_changed("room"):
            if not frappe.db.get_value("Gym Room", self.room, "is_active"):
                frappe.throw(_("Room {0} is not active.").format(self.room))

    def set_times(self):
        duration = frappe.get_cached_doc("Gym Class", self.gym_class).duration_minutes
        start = datetime.combine(getdate(self.session_date), get_time(self.start_time))
        end = start + timedelta(minutes=cint(duration))
        if end.date() != start.date():
            frappe.throw(_("A session cannot run past midnight."))
        self.end_time = end.strftime("%H:%M:%S")
        self.starts_on, self.ends_on = start, end
        if self.is_new() and start < now_datetime():
            frappe.throw(_("Cannot schedule a session in the past."))

    def validate_capacity(self):
        room_capacity = frappe.db.get_value("Gym Room", self.room, "capacity")
        if cint(self.capacity) < 1:
            frappe.throw(_("Capacity must be at least 1."))
        if cint(self.capacity) > room_capacity:
            frappe.throw(_("Capacity ({0}) cannot exceed the capacity of room {1} ({2}).").format(
                self.capacity, self.room, room_capacity))
        if not self.is_new():
            # re-read under a lock: booked_count is maintained with SQL by bookings
            self.booked_count = utils.lock_session(self.name).booked_count
            if cint(self.capacity) < cint(self.booked_count):
                frappe.throw(_("Capacity ({0}) cannot be lower than the {1} confirmed bookings.").format(
                    self.capacity, self.booked_count))

    def validate_overlaps(self, field, message):
        if self.status == "Cancelled":
            return
        clash = frappe.db.sql(
            f"""select name from `tabClass Session`
                where `{field}`=%(value)s and session_date=%(date)s and status!='Cancelled'
                  and name!=%(name)s and start_time < %(end)s and end_time > %(start)s limit 1""",
            {"value": self.get(field), "date": self.session_date, "name": self.name or "",
             "start": str(get_time(self.start_time)), "end": str(self.end_time)},
        )
        if clash:
            frappe.throw(message.format(frappe.bold(self.get(field)), clash[0][0]), title=_("Schedule conflict"))

    def validate_status_change(self):
        before = self.get_doc_before_save()
        if before and before.status == "Cancelled" and self.status != "Cancelled":
            frappe.throw(_("A cancelled session cannot be reopened. Create a new session instead."))

    # -------------------------------------------------------------
    def cancel_all_bookings(self):
        for name in frappe.get_all(
            "Class Booking", filters={"class_session": self.name, "status": ["in", ["Booked", "Waitlisted"]]}, pluck="name"
        ):
            b = frappe.get_doc("Class Booking", name)
            b.flags.session_cancelled = True
            b.status = "Cancelled"
            b.save(ignore_permissions=True)
            utils.notify_member(
                b.member, _("Class cancelled: {0}").format(self.gym_class),
                _("Your session on {0} at {1} was cancelled. Any class credit has been returned.").format(
                    frappe.format(self.session_date, "Date"), self.start_time))
        frappe.db.set_value("Class Session", self.name, "booked_count", 0, update_modified=False)
