app_name = "gym_management"
app_title = "Gym Management"
app_publisher = "Shrouk Negeda"
app_description = "Gym management on top of ERPNext"
app_email = "sh.ta.3366@gmail.com"
app_license = "MIT"

required_apps = ["erpnext"]

# Install / migrate: roles, custom fields, item group (all idempotent)
after_install = "gym_management.install.after_install"
after_migrate = "gym_management.install.after_migrate"

# Keep Gym Trainer in sync when an Employee leaves
doc_events = {
    "Employee": {"on_update": "gym_management.events.employee_on_update"},
}

scheduler_events = {
    "hourly": ["gym_management.tasks.hourly"],
    "daily": ["gym_management.tasks.daily"],
}

# Trainers only see their own sessions / the bookings of their own sessions
permission_query_conditions = {
    "Class Session": "gym_management.permissions.class_session_query",
    "Class Booking": "gym_management.permissions.class_booking_query",
}
has_permission = {
    "Class Session": "gym_management.permissions.class_session_has_permission",
    "Class Booking": "gym_management.permissions.class_booking_has_permission",
}
