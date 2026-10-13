frappe.ui.form.on("Class Booking", {
    setup(frm) {
        // only upcoming, non-cancelled sessions - filtered client side, no server round-trip
        frm.set_query("class_session", () => ({
            filters: { status: "Scheduled", session_date: [">=", frappe.datetime.get_today()] },
        }));
        frm.set_query("member", () => ({ filters: { status: ["!=", "Blacklisted"] } }));
    },

    refresh(frm) {
        frm.trigger("show_spots");
        frm.trigger("subscribe_to_updates");
        if (frm.is_new()) return;

        const colours = { Booked: "green", Waitlisted: "orange", Attended: "blue", "No Show": "red", Cancelled: "gray" };
        frm.page.set_indicator(__(frm.doc.status), colours[frm.doc.status] || "gray");

        if (["Booked", "Waitlisted"].includes(frm.doc.status)) {
            frm.add_custom_button(__("Cancel Booking"), () => {
                frappe.confirm(__("Cancel this booking?"), () =>
                    frappe.call({ method: "gym_management.api.cancel_booking", args: { booking: frm.doc.name } })
                        .then(() => frm.reload_doc())
                );
            });
        }
        if (frm.doc.status === "Booked") {
            ["Attended", "No Show"].forEach((s) =>
                frm.add_custom_button(__(s), () =>
                    frappe.call({ method: "gym_management.api.mark_attendance", args: { booking: frm.doc.name, status: s } })
                        .then(() => frm.reload_doc()), __("Mark")));
        }
    },

    class_session(frm) { frm.trigger("show_spots"); },

    async show_spots(frm) {
        if (!frm.doc.class_session) return frm.dashboard.clear_headline();
        const r = await frappe.db.get_value("Class Session", frm.doc.class_session, ["capacity", "booked_count"]);
        frm.events.render_spots(frm, r.message);
    },

    render_spots(frm, s) {
        if (!s) return;
        // the headline only matters while the booking is open or being created
        if (!frm.is_new() && !["Booked", "Waitlisted"].includes(frm.doc.status)) return;
        const left = Math.max((s.capacity || 0) - (s.booked_count || 0), 0);
        frm.dashboard.set_headline(
            left > 0
                ? __("{0} of {1} spots remaining", [left, s.capacity])
                : __("Session full - new bookings go to the waitlist"),
            left > 0 ? "green" : "orange"
        );
    },

    // spots change while the form is open: the server publishes "gym_session_update" after every booking change
    subscribe_to_updates(frm) {
        if (frm.__gym_rt) return;
        frm.__gym_rt = true;
        frappe.realtime.on("gym_session_update", (d) => {
            if (cur_frm === frm && d.name === frm.doc.class_session) frm.events.render_spots(frm, d);
        });
    },
});
