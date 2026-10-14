frappe.ui.form.on("Trainer Availability", {
    setup(frm) {
        frm.set_query("trainer", () => ({ filters: { is_active: 1 } }));
    },
});
