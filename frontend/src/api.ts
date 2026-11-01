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
  needed_by: string | null;
  urgency: "Emergency" | "Today" | "Planned" | null;
  status: "Recorded" | "Acknowledged" | "In Progress";
  /** UTC, ISO 8601. */
  recorded_at: string;
};

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
  needed_by: string | null;
  urgency: "Emergency" | "Today" | "Planned" | null;
  status: "Draft" | "Recorded" | "Acknowledged" | "In Progress" | "Resolved";
  source: "ai_call" | "coordinator";
  /** UTC, ISO 8601. */
  recorded_at: string;
  /** Oldest first. */
  events: RequestEvent[];
  /** Calls that created, looked up or amended the request; oldest first. */
  calls: LinkedCall[];
};

/** A call linked to a request (`call_requests`). */
export type LinkedCall = {
  id: number;
  /** UTC, ISO 8601. */
  started_at: string;
  relation: "created" | "looked_up" | "amended";
};

/** One turn of a call's transcript: what the Foreman ("user") or the agent said. */
export type TranscriptTurn = { role: "agent" | "user"; message: string; at_s: number };

/** A call's post-call record (`GET /api/calls/{id}`); empty transcript until it arrives. */
export type CallRecord = {
  id: number;
  /** UTC, ISO 8601. */
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  /** What was said, in order. */
  transcript: TranscriptTurn[];
};

export async function fetchCall(accessToken: string, id: number): Promise<CallRecord> {
  const response = await fetch(`/api/calls/${id}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`GET /api/calls/${id} failed: ${response.status}`);
  return (await response.json()) as CallRecord;
}

/**
 * The call's recording, streamed by the backend from ElevenLabs. Fetched with the token (an
 * <audio src> could not send it); null when there is no recording (any more).
 */
export async function fetchCallAudio(accessToken: string, id: number): Promise<Blob | null> {
  const response = await fetch(`/api/calls/${id}/audio`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`GET /api/calls/${id}/audio failed: ${response.status}`);
  return await response.blob();
}

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
