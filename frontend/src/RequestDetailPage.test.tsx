// Vitest runs in UTC (vite.config.ts), so these prove times are shown in America/New_York
// whatever the browser's own zone.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { QueueRequest, RequestDetail } from "./api";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com", role: "coordinator" };

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok-pat" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

const DETAIL: RequestDetail = {
  ref: "R-1000",
  foreman: "Dale Kramer",
  job: "Route 104 Widening",
  job_spoken: "the 104 job",
  category: "Trucking",
  need: "tri-axle dump trucks",
  quantity: "3",
  unit: "trucks",
  needed_by: "2026-11-02T12:00:00Z",
  needed_by_spoken: "tomorrow at seven",
  urgency: "Planned",
  status: "Recorded",
  allowed_actions: ["acknowledge", "resolve", "merge", "edit", "note"],
  source: "ai_call",
  recorded_at: "2026-11-02T01:30:00Z",
  owner: null,
  acknowledged_at: null,
  outcome: null,
  explanation: null,
  resolved_at: null,
  foreman_informed_at: null,
  uninformed: false,
  default_owner_id: null,
  events: [
    {
      at: "2026-11-02T01:30:00Z",
      actor: { type: "agent", id: null, name: null },
      kind: "recorded",
      before: null,
      after: { ref: "R-1000", need: "tri-axle dump trucks", status: "Recorded" },
    },
    {
      at: "2026-11-02T02:05:00Z",
      actor: { type: "staff", id: "u-2", name: "Casey Ng" },
      kind: "edited",
      before: { unit: null },
      after: { unit: "trucks" },
    },
    {
      at: "2026-11-02T04:00:00Z",
      actor: { type: "system", id: null, name: null },
      kind: "flagged",
      before: { overdue: false },
      after: { overdue: true },
    },
  ],
  calls: [],
};

function serve(detail: RequestDetail | null, queue: QueueRequest[] = []) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === "/api/requests") return new Response(JSON.stringify({ requests: queue }));
    if (detail && url === `/api/requests/${detail.ref}`) return new Response(JSON.stringify(detail));
    return new Response(JSON.stringify({ detail: "No such request" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  render(<App auth={signedIn} />);
}

describe("request detail", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows an Unmatched Job with what the Foreman said", async () => {
    serve({ ...DETAIL, job: null, job_spoken: "the Smith pit" });
    renderAt("/requests/R-1000");

    expect(await screen.findByRole("heading", { name: "R-1000" })).toBeInTheDocument();
    const fields = screen.getByRole("group", { name: "Fields" });
    const job = within(fields).getByText("Job").nextElementSibling;
    expect(job).toHaveTextContent("Unmatched: “the Smith pit”");
  });

  it.each([
    [{ needed_by: null, needed_by_spoken: "next Tuesday" }, "“next Tuesday”"],
    [{ needed_by: null, needed_by_spoken: null }, "Unknown"],
  ])("shows a needed-by that was not resolved (%o) as %s", async (overrides, expected) => {
    serve({ ...DETAIL, ...overrides });
    renderAt("/requests/R-1000");

    expect(await screen.findByRole("heading", { name: "R-1000" })).toBeInTheDocument();
    const fields = screen.getByRole("group", { name: "Fields" });
    expect(within(fields).getByText("Needed-by").nextElementSibling).toHaveTextContent(
      new RegExp(`^${expected}$`),
    );
  });

  it("shows every field of the request", async () => {
    const fetchMock = serve(DETAIL);
    renderAt("/requests/R-1000");

    expect(await screen.findByRole("heading", { name: "R-1000" })).toBeInTheDocument();
    const fields = screen.getByRole("group", { name: "Fields" });
    const pairs = within(fields)
      .getAllByRole("term")
      .map((t) => [t.textContent, t.nextElementSibling?.textContent]);
    expect(pairs).toEqual([
      ["Foreman", "Dale Kramer"],
      ["Job", "Route 104 Widening"],
      ["Category", "Trucking"],
      ["Need", "tri-axle dump trucks"],
      ["Quantity", "3 trucks"],
      ["Needed-by", "Mon, Nov 2, 7:00 AM"],
      ["Urgency", "Planned"],
      ["Status", "Recorded"],
      ["Owner", "—"],
      ["Source", "AI call"],
      ["Recorded", "Sun, Nov 1, 8:30 PM"],
    ]);
    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000", {
      headers: { Authorization: "Bearer tok-pat" },
    });
  });

  it("shows the audit history oldest first: when (New York time), who, what changed", async () => {
    serve(DETAIL);
    renderAt("/requests/R-1000");

    const history = await screen.findByRole("table", { name: "History" });
    const headers = within(history).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["When", "Who", "What", "Changes"]);
    const rows = within(history)
      .getAllByRole("row")
      .slice(1)
      .map((r) => within(r).getAllByRole("cell").map((c) => c.textContent));
    expect(rows).toEqual([
      [
        "Sun, Nov 1, 8:30 PM",
        "Agent",
        "Recorded",
        "ref: R-1000need: tri-axle dump trucksstatus: Recorded",
      ],
      ["Sun, Nov 1, 9:05 PM", "Casey Ng", "Edited", "unit: — → trucks"],
      ["Sun, Nov 1, 11:00 PM", "System", "flagged", "overdue: false → true"],
    ]);
  });

  it("says so when the request does not exist", async () => {
    serve(null);
    renderAt("/requests/R-999");

    expect(await screen.findByText("No such request.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("opens from the queue by clicking the request", async () => {
    serve(DETAIL, [
      {
        ref: "R-1000",
        job: "Route 104 Widening",
        job_spoken: "the 104 job",
        need: "tri-axle dump trucks",
        quantity: "3",
        unit: "trucks",
        needed_by: "2026-11-02T12:00:00Z",
        needed_by_spoken: "tomorrow at seven",
        urgency: null,
        status: "Recorded",
        recorded_at: "2026-11-02T01:30:00Z",
        overdue: false,
        change_requested: false,
      },
    ]);
    renderAt("/");

    await userEvent.click(await screen.findByRole("link", { name: "R-1000" }));

    expect(await screen.findByRole("table", { name: "History" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/requests/R-1000");
  });
});
