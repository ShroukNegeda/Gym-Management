frappe.listview_settings["Gym Membership"] = {
    add_fields: ["status", "end_date"],
    get_indicator(doc) {
        const colours = { Draft: "gray", Active: "green", Frozen: "blue", Expired: "red", Cancelled: "darkgrey" };
        return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
    },
};
