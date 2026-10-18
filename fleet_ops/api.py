"""Endpoints the hub's `fleet` command and the boxes' `fleet-agent` call.

sync / latest_report / current_manifest: token auth, role Fleet Manager (the hub).
report: box-authenticated (token hash stored on the Managed Box by the hub's sync)."""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import cint, flt, get_system_timezone

BACKUP_STALE_HOURS = 36
STATUS_MAP = {"OK": "OK", "WARN": "WARN", "CRIT": "CRIT", "STALE": "STALE", "FAILED": "CRIT"}


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return json.loads(v or "[]")
    return v


def _dt(iso):
    if not iso:
        return None
    d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if d.tzinfo is not None:
        d = d.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
    return d


def _apply_check(doc, chk, current_release):
    """Write a check's summary onto its Managed Box and store the Fleet Check row (once per checked_at)."""
    when = _dt(chk.get("checked_at"))
    status = STATUS_MAP.get(chk.get("status"), "CRIT")
    findings = chk.get("findings") or [{"level": "CRIT", "code": "legacy", "message": m} for m in (chk.get("problems") or [])]
    doc.last_check = when
    doc.last_check_status = status
    doc.last_problems = "\n".join(f"{x['level']}: {x['message']}" for x in findings if x.get("level") != "INFO")
    doc.crit_count = sum(1 for x in findings if x.get("level") == "CRIT")
    doc.warn_count = sum(1 for x in findings if x.get("level") in ("WARN", "STALE"))
    age = chk.get("hub_backup_age_h") if chk.get("mode", "pull") == "pull" else chk.get("box_backup_age_h")
    try:
        agef = flt(age) if age not in (None, "?", "") else None
    except Exception:
        agef = None
    doc.hub_backup_age_h = agef or 0
    doc.backup_stale = 1 if (agef is None or agef > BACKUP_STALE_HOURS) else 0
    doc.tls_days_left = cint(chk.get("tls_days_left") or 0)
    doc.disk_free_gb = cint(chk.get("disk_free_gb") or 0)
    doc.open_shifts = cint(chk.get("open_shifts") or 0)
    doc.behind_release = 1 if chk.get("behind_release") else 0
    doc.domain_registrar = chk.get("domain_registrar") or doc.domain_registrar
    if chk.get("domain_expiry"):
        doc.domain_expiry = str(chk["domain_expiry"])[:10]
    if chk.get("domain_days_left") is not None:
        doc.domain_days_left = cint(chk.get("domain_days_left"))
    if current_release and frappe.db.exists("Fleet Release", current_release) and not doc.behind_release and chk.get("heads"):
        doc.release = current_release
    stored = 0
    if when and not frappe.db.exists("Fleet Check", {"box": doc.box_id, "checked_at": when}):
        frappe.get_doc({
            "doctype": "Fleet Check", "box": doc.box_id, "checked_at": when, "status": status,
            "release_current": chk.get("release_current") or "",
            "disk_free_gb": cint(chk.get("disk_free_gb") or 0), "ram_avail_mb": cint(chk.get("ram_avail_mb") or 0),
            "errorlog_rows": cint(chk.get("errorlog_rows_today") or 0), "failed_units": cint(chk.get("failed_units") or 0),
            "open_shifts": cint(chk.get("open_shifts") or 0), "tls_days_left": cint(chk.get("tls_days_left") or 0),
            "domain_days_left": cint(chk.get("domain_days_left") or 0),
            "hub_backup_age_h": flt(chk.get("hub_backup_age_h") or 0), "box_backup_age_h": flt(chk.get("box_backup_age_h") or 0) if str(chk.get("box_backup_age_h", "")).replace(".", "").isdigit() else 0,
            "crit_count": doc.crit_count, "warn_count": doc.warn_count,
            "targets": chk.get("targets") or "", "http_codes": " ".join(f"{k}={v}" for k, v in (chk.get("http") or {}).items()),
            "heads": "\n".join(f"{k}={v}" for k, v in (chk.get("heads") or {}).items()),
            "behind_release": ", ".join(chk.get("behind_release") or []),
            "problems": doc.last_problems, "findings": json.dumps(findings, indent=1), "raw": json.dumps(chk, indent=1),
        }).insert(ignore_permissions=True)
        stored = 1
    if chk.get("domain_expiry"):
        for sub in frappe.get_all("Fleet Subscription", filters={"service_type": "Domain", "reference": doc.host}, pluck="name"):
            frappe.db.set_value("Fleet Subscription", sub, {"next_renewal": str(chk["domain_expiry"])[:10],
                                                              "provider": chk.get("domain_registrar") or frappe.db.get_value("Fleet Subscription", sub, "provider")})
    return stored


