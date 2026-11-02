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
  /** Still Recorded after its ack window (Today 15 min, Planned 2 h): the backup is texted. */
  overdue: boolean;
  /** The Foreman asked by phone to change it at or after In Progress; nothing was changed. */
  change_requested: boolean;
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

/** An alert that could not be sent, for a request still open (`GET /api/alerts/failed`). */
export type FailedAlert = {
  ref: string | null;
  kind: "today_new" | "callback" | "emergency" | "overdue" | "transfer" | "eod_summary";
  channel: "sms" | "email" | "popup";
  /** When it was attempted; UTC, ISO 8601. */
  at: string;
  /** Why it was not sent. */
  detail: string | null;
};

export async function fetchFailedAlerts(accessToken: string): Promise<FailedAlert[]> {
  const response = await fetch("/api/alerts/failed", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`GET /api/alerts/failed failed: ${response.status}`);
  return ((await response.json()) as { alerts: FailedAlert[] }).alerts;
}

/** A dashboard pop-up nobody has dismissed yet (ticket #25: incoming transfer). */
export type Popup = {
  id: number;
  kind: "transfer" | "emergency";
  /** E.g. "Incoming transfer: Dale Kramer, Route 104 Widening, about: not stated". */
  text: string;
  /** When it was raised; UTC, ISO 8601. */
  at: string;
};

export async function fetchPopups(accessToken: string): Promise<Popup[]> {
  const response = await fetch("/api/popups", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`GET /api/popups failed: ${response.status}`);
  return ((await response.json()) as { popups: Popup[] }).popups;
}

/** Hide the pop-up for every Coordinator. */
export async function dismissPopup(accessToken: string, id: number): Promise<void> {
  const response = await fetch(`/api/popups/${id}/dismiss`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`POST /api/popups/${id}/dismiss failed: ${response.status}`);
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
  /** Null when Unmatched (ticket #31; optional so fixtures without it still type-check). */
  job_id?: number | null;
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
  /** UTC, ISO 8601; null while the request is a Draft. */
  recorded_at: string | null;
  owner: Owner | null;
  /** UTC, ISO 8601; null until Acknowledged. */
  acknowledged_at: string | null;
  /** Set with explanation and resolved_at when Resolved; null before. */
  outcome: Outcome | null;
  explanation: string | null;
  /** UTC, ISO 8601; null until Resolved. */
  resolved_at: string | null;
  /** Ref of the request this one was merged into; null if not merged. */
  merged_into?: string | null;
  /** UTC, ISO 8601; null until a coordinator marks Foreman Informed. */
  foreman_informed_at: string | null;
  /** Resolved, not marked Foreman Informed within the threshold (as of the backend's clock). */
  uninformed: boolean;
  /** The category's default Owner, offered first when acknowledging. */
  default_owner_id: number | null;
  /** Oldest first. */
  events: RequestEvent[];
  /** Calls that created, looked up or amended the request; oldest first. */
  calls: LinkedCall[];
  /** Oldest first (ticket #17; optional so fixtures without it still type-check). */
  notes?: RequestNote[];
};

/** A note on a request, optionally urgent (`request_notes`). */
export type RequestNote = {
  /** UTC, ISO 8601. */
  at: string;
  author_type: "agent" | "staff" | "system";
  /** The staff member's name; null for the agent. */
  author: string | null;
  text: string;
  urgent: boolean;
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

/** A Request the Foreman did not confirm (`GET /api/drafts`); never part of the queue. */
export type Draft = {
  ref: string;
  foreman: string;
  job: string | null;
  job_spoken: string; // "" when no Job was said
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

/** The person or team responsible for fulfilling a request. */
export type Owner = { id: number; name: string };

/** Every Owner, sorted by name (`GET /api/owners`). */
export async function fetchOwners(accessToken: string): Promise<Owner[]> {
  const response = await fetch("/api/owners", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`GET /api/owners failed: ${response.status}`);
  return ((await response.json()) as { owners: Owner[] }).owners;
}

/** Recorded → Acknowledged with an Owner; resolves to the updated request. */
export async function acknowledgeRequest(
  accessToken: string,
  ref: string,
  ownerId: number,
): Promise<RequestDetail> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}/acknowledge`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ owner_id: ownerId }),
  });
  if (!response.ok) throw new Error(`acknowledge ${ref} failed: ${response.status}`);
  return (await response.json()) as RequestDetail;
}

/** Reassign owner (spec J9) of an Acknowledged or In Progress request; resolves to it updated. */
export async function reassignOwner(
  accessToken: string,
  ref: string,
  ownerId: number,
): Promise<RequestDetail> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}/owner`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ owner_id: ownerId }),
  });
  if (!response.ok) throw new Error(`reassign ${ref} failed: ${response.status}`);
  return (await response.json()) as RequestDetail;
}

