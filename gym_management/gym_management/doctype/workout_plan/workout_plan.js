frappe.ui.form.on("Workout Plan", {
    setup(frm) {
        frm.set_query("trainer", () => ({ filters: { is_active: 1 } }));
        frm.set_query("member", () => ({ filters: { status: ["!=", "Blacklisted"] } }));
    },

    refresh(frm) {
        if (frm.is_new()) return;
        const colours = { Active: "green", Completed: "blue", Cancelled: "gray" };
        frm.page.set_indicator(__(frm.doc.status), colours[frm.doc.status] || "gray");

        if (frm.doc.status === "Active") {
            frm.add_custom_button(__("Mark Completed"), () => {
                frm.set_value("status", "Completed");
                if (!frm.doc.end_date) frm.set_value("end_date", frappe.datetime.get_today());
                frm.save();
            });
        }
        frm.add_custom_button(__("Body Measurements"), () =>
            frappe.set_route("List", "Body Measurement", { member: frm.doc.member }));
    },
});
