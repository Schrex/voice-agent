/** Quick entry (spec J7): `GET /api/quick-entry` and `POST /api/requests`. */

export type Choice = { id: number; name: string };

/** What the form offers: active Foremen and Jobs, the Categories, every Owner. */
export type QuickEntryChoices = {
  foremen: Choice[];
  jobs: Choice[];
  categories: string[];
  owners: Choice[];
};

export type QuickEntry = {
  foreman_id: number;
  job_id: number;
  category: string;
  need: string;
  quantity: string | null;
  unit: string | null;
  /** As typed; the backend resolves it like a spoken needed-by. Null = unknown. */
  needed_by: string | null;
  /** Given → logged straight to Acknowledged. */
  owner_id: number | null;
};

export type Logged = { ref: string; status: "Recorded" | "Acknowledged" };

export async function fetchQuickEntryChoices(accessToken: string): Promise<QuickEntryChoices> {
  const response = await fetch("/api/quick-entry", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`GET /api/quick-entry failed: ${response.status}`);
  return (await response.json()) as QuickEntryChoices;
}

export async function logRequest(accessToken: string, entry: QuickEntry): Promise<Logged> {
  const response = await fetch("/api/requests", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  });
  if (!response.ok) throw new Error(`POST /api/requests failed: ${response.status}`);
  return (await response.json()) as Logged;
}
