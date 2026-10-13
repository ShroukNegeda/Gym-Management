import frappe
from frappe import _
from frappe.model.document import Document


class GymTrainer(Document):
    def validate(self):
        status = frappe.db.get_value("Employee", self.employee, "status")
        if self.is_active and status != "Active":
            frappe.throw(_("Employee {0} is not Active, so the trainer profile cannot be active.").format(self.employee))
