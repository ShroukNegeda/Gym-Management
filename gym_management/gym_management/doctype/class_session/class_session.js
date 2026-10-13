frappe.ui.form.on("Class Session", {
    setup(frm) {
        frm.set_query("trainer", () => ({ filters: { is_active: 1 } }));
        frm.set_query("room", () => ({ filters: { is_active: 1 } }));
    },

    refresh(frm) {
        if (frm.is_new()) return;
        frm.dashboard.set_headline(__("{0} / {1} spots booked", [frm.doc.booked_count || 0, frm.doc.capacity || 0]));
        if (frm.doc.status === "Scheduled") {
            frm.add_custom_button(__("Cancel Session"), () => {
                frappe.confirm(__("Cancel this session? All bookings will be cancelled and class credits returned."), () => {
                    frm.set_value("status", "Cancelled");
                    frm.save();
                });
            });
        }
        frm.add_custom_button(__("Bookings"), () => frappe.set_route("List", "Class Booking", { class_session: frm.doc.name }));
    },

    async gym_class(frm) {
        if (!frm.doc.gym_class) return;
        const r = await frappe.db.get_value("Gym Class", frm.doc.gym_class, ["default_trainer", "default_room", "default_capacity"]);
        const c = r.message || {};
        if (c.default_trainer) frm.set_value("trainer", c.default_trainer);
        if (c.default_room) frm.set_value("room", c.default_room);
        if (c.default_capacity) frm.set_value("capacity", c.default_capacity);
    },
});
