"""Install-time setup. The desk objects (Sidebar, Dashboard, Number Cards) ship as JSON
in this app and are synced by Frappe on install and migrate; only the role is created here."""
import frappe

ROLE = "Fleet Manager"


def after_install():
    if not frappe.db.exists("Role", ROLE):
        frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(ignore_permissions=True)
    frappe.db.commit()
