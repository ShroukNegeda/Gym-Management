"""Tests for the bonus features: workout plans, body measurements and the door-access API.

Run with:  bench --site <site> run-tests --app gym_management
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from gym_management import door_api
from gym_management.tests import factories as f


class BonusTestCase(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.flags.gym_skip_invoice = True

    @classmethod
    def tearDownClass(cls):
        frappe.flags.gym_skip_invoice = False
        super().tearDownClass()


# ------------------------------------------------------------------ body measurements
class TestBodyMeasurement(BonusTestCase):
    def measurement(self, **values):
        member = values.pop("member", None) or f.make_member().name
        return frappe.get_doc({"doctype": "Body Measurement", "member": member, "measured_on": today(), **values})

    def test_bmi_is_calculated(self):
        doc = self.measurement(weight_kg=70, height_cm=175).insert()
        self.assertEqual(doc.bmi, 22.9)

    def test_bmi_empty_without_height(self):
        doc = self.measurement(weight_kg=70).insert()
        self.assertEqual(doc.bmi, 0)

    def test_needs_at_least_one_value(self):
        with self.assertRaises(frappe.ValidationError):
            self.measurement().insert()

    def test_future_date_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.measurement(weight_kg=70, measured_on=add_days(today(), 1)).insert()

    def test_out_of_range_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.measurement(weight_kg=7).insert()      # typo for 70
        with self.assertRaises(frappe.ValidationError):
            self.measurement(height_cm=1750).insert()   # typo for 175


# ------------------------------------------------------------------ workout plans
class TestWorkoutPlan(BonusTestCase):
    ROW = {"day": "Monday", "exercise": "Squat", "sets": 3, "reps": 10}

    def plan(self, member=None, exercises=None, **values):
        return frappe.get_doc({
            "doctype": "Workout Plan", "plan_title": f.uid("Plan "), "member": member or f.make_member().name,
            "start_date": today(), "exercises": [self.ROW] if exercises is None else exercises, **values})

    def test_plan_is_created(self):
        self.assertTrue(self.plan().insert().name.startswith("WP-"))

    def test_needs_an_exercise(self):
        with self.assertRaises(frappe.ValidationError):
            self.plan(exercises=[]).insert()

    def test_end_before_start_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.plan(end_date=add_days(today(), -1)).insert()

    def test_sets_without_reps_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.plan(exercises=[{"day": "Friday", "exercise": "Row", "sets": 3, "reps": 0}]).insert()

    def test_timed_exercise_without_sets_is_fine(self):
        self.plan(exercises=[{"day": "Friday", "exercise": "Treadmill 20 min"}]).insert()

    def test_only_one_active_plan_per_member(self):
        member = f.make_member().name
        first = self.plan(member=member).insert()
        with self.assertRaises(frappe.ValidationError):
            self.plan(member=member).insert()
        first.status = "Completed"
        first.save()
        self.plan(member=member).insert()  # allowed once the first one is completed

    def test_blacklisted_member_rejected(self):
        member = f.make_member()
        member.status = "Blacklisted"
        member.save()
        with self.assertRaises(frappe.ValidationError):
            self.plan(member=member.name).insert()


# ------------------------------------------------------------------ door controller API
class TestDoorApi(BonusTestCase):
    def active_member(self, **plan_kw):
        member = f.make_member()
        membership = f.make_membership(member.name, f.make_plan(**plan_kw).name)
        return member, membership

    def visits(self, member):
        return frappe.get_all("Gym Check In", filters={"member": member}, pluck="name")

    def test_allowed_member_is_checked_in(self):
        member, membership = self.active_member()
        res = door_api.check_access(member.name)
        self.assertTrue(res["allow"])
        self.assertEqual(res["membership"], membership.name)
        self.assertFalse(res["duplicate"])
        self.assertEqual(self.visits(member.name), [res["check_in"]])

    def test_repeated_scan_is_one_visit(self):
        member, _ = self.active_member()
        first = door_api.check_access(member.name)
        second = door_api.check_access(member.name)
        self.assertTrue(second["allow"] and second["duplicate"])
        self.assertEqual(second["check_in"], first["check_in"])
        self.assertEqual(len(self.visits(member.name)), 1)

    def test_unknown_member(self):
        res = door_api.check_access("MBR-DOES-NOT-EXIST")
        self.assertFalse(res["allow"])
        self.assertEqual(res["code"], "unknown_member")

    def test_member_without_membership_is_denied(self):
        member = f.make_member()
        res = door_api.check_access(member.name)
        self.assertFalse(res["allow"])
        self.assertEqual(res["code"], "none")
        self.assertEqual(self.visits(member.name), [])

    def test_frozen_member_is_denied(self):
        member, membership = self.active_member(max_freeze_days=10)
        membership.freeze(today(), add_days(today(), 3))
        res = door_api.check_access(member.name)
        self.assertFalse(res["allow"])
        self.assertEqual(res["code"], "frozen")

    def test_expired_member_is_denied(self):
        member = f.make_member()
        f.make_membership(member.name, f.make_plan().name, start_date=add_days(today(), -90))
        res = door_api.check_access(member.name)
        self.assertFalse(res["allow"])
        self.assertEqual(res["code"], "expired")

    def test_blacklisted_member_is_denied(self):
        member, _ = self.active_member()
        member.reload()
        member.status = "Blacklisted"
        member.save()
        res = door_api.check_access(member.name)
        self.assertFalse(res["allow"])
        self.assertEqual(res["code"], "blacklisted")

    def test_exit_closes_the_visit(self):
        member, _ = self.active_member()
        visit = door_api.check_access(member.name)["check_in"]
        res = door_api.check_access(member.name, direction="out")
        self.assertTrue(res["allow"])
        self.assertTrue(frappe.db.get_value("Gym Check In", visit, "check_out_time"))

    def test_exit_is_always_allowed(self):
        member = f.make_member()  # no membership at all
        self.assertTrue(door_api.check_access(member.name, direction="out")["allow"])

    def test_invalid_arguments(self):
        member, _ = self.active_member()
        with self.assertRaises(frappe.ValidationError):
            door_api.check_access(member.name, direction="sideways")
        with self.assertRaises(frappe.ValidationError):
            door_api.check_access(member.name, method="Fingerprint")

    def test_active_member_list(self):
        active, _ = self.active_member()
        frozen, ms = self.active_member(max_freeze_days=10)
        ms.freeze(today(), add_days(today(), 3))
        expired = f.make_member()
        f.make_membership(expired.name, f.make_plan().name, start_date=add_days(today(), -90))
        listed = {row["member"] for row in door_api.get_active_members()["members"]}
        self.assertIn(active.name, listed)
        self.assertNotIn(frozen.name, listed)
        self.assertNotIn(expired.name, listed)
