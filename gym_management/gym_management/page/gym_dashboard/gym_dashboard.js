frappe.pages["gym-dashboard"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Gym Dashboard"), single_column: true });
    const dashboard = new GymDashboard(page);
    page.set_primary_action(__("Refresh"), () => dashboard.refresh(), "refresh");
    $(wrapper).on("show", () => dashboard.refresh());
};

class GymDashboard {
    constructor(page) {
        this.page = page;
        this.$body = $('<div class="gym-dashboard" style="padding:15px 0"></div>').appendTo(page.main);
    }

    refresh() {
        frappe.call({ method: "gym_management.api.get_dashboard_data" }).then((r) => this.render(r.message));
    }

    card(label, value, colour, route) {
        const click = route ? `onclick="frappe.set_route(${route})" style="cursor:pointer"` : "";
        return `<div class="col-sm-3 col-xs-6" style="margin-bottom:15px">
            <div class="frappe-card" ${click} style="padding:15px">
                <div class="text-muted small">${label}</div>
                <div style="font-size:28px;font-weight:600;color:var(--${colour}-500, inherit)">${value}</div>
            </div></div>`;
    }

    render(d) {
        const e = frappe.utils.escape_html;
        const money = (v) => format_currency(v, d.currency);
        const sessions = d.sessions.length
            ? d.sessions.map((s) => `<tr>
                <td>${e(s.start_time || "").slice(0, 5)}</td><td>${e(s.gym_class)}</td><td>${e(s.trainer_name || "")}</td>
                <td>${s.booked_count}/${s.capacity}</td>
                <td><div class="progress" style="margin:0"><div class="progress-bar ${s.fill_rate >= 90 ? "progress-bar-warning" : "progress-bar-success"}"
                    style="width:${Math.min(s.fill_rate, 100)}%">${s.fill_rate}%</div></div></td></tr>`).join("")
            : `<tr><td colspan="5" class="text-muted">${__("No sessions today")}</td></tr>`;
        const expiring = d.expiring.length
            ? d.expiring.map((m) => `<tr><td><a href="/app/gym-membership/${encodeURIComponent(m.name)}">${e(m.member_name)}</a></td>
                <td>${e(m.membership_plan)}</td><td>${frappe.datetime.str_to_user(m.end_date)}</td></tr>`).join("")
            : `<tr><td colspan="3" class="text-muted">${__("Nothing expiring in the next 7 days")}</td></tr>`;

        this.$body.html(`
            <div class="row">
                ${this.card(__("Active Members"), d.active_members, "green", '"List","Gym Member",{status:"Active"}')}
                ${this.card(__("Expiring in 7 Days"), d.expiring_count, d.expiring_count ? "orange" : "green", '"query-report","Membership Expiry Report"')}
                ${this.card(__("Revenue This Month"), money(d.revenue_invoiced), "blue")}
                ${this.card(__("Collected This Month"), money(d.revenue_collected), "blue")}
            </div>
            <div class="row">
                <div class="col-md-7"><div class="frappe-card" style="padding:15px;margin-bottom:15px">
                    <h6>${__("Today's Sessions & Fill Rate")}</h6>
                    <table class="table table-sm"><thead><tr><th>${__("Time")}</th><th>${__("Class")}</th><th>${__("Trainer")}</th><th>${__("Booked")}</th><th style="width:30%">${__("Fill")}</th></tr></thead>
                    <tbody>${sessions}</tbody></table></div></div>
                <div class="col-md-5"><div class="frappe-card" style="padding:15px;margin-bottom:15px">
                    <h6>${__("Expiring Soon")}</h6>
                    <table class="table table-sm"><thead><tr><th>${__("Member")}</th><th>${__("Plan")}</th><th>${__("Expires")}</th></tr></thead>
                    <tbody>${expiring}</tbody></table></div></div>
            </div>
            <div class="frappe-card" style="padding:15px"><h6>${__("Invoiced Revenue by Day (this month)")}</h6><div class="revenue-chart"></div></div>`);

        if (d.revenue_by_day.length) {
            new frappe.Chart(this.$body.find(".revenue-chart")[0], {
                data: {
                    labels: d.revenue_by_day.map((r) => frappe.datetime.str_to_user(r.date)),
                    datasets: [{ name: __("Invoiced"), values: d.revenue_by_day.map((r) => r.invoiced) }],
                },
                type: "bar", height: 220, colors: ["#5e64ff"],
            });
        } else {
            this.$body.find(".revenue-chart").html(`<div class="text-muted">${__("No invoices yet this month")}</div>`);
        }
    }
}
