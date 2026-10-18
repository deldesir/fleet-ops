import frappe
from frappe.model.document import Document
from frappe.utils import flt


class FleetSubscription(Document):
    def validate(self):
        cycle = self.billing_cycle or "Monthly"
        price = flt(self.price)
        self.monthly_cost = price if cycle == "Monthly" else price / 12 if cycle == "Yearly" else 0
