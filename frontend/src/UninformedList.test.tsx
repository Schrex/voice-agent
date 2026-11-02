// Vitest runs in UTC (vite.config.ts): times below prove the America/New_York display.
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { UninformedRequest } from "./api";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com", role: "coordinator" };

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok-pat" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

const UNINFORMED: UninformedRequest[] = [
  {
    ref: "R-1000",
    foreman: "Dale Kramer",
    job: "Route 104 Widening",
    job_spoken: "Route 104",
    need: "tri-axle dump trucks",
    outcome: "Denied",
    // Sunday, November 1, 9:00 PM in New York.
    resolved_at: "2026-11-02T02:00:00Z",
  },
  {
    ref: "R-1001",
    foreman: "Rita Owens",
    job: null,
    job_spoken: "the quarry",
    need: "pump",
    outcome: "Fulfilled",
    resolved_at: "2026-11-02T02:30:00Z",
  },
];

function serve(uninformed: UninformedRequest[] | null) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === "/api/requests") return new Response(JSON.stringify({ requests: [] }));
    if (url === "/api/requests?flag=uninformed") {
      if (uninformed === null) return new Response("{}", { status: 500 });
      return new Response(JSON.stringify({ requests: uninformed }));
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderQueue() {
  window.history.pushState({}, "", "/");
  render(<App auth={signedIn} />);
}

describe("Uninformed list on the queue page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the Uninformed count and each request with who to tell and the Outcome", async () => {
    const fetchMock = serve(UNINFORMED);
    renderQueue();

    expect(await screen.findByRole("heading", { name: "Uninformed (2)" })).toBeVisible();
    const table = screen.getByRole("table", { name: "Uninformed" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent))).toEqual([
      ["R-1000", "Dale Kramer", "Route 104 Widening", "tri-axle dump trucks", "Denied", "Sun, Nov 1, 9:00 PM"],
      ["R-1001", "Rita Owens", "Unmatched: “the quarry”", "pump", "Fulfilled", "Sun, Nov 1, 9:30 PM"],
    ]);
    expect(within(rows[0]).getByRole("link", { name: "R-1000" })).toHaveAttribute(
      "href",
      "/requests/R-1000",
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/requests?flag=uninformed", {
      headers: { Authorization: "Bearer tok-pat" },
    });
  });

  it("shows a zero count and no table when nothing is Uninformed", async () => {
    serve([]);
    renderQueue();

    expect(await screen.findByRole("heading", { name: "Uninformed (0)" })).toBeVisible();
    expect(screen.queryByRole("table", { name: "Uninformed" })).not.toBeInTheDocument();
  });

  it("says so when the list cannot be loaded", async () => {
    serve(null);
    renderQueue();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the Uninformed");
  });
});
