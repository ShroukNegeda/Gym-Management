"""Row-level permissions: a Trainer (without a staff role) only sees own sessions."""
import frappe

from gym_management.utils import get_user_trainers, is_trainer_only


def _trainer_list(user):
    trainers = get_user_trainers(user)
    return ", ".join(frappe.db.escape(t) for t in trainers) if trainers else None


def class_session_query(user=None):
    user = user or frappe.session.user
    if not is_trainer_only(user):
        return ""
    trainers = _trainer_list(user)
    if not trainers:
        return "1=0"
    return f"`tabClass Session`.trainer in ({trainers})"


def class_booking_query(user=None):
    user = user or frappe.session.user
    if not is_trainer_only(user):
        return ""
    trainers = _trainer_list(user)
    if not trainers:
        return "1=0"
    return (
        "`tabClass Booking`.class_session in "
        f"(select name from `tabClass Session` where trainer in ({trainers}))"
    )


def class_session_has_permission(doc, ptype=None, user=None, **kwargs):
    user = user or frappe.session.user
    if not is_trainer_only(user):
        return None  # defer to role permissions
    return doc.trainer in get_user_trainers(user)


def class_booking_has_permission(doc, ptype=None, user=None, **kwargs):
    user = user or frappe.session.user
    if not is_trainer_only(user):
        return None
    trainer = frappe.db.get_value("Class Session", doc.class_session, "trainer")
    return trainer in get_user_trainers(user)
