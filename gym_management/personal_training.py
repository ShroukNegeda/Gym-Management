"""Scheduling rules for 1:1 personal training, shared by the DocType, the API and Class Session.

A trainer works in weekly *availability windows* (Trainer Availability). A session is valid when it
fits inside a window and does not overlap another personal-training session of the trainer, another
session of the member, or one of the trainer's group classes.
"""
import frappe
from frappe import _
from frappe.utils import cint, get_time, getdate, now_datetime, today

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SLOT_STEP_MINUTES = 30
MIN_DURATION, MAX_DURATION, DEFAULT_DURATION = 15, 180, 60


# ------------------------------------------------------------------ small helpers
def to_minutes(value):
    """Time / 'HH:MM:SS' / timedelta -> minutes since midnight."""
    t = get_time(value)
    return t.hour * 60 + t.minute


def to_time_str(minutes):
    return "%02d:%02d:00" % divmod(minutes, 60)


def weekday_name(date):
    return WEEKDAYS[getdate(date).weekday()]


# ------------------------------------------------------------------ availability & free slots
def get_windows(trainer, date):
    """[(start_minute, end_minute)] the trainer works on that date."""
    rows = frappe.get_all(
        "Trainer Availability",
        filters={"trainer": trainer, "day_of_week": weekday_name(date), "is_active": 1},
        fields=["from_time", "to_time"],
    )
    return [(to_minutes(r.from_time), to_minutes(r.to_time)) for r in rows]


def busy_intervals(trainer, date):
    """[(start_minute, end_minute)] already taken: booked 1:1 sessions and group classes."""
    rows = frappe.db.sql(
        """select start_time, end_time from `tabPersonal Training Session`
               where trainer=%(t)s and session_date=%(d)s and status='Booked'
           union all
           select start_time, end_time from `tabClass Session`
               where trainer=%(t)s and session_date=%(d)s and status!='Cancelled'""",
        {"t": trainer, "d": getdate(date)},
    )
    return [(to_minutes(s), to_minutes(e)) for s, e in rows]


def compute_free_slots(windows, busy, duration, not_before=None):
    """Pure function: start minutes (every SLOT_STEP_MINUTES) that fit a window and clash with nothing."""
    slots = set()
    for window_start, window_end in windows:
        start = window_start
        while start + duration <= window_end:
            end = start + duration
            free = not any(start < busy_end and end > busy_start for busy_start, busy_end in busy)
            if free and (not_before is None or start > not_before):
                slots.add(start)
            start += SLOT_STEP_MINUTES
    return sorted(slots)


def get_free_slots(trainer, date, duration=DEFAULT_DURATION):
    date = getdate(date)
    duration = cint(duration) or DEFAULT_DURATION
    if date < getdate(today()):
        return []
    not_before = None
    if date == getdate(today()):
        now = now_datetime()
        not_before = now.hour * 60 + now.minute
    slots = compute_free_slots(get_windows(trainer, date), busy_intervals(trainer, date), duration, not_before)
    return [to_time_str(s) for s in slots]


# ------------------------------------------------------------------ validation
def assert_within_availability(trainer, date, start_time, end_time):
    start, end = to_minutes(start_time), to_minutes(end_time)
    if not any(ws <= start and end <= we for ws, we in get_windows(trainer, date)):
        frappe.throw(
            _("{0} is not available on {1} between {2} and {3}.").format(
                frappe.bold(trainer), weekday_name(date), str(get_time(start_time))[:5], str(get_time(end_time))[:5]),
            title=_("Outside working hours"))


def assert_no_conflict(trainer, member, date, start_time, end_time, exclude=None):
    """Raise if the trainer or the member is busy. Uses locking reads (see DECISIONS.md R4): the caller
    has locked the trainer row, so two requests for the same slot are processed one after the other
    and the second one sees the first one's booking."""
    params = {
        "trainer": trainer, "member": member, "date": getdate(date),
        "start": str(get_time(start_time)), "end": str(get_time(end_time)), "name": exclude or "",
    }
    overlap = "session_date=%(date)s and status='Booked' and name!=%(name)s and start_time < %(end)s and end_time > %(start)s"

    taken = frappe.db.sql(
        f"select name from `tabPersonal Training Session` where trainer=%(trainer)s and {overlap} limit 1 for update", params)
    if taken:
        frappe.throw(_("Trainer {0} is already booked at this time: {1}").format(frappe.bold(trainer), taken[0][0]),
                     title=_("Slot taken"))

    busy_member = frappe.db.sql(
        f"select name from `tabPersonal Training Session` where member=%(member)s and {overlap} limit 1 for update", params)
    if busy_member:
        frappe.throw(_("{0} already has a personal training session at this time: {1}").format(
            frappe.bold(member), busy_member[0][0]), title=_("Member busy"))

    group = frappe.db.sql(
        """select name from `tabClass Session`
           where trainer=%(trainer)s and session_date=%(date)s and status!='Cancelled'
             and start_time < %(end)s and end_time > %(start)s limit 1""", params)
    if group:
        frappe.throw(_("Trainer {0} is teaching a group class at this time: {1}").format(
            frappe.bold(trainer), group[0][0]), title=_("Slot taken"))


def check_class_session_conflict(session):
    """Called from Class Session.validate: a group class must not be scheduled over a booked 1:1 session."""
    if session.status == "Cancelled" or not session.trainer:
        return
    clash = frappe.db.sql(
        """select name from `tabPersonal Training Session`
           where trainer=%(t)s and session_date=%(d)s and status='Booked'
             and start_time < %(e)s and end_time > %(s)s limit 1""",
        {"t": session.trainer, "d": getdate(session.session_date),
         "s": str(get_time(session.start_time)), "e": str(get_time(session.end_time))},
    )
    if clash:
        frappe.throw(_("Trainer {0} has a personal training session at this time: {1}").format(
            frappe.bold(session.trainer), clash[0][0]), title=_("Schedule conflict"))
