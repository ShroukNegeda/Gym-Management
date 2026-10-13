import frappe
from frappe import _
from frappe.model.document import Document


class GymClass(Document):
    def validate(self):
        if (self.duration_minutes or 0) <= 0:
            frappe.throw(_("Duration must be greater than zero."))
        if self.default_trainer and not frappe.db.get_value("Gym Trainer", self.default_trainer, "is_active"):
            frappe.throw(_("Default Trainer {0} is not active.").format(self.default_trainer))
        if self.default_room:
            room_capacity = frappe.db.get_value("Gym Room", self.default_room, "capacity")
            if self.default_capacity and self.default_capacity > room_capacity:
                frappe.throw(_("Default Capacity ({0}) cannot exceed the capacity of room {1} ({2}).").format(
                    self.default_capacity, self.default_room, room_capacity))
        elif self.default_capacity and self.default_capacity < 1:
            frappe.throw(_("Default Capacity must be at least 1."))
