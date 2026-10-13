frappe.pages["gym-checkin"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Front Desk Check-in"), single_column: true });
    new GymCheckin(page);
};

class GymCheckin {
    constructor(page) {
        this.page = page;
        this.$root = $(`
            <div class="gym-checkin" style="max-width:720px;margin:20px auto">
                <input class="form-control input-lg gym-search" autofocus
                       placeholder="${__("Scan QR / type name, phone or member ID and press Enter")}">
                <div class="gym-results" style="margin-top:10px"></div>
                <div class="gym-member" style="margin-top:15px"></div>
            </div>`).appendTo(page.main);
        this.$search = this.$root.find(".gym-search");
        this.$results = this.$root.find(".gym-results");
        this.$member = this.$root.find(".gym-member");
        this.$search.on("keydown", (e) => { if (e.key === "Enter") this.search(); });
        this.$search.on("input", frappe.utils.debounce(() => this.search(), 400));
    }

    search() {
        const txt = this.$search.val().trim();
        if (!txt) { this.$results.empty(); return; }
        frappe.call({ method: "gym_management.api.search_members", args: { txt } }).then((r) => {
            const rows = r.message || [];
            if (rows.length === 1) { this.$results.empty(); this.select(rows[0].name); return; }
            const e = frappe.utils.escape_html;
            this.$results.html(rows.length
                ? rows.map((m) => `<div class="list-group-item" data-member="${e(m.name)}" style="cursor:pointer">
                    <b>${e(m.member_name)}</b> <span class="text-muted">${e(m.name)} &middot; ${e(m.phone || "")}</span>
                    <span class="pull-right indicator-pill ${m.status === "Active" ? "green" : "gray"}">${__(m.status)}</span></div>`).join("")
                : `<div class="text-muted">${__("No member found")}</div>`);
            this.$results.find("[data-member]").on("click", (ev) => { this.$results.empty(); this.select($(ev.currentTarget).data("member")); });
        });
    }

    select(member) {
        frappe.call({ method: "gym_management.api.get_member_access", args: { member } }).then((r) => this.render(r.message));
    }

    render(d) {
        const e = frappe.utils.escape_html;
        const ok = d.allowed;
        const bookings = (d.bookings_today || []).map((b, i) => `
            <label style="display:block"><input type="radio" name="gym-booking" value="${e(b.name)}" ${i === 0 ? "checked" : ""}>
            ${e(b.gym_class)} &middot; ${e((b.start_time || "").slice(0, 5))}</label>`).join("");
        const details = d.membership ? `
            <div>${e(d.membership_plan || "")} &middot; ${__("valid until")} <b>${frappe.datetime.str_to_user(d.end_date)}</b></div>
            ${d.classes_total ? `<div>${__("Classes remaining")}: <b>${d.classes_remaining}</b> / ${d.classes_total}</div>` : ""}` : "";

        this.$member.html(`
            <div class="gym-banner" style="padding:20px;border-radius:8px;color:#fff;background:${ok ? "#2e9e5b" : "#d0342c"}">
                <div style="font-size:26px;font-weight:700">${ok ? "&#10003; " + __("ACCESS GRANTED") : "&#10007; " + __("ACCESS DENIED")}</div>
                <div style="font-size:18px">${e(d.member_name)} <small>(${e(d.member)})</small></div>
                <div style="margin-top:6px">${e(d.message)}</div>
            </div>
            <div class="frappe-card" style="padding:15px;margin-top:10px">
                ${details}
                ${bookings ? `<h6 style="margin-top:12px">${__("Booked today")}</h6>${bookings}
                    <label style="display:block"><input type="radio" name="gym-booking" value=""> ${__("Gym floor only")}</label>` : ""}
                <div style="margin-top:12px">
                    <select class="form-control gym-method" style="width:auto;display:inline-block">
                        <option>Front Desk</option><option>QR</option><option>Card</option></select>
                    <button class="btn btn-primary btn-lg gym-do-checkin" ${ok ? "" : "disabled"}>${__("Check In")}</button>
                </div>
            </div>`);

        this.$member.find(".gym-do-checkin").on("click", () => {
            const booking = this.$member.find("input[name=gym-booking]:checked").val() || null;
            frappe.call({
                method: "gym_management.api.check_in",
                args: { member: d.member, method: this.$member.find(".gym-method").val(), class_booking: booking },
                freeze: true,
            }).then(() => {
                frappe.show_alert({ message: __("{0} checked in", [d.member_name]), indicator: "green" });
                this.$member.empty();
                this.$search.val("").focus();
            });
        });
    }
}
