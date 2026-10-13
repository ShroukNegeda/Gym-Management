import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

# field -> (min, max): catches typos such as 7 kg or 1750 cm
LIMITS = {
    "weight_kg": (20, 400),
    "height_cm": (100, 250),
    "body_fat_percent": (2, 70),
    "chest_cm": (30, 250),
    "waist_cm": (30, 250),
    "hips_cm": (30, 250),
}


class BodyMeasurement(Document):
    def validate(self):
        self.validate_date()
        self.validate_values()
        self.calculate_bmi()

    def validate_date(self):
        if getdate(self.measured_on) > getdate(today()):
            frappe.throw(_("Measured On cannot be in the future."))

    def validate_values(self):
        if not any(flt(self.get(field)) for field in LIMITS):
            frappe.throw(_("Enter at least one measurement."))
        for field, (low, high) in LIMITS.items():
            value = flt(self.get(field))
            if value and not (low <= value <= high):
                frappe.throw(_("{0} must be between {1} and {2}.").format(self.meta.get_label(field), low, high))

    def calculate_bmi(self):
        weight, height = flt(self.weight_kg), flt(self.height_cm)
        self.bmi = round(weight / ((height / 100) ** 2), 1) if weight and height else 0
