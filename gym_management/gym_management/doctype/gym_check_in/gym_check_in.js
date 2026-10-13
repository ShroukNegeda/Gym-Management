frappe.ui.form.on("Gym Check In", {
    setup(frm) {
        // only today's confirmed bookings of the selected member
        frm.set_query("class_booking", () => ({
            filters: { member: frm.doc.member, status: "Booked", session_date: frappe.datetime.get_today() },
        }));
    },
    member(frm) { frm.set_value("class_booking", null); },
});
