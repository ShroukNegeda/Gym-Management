"""Booking service layer: spot accounting and waitlist promotion."""
import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from gym_management import utils


def apply_booked(booking):
    """A booking just became (or was created as) Booked: take a class credit and a spot."""
    utils.consume_credit(booking.membership)
    utils.adjust_session_counter(booking.class_session, 1)


def release_spot(booking, refund_credit=True):
    """A spot-occupying booking was cancelled/deleted: free the spot, optionally refund the credit."""
    utils.lock_session(booking.class_session)
    utils.adjust_session_counter(booking.class_session, -1)
    if refund_credit and booking.membership:
        utils.release_credit(booking.membership)


def hours_until_session(session_name):
    starts_on = frappe.db.get_value("Class Session", session_name, "starts_on")
    return (get_datetime(starts_on) - now_datetime()).total_seconds() / 3600


def promote_waitlist(session_name):
    """Fill free spots from the waitlist, earliest waitlisted booking first."""
    session = utils.lock_session(session_name)
    if session.status != "Scheduled":
        return []
    spots = session.capacity - session.booked_count
    if spots <= 0:
        return []

    waiting = frappe.db.sql(
        """select name from `tabClass Booking`
           where class_session=%s and status='Waitlisted'
           order by booked_on asc, creation asc for update""",
        session_name, as_dict=True,
    )
    promoted = []
    for row in waiting:
        if spots <= 0:
            break
        booking = frappe.get_doc("Class Booking", row.name)
        res = utils.resolve_membership(booking.member, session.session_date)
        if not res.membership or not utils.has_credit(res.membership):
            continue  # not eligible any more; stays on the waitlist
        booking.flags.in_waitlist_promotion = True
        booking.membership = res.membership
        booking.status = "Booked"
        booking.save(ignore_permissions=True)
        spots -= 1
        promoted.append(booking.name)
        utils.notify_member(
            booking.member,
            _("You are in! Spot confirmed for {0}").format(booking.class_session),
            _("A spot opened up and your waitlisted booking {0} is now confirmed.").format(booking.name),
        )
    return promoted
