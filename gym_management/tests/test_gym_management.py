"""Run with:  bench --site <site> run-tests --app gym_management

Needs a site where the ERPNext setup wizard has been completed (a Company exists).
Most tests set ``frappe.flags.gym_skip_invoice`` so they do not depend on the chart of accounts;
the invoice test exercises the real Sales Invoice path and skips itself if accounting is not ready.
"""
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_months, getdate, today

from gym_management import utils
from gym_management.tests import factories as f


class GymTestCase(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.flags.gym_skip_invoice = True
        frappe.db.set_single_value("Gym Settings", {"enable_waitlist": 1, "cancellation_window_hours": 4, "no_show_limit": 3})
        cls.trainer = f.make_trainer()
        cls.room = f.make_room(capacity=10)

    @classmethod
    def tearDownClass(cls):
        frappe.flags.gym_skip_invoice = False
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        # tests in one class share a transaction: undo whatever a previous test changed in the settings
        frappe.db.set_single_value("Gym Settings", {"enable_waitlist": 1, "cancellation_window_hours": 4, "no_show_limit": 3})

    def session(self, capacity=2, **kw):
        # a fresh trainer and room per session: tests in one class share a transaction,
        # so sessions made by different tests must never clash on trainer/room/time
        trainer, room = f.make_trainer(), f.make_room(capacity=10)
        cls = f.make_class(trainer.name, room.name, capacity=capacity)
        return f.make_session(cls.name, capacity=capacity, **kw)

    def active_member(self, plan=None, **kw):
        member = f.make_member()
        f.make_membership(member.name, (plan or f.make_plan()).name, **kw)
        return member


class TestMembership(GymTestCase):
    def test_end_date_for_each_duration_type(self):
        start = getdate("2026-01-31")
        self.assertEqual(utils.compute_base_end_date(start, "Days", 30), getdate("2026-03-01"))
        self.assertEqual(utils.compute_base_end_date("2026-01-01", "Months", 1), getdate("2026-01-31"))
        self.assertEqual(utils.compute_base_end_date("2026-01-01", "Class Pack", 10, 90), getdate("2026-03-31"))

    def test_submit_calculates_end_date_and_activates(self):
        plan = f.make_plan(duration_type="Months", duration_value=3)
        ms = f.make_membership(f.make_member().name, plan.name)
        self.assertEqual(getdate(ms.end_date), getdate(add_days(add_months(today(), 3), -1)))
        self.assertEqual(ms.status, "Active")

    def test_only_one_membership_at_a_time(self):
        member, plan = f.make_member(), f.make_plan()
        f.make_membership(member.name, plan.name)
        with self.assertRaises(frappe.ValidationError):
            f.make_membership(member.name, plan.name)  # overlaps the first one

    def test_member_gets_customer(self):
        member = f.make_member()
        self.assertTrue(member.customer)
        self.assertEqual(frappe.db.get_value("Customer", member.customer, "customer_name"), member.member_name)

    def test_freeze_limit_and_end_date_extension(self):
        member, plan = f.make_member(), f.make_plan(max_freeze_days=10)
        ms = f.make_membership(member.name, plan.name)
        old_end = getdate(ms.end_date)

        ms.freeze(add_days(today(), 2), add_days(today(), 6))  # 5 days
        ms.reload()
        self.assertEqual(ms.total_freeze_days, 5)
        self.assertEqual(getdate(ms.end_date), add_days(old_end, 5))

        with self.assertRaises(frappe.ValidationError):  # 5 + 8 > 10
            ms.freeze(add_days(today(), 10), add_days(today(), 17))
        ms.reload()
        self.assertEqual(ms.total_freeze_days, 5)  # the rejected freeze was not stored

    def test_freeze_rules(self):
        ms = f.make_membership(f.make_member().name, f.make_plan(max_freeze_days=30).name)
        with self.assertRaises(frappe.ValidationError):  # to must be after from
            ms.freeze(add_days(today(), 5), add_days(today(), 5))
        ms.reload()
        with self.assertRaises(frappe.ValidationError):  # cannot start in the past
            ms.freeze(add_days(today(), -3), add_days(today(), 2))
        ms.reload()
        ms.freeze(add_days(today(), 2), add_days(today(), 6))
        ms.reload()
        with self.assertRaises(frappe.ValidationError):  # overlaps the first freeze
            ms.freeze(add_days(today(), 5), add_days(today(), 9))

    def test_plan_without_freeze_allowance_cannot_freeze(self):
        ms = f.make_membership(f.make_member().name, f.make_plan(max_freeze_days=0).name)
        with self.assertRaises(frappe.ValidationError):
            ms.freeze(add_days(today(), 1), add_days(today(), 3))

    def test_renew_is_idempotent(self):
        ms = f.make_membership(f.make_member().name, f.make_plan().name)
        first = ms.renew()
        self.assertEqual(ms.renew(), first)
        self.assertEqual(getdate(frappe.db.get_value("Gym Membership", first, "start_date")), add_days(ms.end_date, 1))


class TestBooking(GymTestCase):
    def test_capacity_and_waitlist(self):
        s = self.session(capacity=2)
        statuses = []
        for _ in range(3):
            m = self.active_member()
            statuses.append(frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": m.name}).insert().status)
        self.assertEqual(statuses, ["Booked", "Booked", "Waitlisted"])
        self.assertEqual(frappe.db.get_value("Class Session", s.name, "booked_count"), 2)

    def test_full_session_without_waitlist_is_rejected(self):
        frappe.db.set_single_value("Gym Settings", "enable_waitlist", 0)
        s = self.session(capacity=1)
        frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": self.active_member().name}).insert()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": self.active_member().name}).insert()

    def test_waitlist_promotion_on_cancellation(self):
        s = self.session(capacity=1, days_ahead=3)
        first, second = self.active_member(), self.active_member()
        b1 = frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": first.name}).insert()
        b2 = frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": second.name}).insert()
        self.assertEqual(b2.status, "Waitlisted")

        b1.status = "Cancelled"
        b1.save()
        self.assertEqual(frappe.db.get_value("Class Booking", b2.name, "status"), "Booked")
        self.assertEqual(frappe.db.get_value("Class Session", s.name, "booked_count"), 1)

    def test_earliest_waitlisted_is_promoted_first(self):
        s = self.session(capacity=1, days_ahead=3)
        a, b, c = self.active_member(), self.active_member(), self.active_member()
        ba = frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": a.name}).insert()
        bb = frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": b.name}).insert()
        bc = frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": c.name}).insert()
        ba.status = "Cancelled"
        ba.save()
        self.assertEqual(frappe.db.get_value("Class Booking", bb.name, "status"), "Booked")
        self.assertEqual(frappe.db.get_value("Class Booking", bc.name, "status"), "Waitlisted")

    def test_no_double_booking(self):
        s, m = self.session(), self.active_member()
        frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": m.name}).insert()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": m.name}).insert()

    def test_booking_needs_active_membership(self):
        s, m = self.session(), f.make_member()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": m.name}).insert()

    def test_membership_must_be_active_on_session_date(self):
        plan = f.make_plan(duration_type="Days", duration_value=3)
        m = self.active_member(plan=plan)
        far = self.session(days_ahead=10)  # membership ended long before
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Class Booking", "class_session": far.name, "member": m.name}).insert()

    def test_frozen_on_session_date_is_rejected(self):
        plan = f.make_plan(max_freeze_days=10)
        m = f.make_member()
        ms = f.make_membership(m.name, plan.name)
        ms.freeze(add_days(today(), 2), add_days(today(), 5))
        s = self.session(days_ahead=3)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": m.name}).insert()

    def test_class_pack_credits(self):
        plan = f.make_plan(duration_type="Class Pack", duration_value=2, classes_included=0)
        m = self.active_member(plan=plan)
        ms = utils.resolve_membership(m.name).membership
        self.assertEqual(frappe.db.get_value("Gym Membership", ms, "classes_remaining"), 2)

        s1, s2, s3 = self.session(days_ahead=1), self.session(days_ahead=2), self.session(days_ahead=3)
        b1 = frappe.get_doc({"doctype": "Class Booking", "class_session": s1.name, "member": m.name}).insert()
        frappe.get_doc({"doctype": "Class Booking", "class_session": s2.name, "member": m.name}).insert()
        self.assertEqual(frappe.db.get_value("Gym Membership", ms, "classes_remaining"), 0)
        with self.assertRaises(frappe.ValidationError):  # pack used up
            frappe.get_doc({"doctype": "Class Booking", "class_session": s3.name, "member": m.name}).insert()

        b1.status = "Cancelled"  # cancelled > 4h before: credit comes back
        b1.save()
        self.assertEqual(frappe.db.get_value("Gym Membership", ms, "classes_remaining"), 1)

    def test_cannot_reopen_cancelled_booking(self):
        s, m = self.session(days_ahead=2), self.active_member()
        b = frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": m.name}).insert()
        b.status = "Cancelled"
        b.save()
        b.status = "Booked"
        with self.assertRaises(frappe.ValidationError):
            b.save()

    def test_cancelling_a_session_cancels_bookings_and_refunds(self):
        s = self.session(capacity=2, days_ahead=2)
        m = self.active_member()
        b = frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": m.name}).insert()
        s.reload()
        s.status = "Cancelled"
        s.save()
        self.assertEqual(frappe.db.get_value("Class Booking", b.name, "status"), "Cancelled")
        self.assertEqual(frappe.db.get_value("Class Session", s.name, "booked_count"), 0)


