frappe.ui.form.on("Body Measurement", {
    weight_kg(frm) { frm.trigger("show_bmi"); },
    height_cm(frm) { frm.trigger("show_bmi"); },
    refresh(frm) { frm.trigger("show_bmi"); },

    // live BMI preview - the server recalculates it on save
    show_bmi(frm) {
        const w = flt(frm.doc.weight_kg), h = flt(frm.doc.height_cm);
        if (w && h) frm.set_value("bmi", flt(w / Math.pow(h / 100, 2), 1));
    },
});
