# One Staff role for the pilot

Supersedes the role split in architecture §4.3 (coordinator vs admin) and the "enforces roles" part of [ADR 0005](0005-dashboard-reads-through-api.md). Date: 2026-11-02. Decided by the product owner.

Everyone on the staff list can do every dashboard task: work the queue (Coordinator work) and keep the roster, Jobs, Owners, duty roster and settings (Admin work). The backend still verifies the Supabase token and still refuses a valid user who is not on the staff list (403). Nothing else is gated.

We chose this because the pilot office is a handful of people who cover for one another, and a second account for each person who does both jobs costs more than the protection is worth for 30 days.

Consequences:

- `staff.role` is dropped (migration `0020`). The admin screens, the staff list and `/api/me` no longer show a role. Old seed files that still carry `role` load; the field is ignored.
- "Every Coordinator" now means every staff member: the Emergency SMS (J6) and the end-of-day email (J1 step 8) go to everyone on the staff list.
- Coordinator and Admin stay as glossary words for the work a person does, not for an account type.
- Not handled yet: removing a person's access (there is no DELETE on staff). Revisit roles before a second company or a larger office uses the system.
