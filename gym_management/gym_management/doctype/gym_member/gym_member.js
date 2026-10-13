frappe.ui.form.on("Gym Member", {
    refresh(frm) {
        if (frm.is_new()) return;
        frm.add_custom_button(__("Sell Membership"), () => frappe.new_doc("Gym Membership", { member: frm.doc.name }));
        frm.add_custom_button(__("Check In"), () => {
            frappe.call({ method: "gym_management.api.check_in", args: { member: frm.doc.name } }).then((r) => {
                frappe.show_alert({ message: __("Checked in ({0})", [r.message.check_in]), indicator: "green" });
            });
        });
        if (frm.doc.customer) {
            frm.add_custom_button(__("Customer"), () => frappe.set_route("Form", "Customer", frm.doc.customer), __("View"));
        }
        const colours = { Prospect: "orange", Active: "green", Inactive: "gray", Blacklisted: "red" };
        frm.page.set_indicator(__(frm.doc.status), colours[frm.doc.status] || "gray");
    },
});
