# Copyright (c) 2026, Blondel Mondesir and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ManagedBox(Document):
	_DOCTYPE_NAME = "Managed Box"

	def validate(self):
		if self.alias:
			other = frappe.db.get_value("Managed Box", {"alias": self.alias, "name": ["!=", self.name or ""]}, "name")
			if other:
				frappe.throw(f"Alias {self.alias} is already used by {other}")
