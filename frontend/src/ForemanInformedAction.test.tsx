// Vitest runs in UTC (vite.config.ts): times below prove the America/New_York display.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { RequestDetail } from "./api";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com" };

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok-pat" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

const RESOLVED: RequestDetail = {
  ref: "R-1000",
  foreman: "Dale Kramer",
  job: "Route 104 Widening",
  job_spoken: "Route 104",
  category: "Trucking",
  need: "tri-axle dump trucks",
  quantity: null,
  unit: null,
  needed_by: null,
  needed_by_spoken: null,
  urgency: null,
  status: "Resolved",
  allowed_actions: ["mark_informed", "note"],
  source: "ai_call",
  recorded_at: "2026-11-02T01:30:00Z",
  owner: { id: 1, name: "Dispatch" },
  acknowledged_at: "2026-11-02T01:40:00Z",
  outcome: "Fulfilled",
  explanation: "Two dumps sent",
  resolved_at: "2026-11-02T02:00:00Z",
  foreman_informed_at: null,
  uninformed: true,
  default_owner_id: 1,
  events: [],
  calls: [],
};

const INFORMED: RequestDetail = {
  ...RESOLVED,
  // Sunday, November 1, 9:30 PM in New York.
  foreman_informed_at: "2026-11-02T02:30:00Z",
  uninformed: false,
  allowed_actions: ["note"],
  events: [
    {
      at: "2026-11-02T02:30:00Z",
      actor: { type: "staff", id: "u-1", name: "Pat Lee" },
      kind: "foreman_informed",
      before: { foreman_informed_at: null },
      after: { foreman_informed_at: "2026-11-02T02:30:00Z" },
    },
  ],
};

function serve(initial: RequestDetail, markStatus = 200) {
  let current = initial;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === "/api/owners") return new Response(JSON.stringify({ owners: [] }));
    if (url === "/api/requests/R-1000/informed" && init?.method === "POST") {
      if (markStatus !== 200) return new Response("{}", { status: markStatus });
      current = INFORMED;
      return new Response(JSON.stringify(current));
    }
    if (url === "/api/requests/R-1000") return new Response(JSON.stringify(current));
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderDetail() {
  window.history.pushState({}, "", "/requests/R-1000");
  render(<App auth={signedIn} />);
}

describe("Foreman Informed", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("flags an Uninformed request and marks it Foreman Informed", async () => {
    const fetchMock = serve(RESOLVED);
    renderDetail();

    const section = await screen.findByRole("region", { name: "Foreman Informed" });
    expect(within(section).getByText("Uninformed")).toHaveClass("flag");
    expect(section).toHaveTextContent("Not marked Foreman Informed");

    await userEvent.click(within(section).getByRole("button", { name: "Mark Foreman Informed" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000/informed", {
      method: "POST",
      headers: { Authorization: "Bearer tok-pat" },
    });
    expect(await within(section).findByText(/Foreman Informed Sun, Nov 1, 9:30/)).toBeVisible();
    expect(within(section).queryByText("Uninformed")).not.toBeInTheDocument();
    expect(within(section).queryByRole("button")).not.toBeInTheDocument();
    const history = screen.getByRole("table", { name: "History" });
    expect(within(history).getByText("Foreman Informed", { selector: "td" })).toBeInTheDocument();
  });

  it("does not flag a Resolved request still within the threshold, but offers the mark", async () => {
    serve({ ...RESOLVED, uninformed: false });
    renderDetail();

    const section = await screen.findByRole("region", { name: "Foreman Informed" });
    expect(within(section).queryByText("Uninformed")).not.toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Mark Foreman Informed" })).toBeEnabled();
  });

  it("says so when the backend refuses", async () => {
    serve(RESOLVED, 422);
    renderDetail();

    await userEvent.click(await screen.findByRole("button", { name: "Mark Foreman Informed" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not mark");
  });

  it.each(["Draft", "Recorded", "Acknowledged", "In Progress"] as const)(
    "is not shown when %s (the backend does not allow mark_informed)",
    async (status) => {
      serve({
        ...RESOLVED,
        status,
        outcome: null,
        resolved_at: null,
        uninformed: false,
        allowed_actions: ["note"],
      });
      renderDetail();

      await screen.findByRole("heading", { name: "R-1000" });
      expect(screen.queryByRole("region", { name: "Foreman Informed" })).not.toBeInTheDocument();
    },
  );
});
