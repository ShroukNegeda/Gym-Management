const PT_COLOURS = { Booked: "green", Completed: "blue", Cancelled: "gray", "No Show": "red" };

frappe.ui.form.on("Personal Training Session", {
    setup(frm) {
        frm.set_query("trainer", () => ({ filters: { is_active: 1 } }));
        frm.set_query("member", () => ({ filters: { status: ["!=", "Blacklisted"] } }));
    },

    refresh(frm) {
        if (frm.is_new()) {
            frm.add_custom_button(__("Find Free Slot"), () => frm.trigger("pick_slot"));
            return;
        }
        frm.page.set_indicator(__(frm.doc.status), PT_COLOURS[frm.doc.status] || "gray");
        // the booking is fixed once made: to move it, cancel and book again
        ["member", "trainer", "session_date", "start_time", "duration_minutes"].forEach((f) => frm.set_df_property(f, "read_only", 1));

        if (frm.doc.status === "Booked") {
            frm.add_custom_button(__("Cancel Session"), () =>
                frappe.confirm(__("Cancel this session?"), () =>
                    frappe.call({ method: "gym_management.pt_api.cancel_personal_training", args: { session: frm.doc.name } })
                        .then(() => frm.reload_doc())));
            ["Completed", "No Show"].forEach((s) =>
                frm.add_custom_button(__(s), () => { frm.set_value("status", s); frm.save(); }, __("Mark")));
        }
    },

    // asks the server which start times are free for this trainer / date / duration
    pick_slot(frm) {
        if (!frm.doc.trainer || !frm.doc.session_date) {
            frappe.msgprint(__("Choose the Trainer and the Session Date first."));
            return;
        }
        frappe.call({
            method: "gym_management.pt_api.get_trainer_slots",
            args: { trainer: frm.doc.trainer, session_date: frm.doc.session_date, duration_minutes: frm.doc.duration_minutes || 60 },
        }).then((r) => {
            const slots = (r.message && r.message.slots) || [];
            if (!slots.length) {
                frappe.msgprint(__("No free slots on this date. Check the trainer's Trainer Availability."));
                return;
            }
            frappe.prompt(
                [{ fieldname: "slot", label: __("Start Time"), fieldtype: "Select", options: slots.map((s) => s.slice(0, 5)).join("\n"), reqd: 1 }],
                (v) => frm.set_value("start_time", v.slot + ":00"),
                __("Free slots"), __("Use this time"));
        });
    },
});
