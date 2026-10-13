frappe.listview_settings["Class Session"] = {
    add_fields: ["status", "booked_count", "capacity"],
    get_indicator(doc) {
        if (doc.status === "Cancelled") return [__("Cancelled"), "gray", "status,=,Cancelled"];
        if (doc.status === "Completed") return [__("Completed"), "blue", "status,=,Completed"];
        if (doc.booked_count >= doc.capacity) return [__("Full"), "orange", "status,=,Scheduled"];
        return [__("Open"), "green", "status,=,Scheduled"];
    },
};
