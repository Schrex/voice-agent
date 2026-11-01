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
