import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ROLES = ["Gym Manager", "Front Desk", "Trainer"]
ITEM_GROUP = "Gym Services"

CUSTOM_FIELDS = {
    "Sales Invoice": [
        {
            "fieldname": "gym_section",
            "label": "Gym",
            "fieldtype": "Section Break",
            "insert_after": "tax_id",
            "collapsible": 1,
        },
        {
            "fieldname": "gym_membership",
            "label": "Gym Membership",
            "fieldtype": "Link",
            "options": "Gym Membership",
            "read_only": 1,
            "no_copy": 1,
            "search_index": 1,
            "insert_after": "gym_section",
        },
        {
            "fieldname": "gym_member",
            "label": "Gym Member",
            "fieldtype": "Link",
            "options": "Gym Member",
            "read_only": 1,
            "no_copy": 1,
            "insert_after": "gym_membership",
        },
    ]
}


def after_install():
    setup()


def after_migrate():
    setup()


def setup():
    create_roles()
    create_custom_fields(CUSTOM_FIELDS, update=True)
    create_item_group()


def create_roles():
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def create_item_group():
    if not frappe.db.exists("Item Group", ITEM_GROUP):
        frappe.get_doc(
            {"doctype": "Item Group", "item_group_name": ITEM_GROUP, "parent_item_group": "All Item Groups", "is_group": 0}
        ).insert(ignore_permissions=True)
    if not frappe.db.get_single_value("Gym Settings", "default_item_group"):
        frappe.db.set_single_value("Gym Settings", "default_item_group", ITEM_GROUP)
