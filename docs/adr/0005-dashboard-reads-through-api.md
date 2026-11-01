# Dashboard uses Supabase for login only; all data goes through FastAPI

The React dashboard authenticates with Supabase Auth but never queries Supabase tables directly (no client-side supabase-js data access, no reliance on row-level security). Every read and write goes through FastAPI, which verifies the Supabase JWT and enforces roles. We chose this over the usual Supabase pattern so the agent and the dashboard share one code path for business rules and the audit log, and an ack-without-owner or resolve-without-outcome can't be written by any client.
