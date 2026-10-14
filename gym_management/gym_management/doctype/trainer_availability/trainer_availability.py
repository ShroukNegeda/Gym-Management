import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_time

from gym_management import personal_training as pt


class TrainerAvailability(Document):
    def validate(self):
        if not frappe.db.get_value("Gym Trainer", self.trainer, "is_active"):
            frappe.throw(_("Trainer {0} is not active.").format(self.trainer))
        if pt.to_minutes(self.to_time) <= pt.to_minutes(self.from_time):
            frappe.throw(_("To Time must be after From Time."))
        if cint(self.is_active):
            self.validate_no_overlap()

    def validate_no_overlap(self):
        clash = frappe.db.sql(
            """select name from `tabTrainer Availability`
               where trainer=%s and day_of_week=%s and is_active=1 and name!=%s
                 and from_time < %s and to_time > %s limit 1""",
            (self.trainer, self.day_of_week, self.name or "", str(get_time(self.to_time)), str(get_time(self.from_time))),
        )
        if clash:
            frappe.throw(_("{0} already has overlapping working hours on {1}: {2}").format(
                frappe.bold(self.trainer), self.day_of_week, clash[0][0]), title=_("Overlapping hours"))
