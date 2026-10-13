frappe.views.calendar["Class Session"] = {
    field_map: {
        start: "starts_on",
        end: "ends_on",
        id: "name",
        title: "gym_class",
        allDay: "allDay",
    },
    gantt: false,
    filters: [
        { fieldtype: "Link", fieldname: "trainer", options: "Gym Trainer", label: __("Trainer") },
        { fieldtype: "Link", fieldname: "room", options: "Gym Room", label: __("Room") },
    ],
    get_events_method: "frappe.desk.calendar.get_events",
};
