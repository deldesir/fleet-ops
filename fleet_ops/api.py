"""Endpoints the hub's `fleet` command calls. Token auth; the user needs Fleet Manager."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import cint, flt, get_system_timezone

BACKUP_STALE_HOURS = 36


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return json.loads(v or "[]")
    return v


def _dt(iso):
    """ISO-8601 (with offset) -> naive datetime in the site's timezone, as Frappe stores it."""
    if not iso:
        return None
    d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if d.tzinfo is not None:
        d = d.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
    return d


@frappe.whitelist(methods=["POST"])
def sync(current_release=None, releases=None, boxes=None):
    """Upsert releases and boxes, append new checks. Idempotent: a check is stored once
    per (box, checked_at); releases and boxes are overwritten with the inventory's view."""
    frappe.only_for(("Fleet Manager", "System Manager"))
    releases, boxes = _as_list(releases), _as_list(boxes)
    current_release = current_release or ""
    n_rel = 0
    for r in releases:
        rid = r.get("release")
        if not rid:
            continue
        doc = frappe.get_doc("Fleet Release", rid) if frappe.db.exists("Fleet Release", rid) else frappe.new_doc("Fleet Release")
        doc.release = rid
        doc.captured = _dt(r.get("captured"))
        doc.notes = r.get("notes") or ""
        doc.is_current = 1 if rid == current_release else 0
        doc.set("apps", [{"app": a, "commit": c} for a, c in (r.get("apps") or {}).items()])
        doc.save(ignore_permissions=True)
        n_rel += 1
    for name in frappe.get_all("Fleet Release", filters={"is_current": 1, "name": ["!=", current_release]}, pluck="name"):
        frappe.db.set_value("Fleet Release", name, "is_current", 0)

    n_box = n_chk = 0
    for b in boxes:
        bid = b.get("box_id")
        if not bid:
            continue
        doc = frappe.get_doc("Managed Box", bid) if frappe.db.exists("Managed Box", bid) else frappe.new_doc("Managed Box")
        doc.box_id = bid
        for k in ("host", "business", "profile", "plan", "timezone", "maintenance_window", "billing_contact", "technical_contact"):
            setattr(doc, k, b.get(k) or "")
        doc.role = (b.get("role") or "customer").capitalize()
        doc.owner_type = "Self" if (b.get("owner") or "") == "self" else "Customer"
        doc.status = (b.get("status") or "active").capitalize()
        doc.canary_rank = cint(b.get("canary_rank"))
        if doc.owner_type == "Customer" and not doc.customer and doc.business:
            cust = frappe.db.get_value("Customer", {"customer_name": doc.business}, "name")
            if cust:
                doc.customer = cust
        chk = b.get("check") or {}
        if chk:
            when = _dt(chk.get("checked_at"))
            doc.last_check = when
            doc.last_check_status = "OK" if chk.get("status") == "OK" else "FAILED"
            doc.last_problems = "\n".join(chk.get("problems") or [])
            age = chk.get("hub_backup_age_h")
            doc.hub_backup_age_h = flt(age) if age is not None else 0
            doc.backup_stale = 1 if (age is None or flt(age) > BACKUP_STALE_HOURS) else 0
            doc.tls_days_left = cint(chk.get("tls_days_left") or 0)
            doc.disk_free_gb = cint(chk.get("disk_free_gb") or 0)
            doc.open_shifts = cint(chk.get("open_shifts") or 0)
            doc.behind_release = 1 if chk.get("behind_release") else 0
            doc.domain_registrar = chk.get("domain_registrar") or doc.domain_registrar
            if chk.get("domain_expiry"):
                doc.domain_expiry = str(chk["domain_expiry"])[:10]
            doc.domain_days_left = cint(chk.get("domain_days_left") or 0) if chk.get("domain_days_left") is not None else doc.domain_days_left
            if current_release and frappe.db.exists("Fleet Release", current_release):
                doc.release = current_release if not doc.behind_release else doc.release
        doc.save(ignore_permissions=True)
        n_box += 1
        if chk and when and not frappe.db.exists("Fleet Check", {"box": bid, "checked_at": when}):
            frappe.get_doc({
                "doctype": "Fleet Check", "box": bid, "checked_at": when,
                "status": "OK" if chk.get("status") == "OK" else "FAILED",
                "release_current": chk.get("release_current") or "",
                "disk_free_gb": cint(chk.get("disk_free_gb") or 0), "ram_avail_mb": cint(chk.get("ram_avail_mb") or 0),
                "errorlog_rows": cint(chk.get("errorlog_rows_today") or 0), "failed_units": cint(chk.get("failed_units") or 0),
                "open_shifts": cint(chk.get("open_shifts") or 0), "tls_days_left": cint(chk.get("tls_days_left") or 0),
                "domain_days_left": cint(chk.get("domain_days_left") or 0),
                "hub_backup_age_h": flt(chk.get("hub_backup_age_h") or 0), "box_backup_age_h": flt(chk.get("box_backup_age_h") or 0),
                "targets": chk.get("targets") or "", "http_codes": " ".join(f"{k}={v}" for k, v in (chk.get("http") or {}).items()),
                "heads": "\n".join(f"{k}={v}" for k, v in (chk.get("heads") or {}).items()),
                "behind_release": ", ".join(chk.get("behind_release") or []),
                "problems": "\n".join(chk.get("problems") or []), "raw": json.dumps(chk, indent=1),
            }).insert(ignore_permissions=True)
            n_chk += 1
        # keep the domain's own renewal row in step with what the check saw
        if chk.get("domain_expiry"):
            for sub in frappe.get_all("Fleet Subscription", filters={"service_type": "Domain", "reference": doc.host}, pluck="name"):
                frappe.db.set_value("Fleet Subscription", sub, {"next_renewal": str(chk["domain_expiry"])[:10],
                                                                  "provider": chk.get("domain_registrar") or frappe.db.get_value("Fleet Subscription", sub, "provider")})
    frappe.db.commit()
    return {"releases": n_rel, "boxes": n_box, "checks": n_chk}
