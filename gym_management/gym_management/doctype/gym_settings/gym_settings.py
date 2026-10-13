import frappe
from frappe import _
from frappe.model.document import Document


class GymSettings(Document):
    def validate(self):
        for field in ("cancellation_window_hours", "no_show_limit", "expiry_reminder_days"):
            if (self.get(field) or 0) < 0:
                frappe.throw(_("{0} cannot be negative.").format(self.meta.get_label(field)))
        if self.default_income_account:
            acc = frappe.db.get_value("Account", self.default_income_account, ["root_type", "is_group"], as_dict=True)
            if acc.root_type != "Income" or acc.is_group:
                frappe.throw(_("Default Income Account must be a non-group Income account."))
