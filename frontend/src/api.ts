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
  /** UTC, ISO 8601. */
  recorded_at: string;
  owner: Owner | null;
  /** UTC, ISO 8601; null until Acknowledged. */
  acknowledged_at: string | null;
  /** The category's default Owner, offered first when acknowledging. */
  default_owner_id: number | null;
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
