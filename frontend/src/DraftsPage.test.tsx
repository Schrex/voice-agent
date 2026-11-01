import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com", role: "coordinator" };

const DRAFT = {
  ref: "R-1000",
  foreman: "Dale Kramer",
  job: "Route 104 Widening",
  job_spoken: "Route 104",
  category: "Trucking",
  need: "tri-axle dump trucks",
  quantity: "2",
  unit: "trucks",
  needed_by_spoken: "tomorrow at 7 AM",
  // 01:30 UTC on 2 Nov is 8:30 PM on 1 Nov in New York, whatever the browser's zone.
  call_started_at: "2026-11-02T01:30:00Z",
  call_summary: "Dale asked for trucks and hung up before confirming.",
};

function signedIn(): AuthClient {
  return {
    getSession: async () => ({ accessToken: "tok-pat" }),
    onChange: () => () => {},
    signIn: async () => ({ error: null }),
    signOut: async () => {},
  };
}

/** A fake backend: /api/me, /api/drafts (the given list), and the record action. */
function backend(drafts: unknown[], recordStatus = 200) {
  let current = drafts;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF), { status: 200 });
    if (url === "/api/drafts") return new Response(JSON.stringify({ drafts: current }), { status: 200 });
    if (url.endsWith("/record") && init?.method === "POST") {
      if (recordStatus === 200) current = [];
      return new Response(JSON.stringify({ ref: "R-1000", status: "Recorded" }), { status: recordStatus });
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(<App auth={signedIn()} />);
}

describe("Drafts page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists Drafts with what the Foreman said and the call", async () => {
    backend([DRAFT]);
    renderAt("/drafts");

    expect(await screen.findByRole("heading", { name: "Drafts" })).toBeInTheDocument();
    const row = await screen.findByRole("row", { name: /R-1000/ });
    expect(within(row).getByText("Dale Kramer")).toBeInTheDocument();
    expect(within(row).getByText("Route 104 Widening")).toBeInTheDocument();
    expect(within(row).getByText("tri-axle dump trucks")).toBeInTheDocument();
    expect(within(row).getByText("2 trucks")).toBeInTheDocument();
    expect(within(row).getByText("tomorrow at 7 AM")).toBeInTheDocument();
    expect(within(row).getByText(/Sun, Nov 1, 8:30\sPM/)).toBeInTheDocument();
    expect(within(row).getByText(DRAFT.call_summary)).toBeInTheDocument();
  });

  it("shows the Job as spoken when it matched no Job", async () => {
    backend([{ ...DRAFT, job: null, job_spoken: "the 104" }]);
    renderAt("/drafts");

    const row = await screen.findByRole("row", { name: /R-1000/ });
    expect(within(row).getByText("Unmatched")).toBeInTheDocument();
    expect(row).toHaveTextContent("Unmatched: “the 104”");
    // Recording it makes an Unmatched Recorded request (spec AC1.4).
    expect(within(row).getByRole("button", { name: "Record" })).toBeEnabled();
  });

  it("shows Unmatched with nothing said when no Job was named", async () => {
    backend([{ ...DRAFT, job: null, job_spoken: "" }]);
    renderAt("/drafts");

    const row = await screen.findByRole("row", { name: /R-1000/ });
    expect(row).toHaveTextContent("Unmatched: not said");
  });

  it("says when there are no Drafts", async () => {
    backend([]);
    renderAt("/drafts");

    expect(await screen.findByText("No Drafts.")).toBeInTheDocument();
  });

  it("records a Draft and drops it from the list", async () => {
    const fetchMock = backend([DRAFT]);
    renderAt("/drafts");

    const row = await screen.findByRole("row", { name: /R-1000/ });
    await userEvent.click(within(row).getByRole("button", { name: "Record" }));

    expect(await screen.findByText("No Drafts.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000/record", {
      method: "POST",
      headers: { Authorization: "Bearer tok-pat" },
    });
  });

  it("shows an error when recording fails", async () => {
    backend([DRAFT], 422);
    renderAt("/drafts");

    const row = await screen.findByRole("row", { name: /R-1000/ });
    await userEvent.click(within(row).getByRole("button", { name: "Record" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("R-1000 could not be recorded");
  });

  it("is reached from the queue and links back to it", async () => {
    backend([]);
    renderAt("/");

    await userEvent.click(await screen.findByRole("link", { name: "Drafts" }));
    expect(await screen.findByRole("heading", { name: "Drafts" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("link", { name: "Queue" }));
    expect(await screen.findByRole("heading", { name: "Queue" })).toBeInTheDocument();
  });
});
