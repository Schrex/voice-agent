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
