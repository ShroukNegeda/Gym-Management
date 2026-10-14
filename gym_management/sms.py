"""Optional SMS notifications.

Messages go through Frappe's own *SMS Settings* (any HTTP SMS gateway). Nothing is sent unless
"Enable SMS Notifications" is ticked in Gym Settings AND an SMS gateway URL is configured, so
a site without a gateway behaves exactly as before. Sending happens in a background job after
the transaction commits, so a slow or failing gateway can never block or roll back a booking.
"""
import re

import frappe
from frappe.utils import cint

MAX_SMS_LENGTH = 320


def normalize_number(raw, country_code=None):
    """Digits only, international format without '+'. Returns None if it cannot be a phone number.

    "+20 10 1234 5678" -> "201012345678"; "01012345678" with country_code "20" -> "201012345678".
    """
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and country_code:
        digits = re.sub(r"\D", "", country_code) + digits[1:]
    return digits if 8 <= len(digits) <= 15 else None


def sms_enabled():
    return bool(cint(frappe.db.get_single_value("Gym Settings", "enable_sms_notifications")))


def sms_gateway_configured():
    return bool(frappe.db.get_single_value("SMS Settings", "sms_gateway_url"))


def send_member_sms(member, text):
    """Queue ``text`` as an SMS to the member. Returns True when a message was queued."""
    if not text or not sms_enabled() or not sms_gateway_configured():
        return False
    phone = frappe.db.get_value("Gym Member", member, "phone")
    number = normalize_number(phone, frappe.db.get_single_value("Gym Settings", "sms_country_code"))
    if not number:
        return False
    frappe.enqueue(
        "gym_management.sms.deliver",
        queue="short", receivers=[number], text=text[:MAX_SMS_LENGTH], enqueue_after_commit=True,
    )
    return True


def deliver(receivers, text):
    """Background job: hand the message to the configured gateway."""
    from frappe.core.doctype.sms_settings.sms_settings import send_sms

    try:
        send_sms(receivers, text, success_msg=False)
    except Exception:
        frappe.log_error(title="Gym Management: SMS delivery failed")
