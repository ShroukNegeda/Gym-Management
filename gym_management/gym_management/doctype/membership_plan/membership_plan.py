import frappe
from frappe import _
from frappe.model.document import Document

from gym_management import utils


class MembershipPlan(Document):
    def validate(self):
        if (self.duration_value or 0) <= 0:
            frappe.throw(_("Duration Value must be greater than zero."))
        if (self.price or 0) < 0 or (self.classes_included or 0) < 0 or (self.max_freeze_days or 0) < 0:
            frappe.throw(_("Price, Classes Included and Max Freeze Days cannot be negative."))
        if self.duration_type == "Class Pack" and (self.validity_days or 0) <= 0:
            frappe.throw(_("Validity Days is required for a Class Pack."))
        if self.item:
            self.validate_item()
        else:
            self.create_item()

    def on_update(self):
        self.sync_item_price()
        self.sync_item_status()

    # -------------------------------------------------------------
    def validate_item(self):
        if frappe.db.get_value("Item", self.item, "is_stock_item"):
            frappe.throw(_("Item {0} is a stock item. A Membership Plan needs a non-stock service Item.").format(self.item))

    def create_item(self):
        settings = utils.get_settings()
        if frappe.db.exists("Item", self.plan_name):
            self.item = self.plan_name
            self.validate_item()
            return
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": self.plan_name,
            "item_name": self.plan_name,
            "item_group": settings.default_item_group or "Services",
            "stock_uom": "Nos",
            "is_stock_item": 0,
            "is_sales_item": 1,
            "is_purchase_item": 0,
            "include_item_in_manufacturing": 0,
            "description": _("Gym membership plan: {0}").format(self.plan_name),
        })
        if settings.default_income_account:
            company = frappe.db.get_value("Account", settings.default_income_account, "company")
            item.append("item_defaults", {"company": company, "income_account": settings.default_income_account})
        item.insert(ignore_permissions=True)
        self.item = item.name

    def sync_item_price(self):
        price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list") or "Standard Selling"
        if not frappe.db.exists("Price List", price_list):
            frappe.msgprint(_("Price List {0} not found; Item Price was not synced.").format(price_list), indicator="orange", alert=True)
            return
        existing = frappe.db.get_value("Item Price", {"item_code": self.item, "price_list": price_list, "selling": 1})
        if existing:
            if frappe.db.get_value("Item Price", existing, "price_list_rate") != self.price:
                frappe.db.set_value("Item Price", existing, "price_list_rate", self.price)
            return
        frappe.get_doc({
            "doctype": "Item Price",
            "item_code": self.item,
            "price_list": price_list,
            "selling": 1,
            "price_list_rate": self.price,
            "currency": frappe.db.get_value("Price List", price_list, "currency"),
        }).insert(ignore_permissions=True)

    def sync_item_status(self):
        """Disable the backing Item only when no active plan still uses it."""
        in_use = frappe.db.exists("Membership Plan", {"item": self.item, "is_active": 1})
        disabled = 0 if in_use else 1
        if frappe.db.get_value("Item", self.item, "disabled") != disabled:
            frappe.db.set_value("Item", self.item, "disabled", disabled)
