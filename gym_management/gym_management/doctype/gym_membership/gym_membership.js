const STATUS_COLOURS = { Draft: "gray", Active: "green", Frozen: "blue", Expired: "red", Cancelled: "darkgrey" };

frappe.ui.form.on("Gym Membership", {
    setup(frm) {
        frm.set_query("member", () => ({ filters: { status: ["!=", "Blacklisted"] } }));
        frm.set_query("membership_plan", () => ({ filters: { is_active: 1 } }));
    },

    onload(frm) {
        if (frm.is_new() && !frm.doc.company) {
            frm.set_value("company", frappe.defaults.get_user_default("Company"));
        }
    },

    refresh(frm) {
        frm.trigger("render_status");
        frm.trigger("toggle_fields");
        frm.trigger("add_buttons");
        if (frm.is_new()) frm.trigger("preview_end_date");
    },

    render_status(frm) {
        if (frm.is_new()) return;
        frm.page.set_indicator(__(frm.doc.status), STATUS_COLOURS[frm.doc.status] || "gray");
    },

    toggle_fields(frm) {
        const submitted = frm.doc.docstatus === 1;
        const locked = ["Expired", "Cancelled"].includes(frm.doc.status);
        // freezing is only possible while the membership is running
        frm.set_df_property("freeze_history", "read_only", !(submitted && ["Active", "Frozen"].includes(frm.doc.status)));
        frm.set_df_property("auto_renew", "read_only", locked ? 1 : 0);
        frm.toggle_display("renewed_from", !!frm.doc.renewed_from);
        frm.toggle_display("classes_remaining", frm.doc.classes_total > 0);
        // once submitted the commercial terms are fixed
        ["member", "membership_plan", "start_date", "company"].forEach((f) => frm.set_df_property(f, "read_only", submitted ? 1 : 0));
    },

    add_buttons(frm) {
        if (frm.doc.docstatus !== 1) return;

        if (frm.doc.status === "Active") {
            frm.add_custom_button(__("Freeze"), () => {
                frappe.prompt(
                    [
                        { fieldname: "freeze_from", label: __("Freeze From"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
                        { fieldname: "freeze_to", label: __("Freeze To"), fieldtype: "Date", reqd: 1 },
                        { fieldname: "reason", label: __("Reason"), fieldtype: "Small Text" },
                    ],
                    (values) => {
                        frm.call({ method: "freeze", doc: frm.doc, args: values, freeze: true, freeze_message: __("Freezing...") })
                            .then(() => frm.reload_doc());
                    },
                    __("Freeze Membership"),
                    __("Freeze")
                );
            }, __("Actions"));
        }

        if (["Active", "Frozen", "Expired"].includes(frm.doc.status)) {
            frm.add_custom_button(__("Renew"), () => {
                frm.call({ method: "renew", doc: frm.doc, args: { submit: 0 }, freeze: true }).then((r) => {
                    if (r.message) frappe.set_route("Form", "Gym Membership", r.message);
                });
            }, __("Actions"));
        }

        if (frm.doc.sales_invoice) {
            frm.add_custom_button(__("Payment Entry"), () => {
                frappe.call({
                    method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
                    args: { dt: "Sales Invoice", dn: frm.doc.sales_invoice },
                }).then((r) => {
                    const doc = frappe.model.sync(r.message)[0];
                    frappe.set_route("Form", doc.doctype, doc.name);
                });
            }, __("Create"));
        }
    },

    // live preview of the end date while drafting (one cached lookup per plan)
    membership_plan(frm) { frm.__plan = null; frm.trigger("preview_end_date"); },
    start_date(frm) { frm.trigger("preview_end_date"); },

    async preview_end_date(frm) {
        if (frm.doc.docstatus !== 0 || !frm.doc.membership_plan || !frm.doc.start_date) return;
        if (!frm.__plan) {
            const r = await frappe.db.get_value("Membership Plan", frm.doc.membership_plan,
                ["duration_type", "duration_value", "validity_days"]);
            frm.__plan = r.message;
        }
        const p = frm.__plan;
        if (!p) return;
        const start = frm.doc.start_date;
        let end;
        if (p.duration_type === "Days") end = frappe.datetime.add_days(start, p.duration_value - 1);
        else if (p.duration_type === "Months") end = frappe.datetime.add_days(frappe.datetime.add_months(start, p.duration_value), -1);
        else end = frappe.datetime.add_days(start, (p.validity_days || 90) - 1);
        frm.dashboard.set_headline(__("Membership will run until {0}", [frappe.datetime.str_to_user(end)]));
    },
});
