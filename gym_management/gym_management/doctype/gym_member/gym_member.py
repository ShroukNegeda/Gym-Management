import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today, validate_email_address, validate_phone_number

from gym_management import utils


class GymMember(Document):
    def validate(self):
        self.validate_contact_details()
        self.ensure_customer()
        # system-managed: never trust the value that came from the client
        self.active_membership = utils.resolve_membership(self.name).current if not self.is_new() else None

    def after_insert(self):
        self.create_contact()

    # -------------------------------------------------------------
    def validate_contact_details(self):
        if self.email:
            validate_email_address(self.email, throw=True)
        for phone in (self.phone, self.emergency_contact_phone):
            if phone:
                validate_phone_number(phone, throw=True)
        if self.date_of_birth and getdate(self.date_of_birth) > getdate(today()):
            frappe.throw(_("Date of Birth cannot be in the future."))

    def ensure_customer(self):
        """One Gym Member <-> one Customer; the Customer is created on first save."""
        if self.customer:
            clash = frappe.db.exists("Gym Member", {"customer": self.customer, "name": ["!=", self.name]})
            if clash:
                frappe.throw(_("Customer {0} is already linked to Gym Member {1}.").format(self.customer, clash))
            return
        customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": self.member_name,
            "customer_type": "Individual",
            "customer_group": frappe.db.get_single_value("Selling Settings", "customer_group") or "Individual",
            "territory": frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
        })
        customer.insert(ignore_permissions=True)
        self.customer = customer.name

    def create_contact(self):
        """Contact details live in ERPNext's Contact, linked to the Customer via Dynamic Link."""
        if not (self.email or self.phone):
            return
        if frappe.db.exists("Dynamic Link", {"parenttype": "Contact", "link_doctype": "Customer", "link_name": self.customer}):
            return
        contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": self.member_name,
            "links": [{"link_doctype": "Customer", "link_name": self.customer}],
        })
        if self.email:
            contact.add_email(self.email, is_primary=True)
        if self.phone:
            contact.add_phone(self.phone, is_primary_mobile_no=True)
        contact.insert(ignore_permissions=True)
