// Vitest runs in UTC (vite.config.ts), so these prove times are shown in America/New_York
// whatever the browser's own zone.
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { QueueRequest } from "./api";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com", role: "coordinator" };

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok-pat" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

function row(overrides: Partial<QueueRequest>): QueueRequest {
  return {
    ref: "R-1000",
    job: "Route 104 Widening",
    job_spoken: "the 104 job",
    need: "tri-axle dump trucks",
    quantity: "3",
    unit: "trucks",
    needed_by: "tomorrow at seven",
    urgency: "Today",
    status: "Recorded",
    recorded_at: "2026-11-02T01:30:00Z",
    ...overrides,
  };
}

function serve(requests: QueueRequest[]) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === "/api/requests") return new Response(JSON.stringify({ requests }));
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function renderQueue() {
  window.history.pushState({}, "", "/");
  render(<App auth={signedIn} />);
  return await screen.findByRole("table");
}

describe("queue", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    // 2026-11-02 03:30 UTC = Sunday, November 1, 10:30 PM in New York (EST, after DST ends).
    vi.setSystemTime(new Date("2026-11-02T03:30:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("lists each open request's fields in the order the backend sent", async () => {
    const fetchMock = serve([
      row({ ref: "R-1001", need: "excavator", quantity: null, unit: null, urgency: "Emergency" }),
      row({ ref: "R-1000", status: "Acknowledged", needed_by: null, urgency: null }),
    ]);

    const table = await renderQueue();

    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Ref",
      "Job",
      "Need",
      "Quantity",
      "Needed-by",
      "Urgency",
      "Status",
      "Age",
    ]);
    const [first, second] = within(table).getAllByRole("row").slice(1);
    expect(within(first).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "R-1001",
      "Route 104 Widening",
      "excavator",
      "—",
      "tomorrow at seven",
      "Emergency",
      "Recorded",
      expect.stringMatching(/^2h 0m/),
    ]);
    expect(within(second).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "R-1000",
      "Route 104 Widening",
      "tri-axle dump trucks",
      "3 trucks",
      "—",
      "—",
      "Acknowledged",
      expect.stringMatching(/^2h 0m/),
    ]);
    expect(fetchMock).toHaveBeenCalledWith("/api/requests", {
      headers: { Authorization: "Bearer tok-pat" },
    });
  });

  it("flags a request whose Job matched nothing as Unmatched, with what the Foreman said", async () => {
    serve([
      row({ ref: "R-1001", job: null, job_spoken: "the Smith pit" }),
      row({ ref: "R-1000" }),
    ]);

    const table = await renderQueue();

    const [unmatched, matched] = within(table).getAllByRole("row").slice(1);
    const jobCell = within(unmatched).getAllByRole("cell")[1];
    expect(jobCell).toHaveTextContent("Unmatched: “the Smith pit”");
    expect(within(jobCell).getByText("Unmatched")).toHaveClass("flag");
    expect(within(matched).getAllByRole("cell")[1]).toHaveTextContent(/^Route 104 Widening$/);
  });

  it("shows when a request was recorded in New York time across the UTC date line", async () => {
    // 01:30 UTC on Nov 2 is still Nov 1 (8:30 PM EST, UTC-5) in New York.
    serve([row({ recorded_at: "2026-11-02T01:30:00Z" })]);
    expect(new Date("2026-11-02T01:30:00Z").getUTCDate()).toBe(2);

    const table = await renderQueue();

    const age = within(table).getAllByRole("cell").at(-1)!;
    expect(age).toHaveTextContent("Recorded Sun, Nov 1, 8:30 PM");
    expect(age).not.toHaveTextContent("Nov 2");
  });

  it("shows age in minutes, hours and days", async () => {
    serve([
      row({ ref: "R-1", recorded_at: "2026-11-02T03:29:40Z" }),
      row({ ref: "R-2", recorded_at: "2026-11-02T03:15:00Z" }),
      row({ ref: "R-3", recorded_at: "2026-10-29T22:00:00Z" }),
    ]);

    const table = await renderQueue();

    const ages = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((r) => within(r).getAllByRole("cell").at(-1)!.textContent);
    expect(ages[0]).toMatch(/^0m/);
    expect(ages[1]).toMatch(/^15m/);
    expect(ages[2]).toMatch(/^3d 5h/);
  });

  it("says so when there are no open requests", async () => {
    serve([]);
    window.history.pushState({}, "", "/");
    render(<App auth={signedIn} />);

    expect(await screen.findByText("No requests.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
