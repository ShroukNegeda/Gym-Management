"""Tests for personal-training bookings and SMS notifications.

Run with:  bench --site <site> run-tests --app gym_management
"""
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from gym_management import personal_training as pt
from gym_management import pt_api, sms, utils
from gym_management.tests import factories as f

DAY = add_days(today(), 7)          # always in the future, always the same weekday as today
WEEKDAY = pt.weekday_name(DAY)


class PtTestCase(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.flags.gym_skip_invoice = True

    @classmethod
    def tearDownClass(cls):
        frappe.flags.gym_skip_invoice = False
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        frappe.db.set_single_value("Gym Settings", "enable_sms_notifications", 0)

    # --- helpers
    def trainer_with_hours(self, start="10:00:00", end="13:00:00", day=None):
        trainer = f.make_trainer()
        self.availability(trainer.name, start, end, day)
        return trainer

    def availability(self, trainer, start="10:00:00", end="13:00:00", day=None):
        return frappe.get_doc({"doctype": "Trainer Availability", "trainer": trainer, "day_of_week": day or WEEKDAY,
                               "from_time": start, "to_time": end, "is_active": 1}).insert()

    def member(self):
        member = f.make_member()
        f.make_membership(member.name, f.make_plan().name)
        return member

    def session_doc(self, member, trainer, start="11:00:00", duration=60, date=None):
        return frappe.get_doc({"doctype": "Personal Training Session", "member": member, "trainer": trainer,
                               "session_date": date or DAY, "start_time": start, "duration_minutes": duration})


# ------------------------------------------------------------------ availability
class TestTrainerAvailability(PtTestCase):
    def test_to_time_must_be_after_from_time(self):
        trainer = f.make_trainer()
        with self.assertRaises(frappe.ValidationError):
            self.availability(trainer.name, "12:00:00", "12:00:00")
        with self.assertRaises(frappe.ValidationError):
            self.availability(trainer.name, "12:00:00", "10:00:00")

    def test_overlapping_windows_rejected(self):
        trainer = f.make_trainer()
        self.availability(trainer.name, "10:00:00", "13:00:00")
        with self.assertRaises(frappe.ValidationError):
            self.availability(trainer.name, "12:00:00", "15:00:00")

    def test_adjacent_and_other_day_windows_allowed(self):
        trainer = f.make_trainer()
        self.availability(trainer.name, "10:00:00", "13:00:00")
        self.availability(trainer.name, "13:00:00", "16:00:00")                                   # touching
        self.availability(trainer.name, "10:00:00", "13:00:00", day=pt.weekday_name(add_days(DAY, 1)))  # other day


# ------------------------------------------------------------------ free slots
class TestFreeSlots(PtTestCase):
    def test_compute_free_slots_is_a_pure_function(self):
        self.assertEqual(pt.compute_free_slots([(600, 780)], [], 60), [600, 630, 660, 690, 720])
        self.assertEqual(pt.compute_free_slots([(600, 780)], [(660, 720)], 60), [600, 720])   # touching is fine
        self.assertEqual(pt.compute_free_slots([(600, 780)], [], 90), [600, 630, 660, 690])
        self.assertEqual(pt.compute_free_slots([(600, 780)], [], 60, not_before=640), [660, 690, 720])
        self.assertEqual(pt.compute_free_slots([], [], 60), [])

    def test_slots_for_a_trainer(self):
        trainer = self.trainer_with_hours()
        self.assertEqual(pt.get_free_slots(trainer.name, DAY, 60),
                         ["10:00:00", "10:30:00", "11:00:00", "11:30:00", "12:00:00"])

    def test_booked_session_removes_overlapping_slots(self):
        trainer = self.trainer_with_hours()
        self.session_doc(self.member().name, trainer.name, "11:00:00").insert()
        self.assertEqual(pt.get_free_slots(trainer.name, DAY, 60), ["10:00:00", "12:00:00"])

    def test_group_class_removes_slots(self):
        trainer = self.trainer_with_hours()
        room = f.make_room()
        cls = f.make_class(trainer.name, room.name, capacity=5, duration=60)
        f.make_session(cls.name, capacity=5, days_ahead=7, start_time="10:30:00")
        self.assertEqual(pt.get_free_slots(trainer.name, DAY, 60), ["11:30:00", "12:00:00"])

    def test_no_hours_or_past_date_gives_no_slots(self):
        self.assertEqual(pt.get_free_slots(f.make_trainer().name, DAY, 60), [])
        trainer = self.trainer_with_hours()
        self.assertEqual(pt.get_free_slots(trainer.name, add_days(today(), -1), 60), [])


# ------------------------------------------------------------------ bookings
class TestPersonalTraining(PtTestCase):
    def test_booking_succeeds(self):
        trainer, member = self.trainer_with_hours(), self.member()
        doc = self.session_doc(member.name, trainer.name, "11:00:00", 60).insert()
        self.assertEqual(doc.status, "Booked")
        self.assertEqual(str(doc.end_time), "12:00:00")
        self.assertTrue(doc.membership)
        self.assertTrue(doc.name.startswith("PT-"))

    def test_outside_working_hours_rejected(self):
        trainer, member = self.trainer_with_hours("10:00:00", "13:00:00"), self.member()
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(member.name, trainer.name, "09:00:00").insert()       # before the window
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(member.name, trainer.name, "12:30:00").insert()       # ends after the window

    def test_trainer_cannot_be_double_booked(self):
        trainer = self.trainer_with_hours()
        self.session_doc(self.member().name, trainer.name, "11:00:00").insert()
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(self.member().name, trainer.name, "11:30:00").insert()
        self.session_doc(self.member().name, trainer.name, "12:00:00").insert()    # back to back is fine

    def test_member_cannot_be_in_two_places(self):
        first, second = self.trainer_with_hours(), self.trainer_with_hours()
        member = self.member()
        self.session_doc(member.name, first.name, "11:00:00").insert()
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(member.name, second.name, "11:30:00").insert()

    def test_group_class_blocks_personal_training(self):
        trainer = self.trainer_with_hours()
        cls = f.make_class(trainer.name, f.make_room().name, capacity=5, duration=60)
        f.make_session(cls.name, capacity=5, days_ahead=7, start_time="11:00:00")
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(self.member().name, trainer.name, "11:30:00").insert()

    def test_personal_training_blocks_group_class(self):
        trainer = self.trainer_with_hours()
        self.session_doc(self.member().name, trainer.name, "11:00:00").insert()
        cls = f.make_class(trainer.name, f.make_room().name, capacity=5, duration=60)
        with self.assertRaises(frappe.ValidationError):
            f.make_session(cls.name, capacity=5, days_ahead=7, start_time="11:30:00")

    def test_membership_is_required(self):
        trainer = self.trainer_with_hours()
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(f.make_member().name, trainer.name).insert()

    def test_membership_must_be_valid_on_the_session_date(self):
        trainer = self.trainer_with_hours()
        member = f.make_member()
        f.make_membership(member.name, f.make_plan(duration_type="Days", duration_value=3).name)   # over long before DAY
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(member.name, trainer.name).insert()

    def test_inactive_trainer_rejected(self):
        trainer = self.trainer_with_hours()
        member = self.member()
        trainer.is_active = 0
        trainer.save()
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(member.name, trainer.name).insert()

    def test_duration_limits(self):
        trainer, member = self.trainer_with_hours(), self.member()
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(member.name, trainer.name, duration=10).insert()
        with self.assertRaises(frappe.ValidationError):
            self.session_doc(member.name, trainer.name, duration=240).insert()

    def test_cancel_frees_the_slot(self):
        trainer = self.trainer_with_hours()
        doc = self.session_doc(self.member().name, trainer.name, "11:00:00").insert()
        doc.status = "Cancelled"
        doc.save()
        self.assertTrue(doc.cancelled_on)
        self.session_doc(self.member().name, trainer.name, "11:00:00").insert()    # same slot, new member

    def test_booked_time_cannot_be_edited(self):
        trainer = self.trainer_with_hours()
        doc = self.session_doc(self.member().name, trainer.name, "11:00:00").insert()
        doc.start_time = "12:00:00"
        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_future_session_cannot_be_completed(self):
        trainer = self.trainer_with_hours()
        doc = self.session_doc(self.member().name, trainer.name).insert()
        doc.status = "Completed"
        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_cancelled_session_cannot_be_reopened(self):
        trainer = self.trainer_with_hours()
        doc = self.session_doc(self.member().name, trainer.name).insert()
        doc.status = "Cancelled"
        doc.save()
        doc.status = "Booked"
        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_api_round_trip(self):
        trainer, member = self.trainer_with_hours(), self.member()
        slots = pt_api.get_trainer_slots(trainer.name, DAY, 60)["slots"]
        self.assertIn("11:00:00", slots)
        booked = pt_api.book_personal_training(member.name, trainer.name, DAY, "11:00:00", 60)
        self.assertEqual(booked["status"], "Booked")
        self.assertNotIn("11:00:00", pt_api.get_trainer_slots(trainer.name, DAY, 60)["slots"])
        cancelled = pt_api.cancel_personal_training(booked["session"])
        self.assertEqual(cancelled["status"], "Cancelled")
        self.assertIn("11:00:00", pt_api.get_trainer_slots(trainer.name, DAY, 60)["slots"])


# ------------------------------------------------------------------ SMS
class TestSms(PtTestCase):
    def enable(self, country_code="20"):
        frappe.db.set_single_value("Gym Settings", {"enable_sms_notifications": 1, "sms_country_code": country_code})

    def test_normalize_number(self):
        self.assertEqual(sms.normalize_number("+20 10 1234 5678"), "201012345678")
        self.assertEqual(sms.normalize_number("01012345678", "20"), "201012345678")
        self.assertEqual(sms.normalize_number("01012345678", "+20"), "201012345678")
        self.assertEqual(sms.normalize_number("0020 101 234 5678"), "201012345678")
        self.assertEqual(sms.normalize_number("01012345678"), "01012345678")       # no country code configured
        self.assertIsNone(sms.normalize_number(""))
        self.assertIsNone(sms.normalize_number(None))
        self.assertIsNone(sms.normalize_number("abc"))
        self.assertIsNone(sms.normalize_number("12345"))                           # too short

    def test_sms_is_queued_when_enabled(self):
        self.enable()
        member = f.make_member()                                                   # factory phone: 01000000000
        with patch("gym_management.sms.frappe.enqueue") as enqueue, \
                patch("gym_management.sms.sms_gateway_configured", return_value=True):
            utils.notify_member(member.name, "Spot confirmed", "Long e-mail body")
        self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(enqueue.call_args.kwargs["receivers"], ["201000000000"])
        self.assertEqual(enqueue.call_args.kwargs["text"], "Spot confirmed")        # subject, not the long body
        self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])

    def test_custom_sms_text(self):
        self.enable()
        member = f.make_member()
        with patch("gym_management.sms.frappe.enqueue") as enqueue, \
                patch("gym_management.sms.sms_gateway_configured", return_value=True):
            utils.notify_member(member.name, "Subject", "Body", sms="Short text")
        self.assertEqual(enqueue.call_args.kwargs["text"], "Short text")

    def test_nothing_is_sent_when_disabled(self):
        member = f.make_member()
        with patch("gym_management.sms.frappe.enqueue") as enqueue, \
                patch("gym_management.sms.sms_gateway_configured", return_value=True):
            utils.notify_member(member.name, "Subject", "Body")
        enqueue.assert_not_called()

    def test_nothing_is_sent_without_a_gateway(self):
        self.enable()
        member = f.make_member()
        with patch("gym_management.sms.frappe.enqueue") as enqueue, \
                patch("gym_management.sms.sms_gateway_configured", return_value=False):
            utils.notify_member(member.name, "Subject", "Body")
        enqueue.assert_not_called()

    def test_member_without_a_phone_is_skipped(self):
        self.enable()
        member = f.make_member()
        frappe.db.set_value("Gym Member", member.name, "phone", "")
        with patch("gym_management.sms.frappe.enqueue") as enqueue, \
                patch("gym_management.sms.sms_gateway_configured", return_value=True):
            utils.notify_member(member.name, "Subject", "Body")
        enqueue.assert_not_called()

    def test_sms_still_goes_out_without_an_email(self):
        self.enable()
        member = f.make_member()
        frappe.db.set_value("Gym Member", member.name, "email", "")
        with patch("gym_management.sms.frappe.enqueue") as enqueue, \
                patch("gym_management.sms.sms_gateway_configured", return_value=True):
            utils.notify_member(member.name, "Subject", "Body")
        self.assertEqual(enqueue.call_count, 1)

    def test_a_failing_sms_never_breaks_the_caller(self):
        self.enable()
        member = f.make_member()
        with patch("gym_management.sms.send_member_sms", side_effect=RuntimeError("gateway down")):
            utils.notify_member(member.name, "Subject", "Body")                    # must not raise

    def test_personal_training_booking_sends_an_sms(self):
        self.enable()
        trainer, member = self.trainer_with_hours(), self.member()
        with patch("gym_management.sms.frappe.enqueue") as enqueue, \
                patch("gym_management.sms.sms_gateway_configured", return_value=True):
            doc = self.session_doc(member.name, trainer.name, "11:00:00").insert()
            booked_texts = [c.kwargs.get("text") for c in enqueue.call_args_list]
            doc.status = "Cancelled"
            doc.save()
            all_texts = [c.kwargs.get("text") for c in enqueue.call_args_list]
        self.assertTrue(any(t and t.startswith("PT booked") for t in booked_texts))
        self.assertTrue(any(t and t.startswith("PT cancelled") for t in all_texts))
