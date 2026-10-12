# DECISIONS

## R1 - ERPNext `Subscription` or custom renewal logic?
**Custom logic** (`Gym Membership.renew()` + the daily `process_auto_renewals` job); the
`subscription` link field exists but stays unused.

*Why not Subscription:* it generates invoices on a cadence but knows nothing about our state: freezes move the
end date (so the billing period must move too), class packs end by usage not by calendar, and a lapsed member
must be blocked at the door regardless of invoice status. Making Subscription the source of truth would mean
syncing two state machines.
*What we keep from ERPNext:* the money side. Every membership still produces a normal Sales Invoice (Item = plan,
Customer = member) and is paid with Payment Entry, so receivables and reports work out of the box.
*Trade-off:* we own the renewal code (dunning, proration, plan-price changes). If the gym later wants card-on-file
recurring billing, a Subscription could be attached per membership without changing the data model.

## R2 - Modelling trainers
**Separate `Gym Trainer` linked 1:1 to `Employee`** (not custom fields on Employee).
Employee stays the HR/payroll record (reused, not duplicated); the trainer profile holds gym-only data
(specialties, bio, active flag) and is what sessions/classes link to, so gym permissions never need HR
permissions. A custom-field approach would touch a core DocType used by HR for a small number of attributes and
make "show me trainers only" queries awkward. Name and status are fetched from Employee, and an Employee `on_update`
hook deactivates the trainer when the employee leaves. A Trainer user is mapped through `Employee.user_id`.

## R3 - Pro-rated refunds (design only)
Add a *Terminate* action (separate from document cancel, which is for corrections and cancels the whole invoice).
1. `unused_ratio = remaining_days / total_days` (days exclude frozen days; for class packs `classes_remaining / classes_total`).
2. `refund = amount_paid * unused_ratio - cancellation_fee` (both from Gym Settings), never below zero; ignore refunds on unpaid invoices - just credit-note them.
3. Create a **credit note** (Sales Invoice return against the original, amount = refund, via a "Membership Refund" service Item so revenue is reduced rather than the original line edited) and, if money was collected, a Payment Entry (Pay) to the member.
4. Set the membership to *Cancelled* effective today (a new `terminated_on` field makes `resolve_membership` stop at that date), cancel future bookings (code already exists in `cancel_future_bookings`), and release the member.
Edge cases: partial payments (refund capped at what was paid), freezes in progress, taxes on the invoice (return handles them).

## R4 - Concurrent bookings (two people, last spot)
Implemented: **pessimistic row lock per session.** `validate_new_booking` runs `SELECT ... FOR UPDATE` on the
`Class Session` row, so competing requests for the same session queue up; the second one then sees the updated
`booked_count`, becomes *Waitlisted* (or is rejected). The counter, the duplicate-booking check and the
credit check run under that lock and in the same DB transaction as the insert, so a failure rolls everything back.
*Pitfall:* under MariaDB's default REPEATABLE READ a plain `SELECT COUNT(*)` after waiting for the lock can read a
stale snapshot; therefore the counter row and the duplicate check are **locking reads** (which read the latest
committed data). The counter is also re-read under lock before a Session/Membership is saved, so a stale form
cannot overwrite it. Alternatives considered: atomic `UPDATE ... WHERE booked_count < capacity` (equally safe,
but the waitlist/duplicate logic still needs a lock), Redis lock (extra moving part), unique index (cannot express
"unique unless cancelled" in MariaDB).

## R5 - Sources
* Frappe Framework docs (docs.frappe.io/framework): DocType controllers, Hooks, Form Scripts, REST API, Background Jobs - from the provided learning guide.
* ERPNext documentation: Customer, Item, Sales Invoice, Payment Entry.
* AI assistant (Claude) was used to help write and explain the code; I reviewed and ran the code and tests myself.
