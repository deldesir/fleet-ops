# Fleet Ops

A small Frappe app for a company that runs ERPNext boxes for other businesses. It
keeps, next to ERPNext's own Customer / Subscription / Sales Invoice records, the
operational side of each managed box:

- **Managed Box** — one row per box: host, business, role (hub, till, customer),
  owner, plan, lifecycle status, canary rank, maintenance window, the release it
  runs, the result of its last health check and its last backup.
- **Fleet Check** — one row per health check per box (app heads, service state,
  error log rows, HTTP codes, disk, RAM, backup age, TLS days left, problems).
- **Fleet Release** — a named set of app commits (a release manifest) the fleet is
  rolled to; boxes are compared against the current one.

The rows are written by the hub's `fleet` command (`fleet push`), which calls
`fleet_ops.api.sync` with a token of a user holding the **Fleet Manager** role. The
**Fleet** workspace shows the numbers that matter: boxes healthy, boxes failing,
boxes behind the current release, stale backups, active subscriptions, overdue
invoices and outstanding receivables.

Install: `bench get-app <this repo>` then `bench --site <site> install-app fleet_ops`.
Requires ERPNext on the same site (for Customer, Subscription, Sales Invoice).

License: MIT.
