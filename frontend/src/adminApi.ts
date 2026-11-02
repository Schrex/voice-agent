/** `/api/admin/*` (admin role only): foremen and jobs (#34); owners, staff, duty, settings (#35). */

export type Phone = { id: number; e164: string };
export type Foreman = {
  id: number;
  first_name: string;
  last_name: string;
  active: boolean;
  phones: Phone[];
};
export type JobAlias = { id: number; alias: string };
export type Job = { id: number; name: string; active: boolean; aliases: JobAlias[] };
export type Owner = { id: number; name: string; phone_e164: string | null; email: string | null };
export type CategoryDefault = { category: string; owner_id: number | null };
export type StaffMember = {
  id: string;
  name: string;
  email: string;
  role: "coordinator" | "admin";
  phone_e164: string | null;
};
export type DutyDay = {
  date: string;
  on_duty: { id: string; name: string };
  backup: { id: string; name: string } | null;
};
export type OfficeSettings = {
  office_line_e164: string | null;
  ack_window_today_min: number;
  ack_window_planned_min: number;
};

/** A refused request; `message` is the backend's reason, fit to show the admin. */
export class AdminApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function adminFetch<T>(
  accessToken: string,
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${accessToken}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/admin${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new AdminApiError(response.status, await reason(response));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function reason(response: Response): Promise<string> {
  try {
    const { detail } = (await response.json()) as { detail?: unknown };
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: a list of {msg, loc}.
    if (Array.isArray(detail) && detail.length > 0) {
      return "Check the entry: " + String((detail[0] as { msg?: unknown }).msg ?? "invalid value");
    }
  } catch {
    // fall through
  }
  return `The change was not saved (error ${response.status}).`;
}
