frappe.listview_settings["Class Booking"] = {
    add_fields: ["status"],
    get_indicator(doc) {
        const colours = { Booked: "green", Waitlisted: "orange", Attended: "blue", "No Show": "red", Cancelled: "gray" };
        return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
    },
};
