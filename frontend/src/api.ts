export type Staff = { id: string; name: string; email: string; role: "coordinator" | "admin" };

/** Outcome of asking the backend who the token belongs to (`GET /api/me`). */
export type MeResult =
  | { kind: "staff"; staff: Staff }
  | { kind: "not-staff" }
  | { kind: "signed-out" };

export async function fetchMe(accessToken: string): Promise<MeResult> {
  const response = await fetch("/api/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (response.status === 401) return { kind: "signed-out" };
  if (response.status === 403) return { kind: "not-staff" };
  if (!response.ok) throw new Error(`GET /api/me failed: ${response.status}`);
  return { kind: "staff", staff: (await response.json()) as Staff };
}

/** One open request as the queue shows it (`GET /api/requests`). */
export type QueueRequest = {
  ref: string;
  job: string;
  need: string;
  quantity: string | null;
  unit: string | null;
  needed_by: string | null;
  urgency: "Emergency" | "Today" | "Planned" | null;
  status: "Recorded" | "Acknowledged" | "In Progress";
  /** UTC, ISO 8601. */
  recorded_at: string;
};

/** Open requests, already sorted by the backend (urgency, then oldest first). */
export async function fetchQueue(accessToken: string): Promise<QueueRequest[]> {
  const response = await fetch("/api/requests", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`GET /api/requests failed: ${response.status}`);
  return ((await response.json()) as { requests: QueueRequest[] }).requests;
}

/** Who made a change: the agent, a staff member (with their name) or the system. */
export type Actor = { type: "agent" | "staff" | "system"; id: string | null; name: string | null };

/** One audit event; `before`/`after` hold only the changed fields (`before` null on creation). */
export type RequestEvent = {
  /** UTC, ISO 8601. */
  at: string;
  actor: Actor;
  kind: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
};

/** One request with its full audit history (`GET /api/requests/{ref}`). */
export type RequestDetail = {
  ref: string;
  foreman: string;
  job: string;
  category: string;
  need: string;
  quantity: string | null;
  unit: string | null;
  needed_by: string | null;
  urgency: "Emergency" | "Today" | "Planned" | null;
  status: "Draft" | "Recorded" | "Acknowledged" | "In Progress" | "Resolved";
  source: "ai_call" | "coordinator";
  /** UTC, ISO 8601; null while the request is a Draft. */
  recorded_at: string | null;
  /** Oldest first. */
  events: RequestEvent[];
};

/** The request rendered `ref` ("R-1000"), or null if there is none. */
export async function fetchRequestDetail(
  accessToken: string,
  ref: string,
): Promise<RequestDetail | null> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`GET /api/requests/${ref} failed: ${response.status}`);
  return (await response.json()) as RequestDetail;
}

/** A Request the Foreman did not confirm (`GET /api/drafts`); never part of the queue. */
export type Draft = {
  ref: string;
  foreman: string;
  job: string | null;
  job_spoken: string | null;
  category: string;
  need: string;
  quantity: string | null;
  unit: string | null;
  needed_by_spoken: string | null;
  call_started_at: string | null;
  call_summary: string | null;
};

export async function fetchDrafts(accessToken: string): Promise<Draft[]> {
  const response = await fetch("/api/drafts", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`GET /api/drafts failed: ${response.status}`);
  return ((await response.json()) as { drafts: Draft[] }).drafts;
}

/** Promote a Draft to Recorded. */
export async function recordDraft(accessToken: string, ref: string): Promise<void> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}/record`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`POST /api/requests/${ref}/record failed: ${response.status}`);
}
