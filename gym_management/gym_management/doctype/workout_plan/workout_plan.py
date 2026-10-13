import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate

from gym_management import utils


class WorkoutPlan(Document):
    def validate(self):
        utils.ensure_member_allowed(self.member)
        self.validate_trainer()
        self.validate_dates()
        self.validate_exercises()
        self.validate_single_active_plan()

    def validate_trainer(self):
        if self.trainer and not frappe.db.get_value("Gym Trainer", self.trainer, "is_active"):
            frappe.throw(_("Trainer {0} is not active.").format(self.trainer))

    def validate_dates(self):
        if self.end_date and getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(_("End Date cannot be before Start Date."))

    def validate_exercises(self):
        if not self.exercises:
            frappe.throw(_("Add at least one exercise."))
        for row in self.exercises:
            if not (row.exercise or "").strip():
                frappe.throw(_("Row {0}: Exercise is required.").format(row.idx))
            sets, reps = cint(row.sets), cint(row.reps)
            if sets < 0 or reps < 0 or cint(row.rest_seconds) < 0:
                frappe.throw(_("Row {0}: Sets, Reps and Rest cannot be negative.").format(row.idx))
            if bool(sets) != bool(reps):  # timed / cardio work may leave both empty
                frappe.throw(_("Row {0}: enter both Sets and Reps (or leave both empty).").format(row.idx))

    def validate_single_active_plan(self):
        if self.status != "Active":
            return
        other = frappe.db.exists(
            "Workout Plan", {"member": self.member, "status": "Active", "name": ["!=", self.name or ""]})
        if other:
            frappe.throw(
                _("{0} already has an active plan ({1}). Complete or cancel it first.").format(
                    frappe.bold(self.member_name or self.member), other),
                title=_("Active plan exists"))