class TestSession(GymTestCase):
    def test_end_time_and_calendar_fields(self):
        cls = f.make_class(self.trainer.name, self.room.name, capacity=5, duration=45)
        s = f.make_session(cls.name, capacity=5, start_time="09:30:00")
        self.assertEqual(str(s.end_time), "10:15:00")
        self.assertTrue(s.starts_on and s.ends_on)

    def test_room_and_trainer_overlap(self):
        trainer = f.make_trainer()
        room = f.make_room()
        cls = f.make_class(trainer.name, room.name)
        f.make_session(
            cls.name,
            trainer=trainer.name,
            room=room.name,
            start_time="10:00:00",
            days_ahead=2,
        )
        with self.assertRaises(frappe.ValidationError):
            f.make_session(
                cls.name,
                trainer=trainer.name,
                room=room.name,
                start_time="10:00:00",
                days_ahead=2,
            )

    def test_capacity_cannot_exceed_room(self):
        small = f.make_room(capacity=3)
        cls = f.make_class(self.trainer.name, small.name)
        with self.assertRaises(frappe.ValidationError):
            f.make_session(cls.name, room=small.name, capacity=5)



class TestCheckIn(GymTestCase):
    def check_in(self, member):
        return frappe.get_doc({"doctype": "Gym Check In", "member": member}).insert()

    def test_active_member_can_check_in(self):
        m = self.active_member()
        self.assertTrue(self.check_in(m.name).membership)

    def test_no_membership_blocked(self):
        with self.assertRaises(frappe.ValidationError):
            self.check_in(f.make_member().name)

    def test_expired_member_blocked(self):
        plan = f.make_plan(duration_type="Months", duration_value=1)
        m = self.active_member(plan=plan, start_date=add_days(today(), -90))
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.check_in(m.name)
        self.assertIn("expired", str(ctx.exception).lower())

    def test_frozen_member_blocked(self):
        m = f.make_member()
        ms = f.make_membership(m.name, f.make_plan(max_freeze_days=10).name)
        ms.freeze(today(), add_days(today(), 3))
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.check_in(m.name)
        self.assertIn("frozen", str(ctx.exception).lower())

    def test_cancelled_membership_blocked(self):
        m = f.make_member()
        ms = f.make_membership(m.name, f.make_plan().name)
        ms.cancel()
        with self.assertRaises(frappe.ValidationError):
            self.check_in(m.name)

    def test_blacklisted_member_blocked(self):
        m = self.active_member()
        m.reload()
        m.status = "Blacklisted"
        m.save()
        with self.assertRaises(frappe.ValidationError):
            self.check_in(m.name)

    def test_check_in_marks_booking_attended(self):
        m = self.active_member()
        # a same-day session must still be in the future, so it is placed late in the evening
        if frappe.utils.now_datetime().hour >= 21:
            self.skipTest("too late in the day to create a same-day session")
        cls = f.make_class(self.trainer.name, self.room.name, capacity=5, duration=30)
        s = f.make_session(cls.name, capacity=5, days_ahead=0, start_time="23:15:00")
        b = frappe.get_doc({"doctype": "Class Booking", "class_session": s.name, "member": m.name}).insert()
        frappe.get_doc({"doctype": "Gym Check In", "member": m.name, "class_booking": b.name}).insert()
        self.assertEqual(frappe.db.get_value("Class Booking", b.name, "status"), "Attended")


class TestInvoice(FrappeTestCase):
    def test_invoice_created_once_even_if_retried(self):
        company = f.default_company()
        if not company:
            self.skipTest("no company: complete the ERPNext setup wizard first")
        frappe.flags.gym_skip_invoice = False
        try:
            ms = f.make_membership(f.make_member().name, f.make_plan(price=250).name)
        except Exception as e:  # chart of accounts / price list not ready on this site
            self.skipTest(f"accounting not ready: {e}")
        invoices = frappe.get_all("Sales Invoice", filters={"gym_membership": ms.name, "docstatus": 1})
        self.assertEqual(len(invoices), 1)
        self.assertEqual(frappe.db.get_value("Gym Membership", ms.name, "sales_invoice"), invoices[0].name)

        again = ms.create_invoice()  # simulates a retried submit
        self.assertEqual(again, invoices[0].name)
        self.assertEqual(len(frappe.get_all("Sales Invoice", filters={"gym_membership": ms.name, "docstatus": ["!=", 2]})), 1)

        ms.cancel()  # cancelling the membership cancels its invoice
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoices[0].name, "docstatus"), 2)