/** Add note (spec J9): a coordinator's note, as typed; resolves to the updated request. */
export async function addNote(accessToken: string, ref: string, text: string): Promise<RequestDetail> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}/notes`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) throw new Error(`note on ${ref} failed: ${response.status}`);
  return (await response.json()) as RequestDetail;
}

/** How a Resolved request ended (glossary "Outcome"). */
export const OUTCOMES = ["Fulfilled", "Partially Fulfilled", "Denied", "Withdrawn"] as const;
export type Outcome = (typeof OUTCOMES)[number];

/** Acknowledged → In Progress; resolves to the updated request. */
export async function startRequest(accessToken: string, ref: string): Promise<RequestDetail> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}/start`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`start ${ref} failed: ${response.status}`);
  return (await response.json()) as RequestDetail;
}

/** Any open status → Resolved with an Outcome and explanation; resolves to the updated request. */
export async function resolveRequest(
  accessToken: string,
  ref: string,
  outcome: Outcome,
  explanation: string,
): Promise<RequestDetail> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}/resolve`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ outcome, explanation }),
  });
  if (!response.ok) throw new Error(`resolve ${ref} failed: ${response.status}`);
  return (await response.json()) as RequestDetail;
}

/** Merge this request into `into`: it is Resolved with the Outcome and explanation, pointing to `into`. */
export async function mergeRequest(
  accessToken: string,
  ref: string,
  into: string,
  outcome: Outcome,
  explanation: string,
): Promise<RequestDetail> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}/merge`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ into, outcome, explanation }),
  });
  if (!response.ok) throw new Error(`merge ${ref} failed: ${response.status}`);
  return (await response.json()) as RequestDetail;
}

/** Request categories (glossary "Category"), in the spec's order. */
export const CATEGORIES = [
  "Trucking",
  "Equipment",
  "Equipment Repair",
  "Material",
  "Labor",
  "Information",
  "Callback",
  "Other",
] as const;

/** An active Job a request can be fixed to. */
export type JobChoice = { id: number; name: string };

/** Every active Job, sorted by name (`GET /api/jobs`). */
export async function fetchJobs(accessToken: string): Promise<JobChoice[]> {
  const response = await fetch("/api/jobs", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`GET /api/jobs failed: ${response.status}`);
  return ((await response.json()) as { jobs: JobChoice[] }).jobs;
}

/** The fields a coordinator can edit; only the ones sent change. */
export type RequestEdit = Partial<{
  job_id: number;
  category: string;
  need: string;
  quantity: string | null;
  unit: string | null;
}>;

/** Edit fields / fix the Job; resolves to the updated request. */
export async function editRequest(
  accessToken: string,
  ref: string,
  changes: RequestEdit,
): Promise<RequestDetail> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  if (!response.ok) throw new Error(`edit ${ref} failed: ${response.status}`);
  return (await response.json()) as RequestDetail;
}

/** A Resolved request whose Foreman has not been told the Outcome in time (dashboard only). */
export type UninformedRequest = {
  ref: string;
  /** Who to tell. */
  foreman: string;
  /** Null when Unmatched. */
  job: string | null;
  job_spoken: string;
  need: string;
  outcome: Outcome;
  /** UTC, ISO 8601. */
  resolved_at: string;
};

/** The Uninformed requests, oldest Resolved first (`GET /api/requests?flag=uninformed`). */
export async function fetchUninformed(accessToken: string): Promise<UninformedRequest[]> {
  const response = await fetch("/api/requests?flag=uninformed", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`GET uninformed requests failed: ${response.status}`);
  return ((await response.json()) as { requests: UninformedRequest[] }).requests;
}

/** Mark Foreman Informed on a Resolved request; resolves to the updated request. */
export async function markForemanInformed(
  accessToken: string,
  ref: string,
): Promise<RequestDetail> {
  const response = await fetch(`/api/requests/${encodeURIComponent(ref)}/informed`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`informed ${ref} failed: ${response.status}`);
  return (await response.json()) as RequestDetail;
}