@frappe.whitelist(methods=["POST"])
def sync(current_release=None, releases=None, boxes=None, catalog=None):
    """Upsert catalog, releases and boxes; append new checks. Idempotent."""
    frappe.only_for(("Fleet Manager", "System Manager"))
    releases, boxes, catalog = _as_list(releases), _as_list(boxes), _as_list(catalog)
    current_release = current_release or ""
    n_cat = 0
    for c in catalog:
        sid = c.get("service_id")
        if not sid:
            continue
        doc = frappe.get_doc("Fleet Service", sid) if frappe.db.exists("Fleet Service", sid) else frappe.new_doc("Fleet Service")
        doc.service_id = sid
        doc.title = c.get("title") or sid
        doc.kind = "Hub-hosted" if c.get("kind") == "hub" else "Box"
        doc.maturity = {"ready": "Ready", "on-request": "On request", "candidate": "Candidate"}.get(c.get("maturity"), "Candidate")
        doc.apps = ", ".join(c.get("apps") or [])
        doc.units = ", ".join(c.get("units") or [])
        doc.upstream = c.get("upstream") or ""
        doc.probes = c.get("probes") or ""
        doc.catalog_notes = c.get("notes") or ""
        if c.get("billing_item") and frappe.db.exists("Item", c["billing_item"]) and not doc.item:
            doc.item = c["billing_item"]
        doc.save(ignore_permissions=True)
        n_cat += 1
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
        doc.set("apps", [{"app": a, "commit": c} for a, c in sorted((r.get("apps") or {}).items())])
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
        doc.connectivity = (b.get("connectivity") or "public").capitalize()
        if b.get("agent_token_hash"):
            doc.agent_token_hash = b["agent_token_hash"]
        doc.set("services", [{"service": s, "title": frappe.db.get_value("Fleet Service", s, "title") or s} for s in (b.get("services") or []) if frappe.db.exists("Fleet Service", s)])
        if doc.owner_type == "Customer" and not doc.customer and doc.business:
            cust = frappe.db.get_value("Customer", {"customer_name": doc.business}, "name")
            if cust:
                doc.customer = cust
        chk = b.get("check") or {}
        if chk:
            n_chk += _apply_check(doc, chk, current_release)
        doc.save(ignore_permissions=True)
        n_box += 1
    frappe.db.commit()
    return {"catalog": n_cat, "releases": n_rel, "boxes": n_box, "checks": n_chk}


@frappe.whitelist(methods=["GET"])
def latest_report(box_id):
    """Newest check stored for a box (the hub reads this for push-mode boxes)."""
    frappe.only_for(("Fleet Manager", "System Manager"))
    rows = frappe.get_all("Fleet Check", filters={"box": box_id}, fields=["checked_at", "status", "raw"], order_by="checked_at desc", limit=1)
    if not rows:
        return {}
    r = rows[0]
    when = r.checked_at.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(ZoneInfo("UTC"))
    return {"checked_at": when.isoformat(timespec="seconds"), "status": r.status, "raw": json.loads(r.raw or "{}")}


def _box_for_token(box_id, token):
    if not (box_id and token) or not frappe.db.exists("Managed Box", box_id):
        frappe.throw("unknown box", frappe.AuthenticationError)
    stored = frappe.db.get_value("Managed Box", box_id, "agent_token_hash") or ""
    if not stored or hashlib.sha256(str(token).encode()).hexdigest() != stored:
        frappe.throw("bad token", frappe.AuthenticationError)
    return frappe.get_doc("Managed Box", box_id)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def report(box_id=None, token=None, check=None):
    """A box reports its own check (offline / push-mode boxes). Raw metrics are stored; the
    hub's `fleet check` re-evaluates severity against the inventory and catalog."""
    doc = _box_for_token(box_id, token)
    chk = json.loads(check) if isinstance(check, str) else (check or {})
    chk.setdefault("checked_at", datetime.utcnow().isoformat(timespec="seconds") + "+00:00")
    chk.setdefault("status", "OK")
    chk["mode"] = "push"
    frappe.set_user("Administrator")
    stored = _apply_check(doc, chk, frappe.db.get_value("Fleet Release", {"is_current": 1}, "name") or "")
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "stored": stored}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def current_manifest(box_id=None, token=None):
    """The current release as manifest text, for fleet-agent's self-upgrade."""
    _box_for_token(box_id, token)
    rid = frappe.db.get_value("Fleet Release", {"is_current": 1}, "name")
    if not rid:
        return {"release": "", "manifest": ""}
    rel = frappe.get_doc("Fleet Release", rid)
    lines = [f"# fleet release {rid}", f"release={rid}", f"captured={rel.captured}"] + [f"{a.app}={a.commit}" for a in rel.apps]
    return {"release": rid, "manifest": "\n".join(lines) + "\n"}
