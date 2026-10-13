import frappe
from frappe import _
from frappe.model.document import Document


class GymRoom(Document):
    def validate(self):
        if (self.capacity or 0) <= 0:
            frappe.throw(_("Room capacity must be greater than zero."))
