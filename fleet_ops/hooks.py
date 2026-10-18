app_name = "fleet_ops"
app_title = "Fleet"
app_publisher = "Blondel Mondesir"
app_description = "Managed-fleet operations for Frappe benches: boxes, health checks, releases, our own subscriptions"
app_email = "blondel.md@gmail.com"
app_license = "mit"
app_home = "/desk/dashboard-view/Fleet"
required_apps = ["frappe/erpnext"]

# The app tile on the desk's Apps screen opens the Fleet dashboard; the module's Sidebar,
# number cards and dashboard ship as JSON under fleet_ops/fleet_ops/ and are synced on
# install and migrate.
add_to_apps_screen = [
    {
        "name": "fleet_ops",
        "logo": "/assets/fleet_ops/images/fleet.svg",
        "title": "Fleet",
        "route": app_home,
    }
]

after_install = "fleet_ops.install.after_install"
