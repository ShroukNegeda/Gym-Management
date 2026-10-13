frappe.query_reports["Membership Expiry Report"] = {
    filters: [
        { fieldname: "from_date", label: __("Expires From"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: "to_date", label: __("Expires To"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), 30), reqd: 1 },
        { fieldname: "membership_plan", label: __("Plan"), fieldtype: "Link", options: "Membership Plan" },
        { fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nActive\nFrozen\nExpired\nCancelled" },
    ],
    formatter(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (column.fieldname === "days_left" && data && data.status !== "Cancelled") {
            const colour = data.days_left < 0 ? "red" : data.days_left <= 7 ? "orange" : "green";
            value = `<span style="color:var(--${colour}-500, ${colour}); font-weight:600">${value}</span>`;
        }
        return value;
    },
};
