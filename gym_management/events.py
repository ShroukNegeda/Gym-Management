import frappe


def employee_on_update(doc, method=None):
    """Deactivate the Gym Trainer profile when the Employee is no longer Active."""
    if doc.status != "Active":
        for name in frappe.get_all("Gym Trainer", filters={"employee": doc.name, "is_active": 1}, pluck="name"):
            frappe.db.set_value("Gym Trainer", name, "is_active", 0)
