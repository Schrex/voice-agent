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
  /** The Job's name; null when Unmatched (no confident match for what the Foreman said). */
  job: string | null;
  /** The Job as the Foreman said it. */
  job_spoken: string;
  need: string;
  quantity: string | null;
  unit: string | null;
  /** UTC, ISO 8601; null when unknown, not understood, or only a day was said. */
  needed_by: string | null;
  /** The needed-by as the Foreman said it; null when they could not say. */
  needed_by_spoken: string | null;
  urgency: "Emergency" | "Today" | "Planned" | null;
  status: "Recorded" | "Acknowledged" | "In Progress";
  /** UTC, ISO 8601. */
  recorded_at: string;
};

/** Every time on the dashboard is shown in the office's zone, whatever the browser's zone. */
export const officeTime = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/**
 * The resolved needed-by in New York time; else what the Foreman said, in quotes, when the
 * backend could not resolve it; else "Unknown" (spec AC1.5: the Foreman could not say).
 */
export function neededByText(r: {
  needed_by: string | null;
  needed_by_spoken: string | null;
}): string {
  if (r.needed_by) return officeTime.format(new Date(r.needed_by));
  if (r.needed_by_spoken) return `“${r.needed_by_spoken}”`;
  return "Unknown";
}

/** "Unmatched: “<what the Foreman said>”" for a Job that matched nothing, else its name. */
export function jobText(r: { job: string | null; job_spoken: string }): string {
  return r.job ?? `Unmatched: “${r.job_spoken}”`;
}

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
  /** Null when Unmatched. */
  job: string | null;
  job_spoken: string;
  category: string;
  need: string;
  quantity: string | null;
  unit: string | null;
  /** UTC, ISO 8601; null when unknown, not understood, or only a day was said. */
  needed_by: string | null;
  /** The needed-by as the Foreman said it; null when they could not say. */
  needed_by_spoken: string | null;
  urgency: "Emergency" | "Today" | "Planned" | null;
  status: "Draft" | "Recorded" | "Acknowledged" | "In Progress" | "Resolved";
  source: "ai_call" | "coordinator";
  /** UTC, ISO 8601. */
  recorded_at: string;
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
