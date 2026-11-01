import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { RequestDetail } from "./api";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com", role: "coordinator" };

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok-pat" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

const ACKNOWLEDGED: RequestDetail = {
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
  status: "Acknowledged",
  source: "ai_call",
  recorded_at: "2026-11-02T01:30:00Z",
  owner: { id: 1, name: "Dispatch" },
  acknowledged_at: "2026-11-02T01:40:00Z",
  outcome: null,
  explanation: null,
  resolved_at: null,
  default_owner_id: 1,
  events: [],
  calls: [],
};

const IN_PROGRESS: RequestDetail = {
  ...ACKNOWLEDGED,
  status: "In Progress",
  events: [
    {
      at: "2026-11-02T01:50:00Z",
      actor: { type: "staff", id: "u-1", name: "Pat Lee" },
      kind: "in_progress",
      before: { status: "Acknowledged" },
      after: { status: "In Progress" },
    },
  ],
};

const RESOLVED: RequestDetail = {
  ...IN_PROGRESS,
  status: "Resolved",
  outcome: "Denied",
  explanation: "No trucks free until Thursday",
  resolved_at: "2026-11-02T02:00:00Z",
  events: [
    ...IN_PROGRESS.events,
    {
      at: "2026-11-02T02:00:00Z",
      actor: { type: "staff", id: "u-1", name: "Pat Lee" },
      kind: "resolved",
      before: { status: "In Progress", outcome: null, explanation: null, resolved_at: null },
      after: {
        status: "Resolved",
        outcome: "Denied",
        explanation: "No trucks free until Thursday",
        resolved_at: "2026-11-02T02:00:00Z",
      },
    },
  ],
};

/** Serves `initial`; a POST to `action` answers `actionStatus` and, on 200, switches to `after`. */
function serve(
  initial: RequestDetail,
  action: "start" | "resolve",
  after: RequestDetail,
  actionStatus = 200,
) {
  let current = initial;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === "/api/owners") return new Response(JSON.stringify({ owners: [] }));
    if (url === `/api/requests/R-1000/${action}` && init?.method === "POST") {
      if (actionStatus !== 200) {
        return new Response(JSON.stringify({ detail: "nope" }), { status: actionStatus });
      }
      current = after;
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

function field(term: string): string | null | undefined {
  const fields = screen.getByRole("group", { name: "Fields" });
  return within(fields).queryByText(term, { selector: "dt" })?.nextElementSibling?.textContent;
}

describe("move to In Progress", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("moves an Acknowledged request to In Progress", async () => {
    const fetchMock = serve(ACKNOWLEDGED, "start", IN_PROGRESS);
    renderDetail();

    await userEvent.click(await screen.findByRole("button", { name: "Move to In Progress" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000/start", {
      method: "POST",
      headers: { Authorization: "Bearer tok-pat" },
    });
    await screen.findByText("In Progress", { selector: "dd" });
    expect(screen.queryByRole("button", { name: "Move to In Progress" })).not.toBeInTheDocument();
    const history = screen.getByRole("table", { name: "History" });
    expect(within(history).getByText("In Progress", { selector: "td" })).toBeInTheDocument();
  });

  it("says so when the backend refuses", async () => {
    serve(ACKNOWLEDGED, "start", IN_PROGRESS, 422);
    renderDetail();

    await userEvent.click(await screen.findByRole("button", { name: "Move to In Progress" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not move");
    expect(field("Status")).toBe("Acknowledged");
  });

  it.each(["Recorded", "In Progress", "Resolved"] as const)("is not offered when %s", async (s) => {
    serve({ ...RESOLVED, status: s }, "start", IN_PROGRESS);
    renderDetail();

    await screen.findByRole("heading", { name: "R-1000" });
    expect(screen.queryByRole("button", { name: "Move to In Progress" })).not.toBeInTheDocument();
  });
});

describe("resolve", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("offers the four Outcomes", async () => {
    serve(IN_PROGRESS, "resolve", RESOLVED);
    renderDetail();

    const outcome = await screen.findByRole("combobox", { name: "Outcome" });
    const options = within(outcome)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual([
      "Choose an Outcome",
      "Fulfilled",
      "Partially Fulfilled",
      "Denied",
      "Withdrawn",
    ]);
  });

  it("resolves with the Outcome and explanation; the request shows them", async () => {
    const fetchMock = serve(IN_PROGRESS, "resolve", RESOLVED);
    renderDetail();

    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Outcome" }), "Denied");
    await userEvent.type(
      screen.getByRole("textbox", { name: "Explanation" }),
      "No trucks free until Thursday",
    );
    await userEvent.click(screen.getByRole("button", { name: "Resolve" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000/resolve", {
      method: "POST",
      headers: { Authorization: "Bearer tok-pat", "Content-Type": "application/json" },
      body: JSON.stringify({ outcome: "Denied", explanation: "No trucks free until Thursday" }),
    });
    await screen.findByText("Resolved", { selector: "dd" });
    expect(field("Outcome")).toBe("Denied");
    expect(field("Explanation")).toBe("No trucks free until Thursday");
    expect(screen.queryByRole("button", { name: "Resolve" })).not.toBeInTheDocument();
  });

  it.each([
    ["no Outcome", "", "Sent two"],
    ["no explanation", "Fulfilled", ""],
    ["a blank explanation", "Fulfilled", "   "],
  ])("cannot resolve with %s", async (_, outcome, explanation) => {
    const fetchMock = serve(IN_PROGRESS, "resolve", RESOLVED);
    renderDetail();

    const select = await screen.findByRole("combobox", { name: "Outcome" });
    if (outcome) await userEvent.selectOptions(select, outcome);
    if (explanation) {
      await userEvent.type(screen.getByRole("textbox", { name: "Explanation" }), explanation);
    }
    const button = screen.getByRole("button", { name: "Resolve" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(fetchMock).not.toHaveBeenCalledWith("/api/requests/R-1000/resolve", expect.anything());
  });

  it("says so when the backend refuses", async () => {
    serve(IN_PROGRESS, "resolve", RESOLVED, 422);
    renderDetail();

    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Outcome" }), "Denied");
    await userEvent.type(screen.getByRole("textbox", { name: "Explanation" }), "No trucks");
    await userEvent.click(screen.getByRole("button", { name: "Resolve" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not resolve");
    expect(field("Status")).toBe("In Progress");
  });

  it.each(["Recorded", "Acknowledged"] as const)("is offered when %s", async (s) => {
    serve({ ...IN_PROGRESS, status: s }, "resolve", RESOLVED);
    renderDetail();

    expect(await screen.findByRole("button", { name: "Resolve" })).toBeInTheDocument();
  });

  it.each(["Draft", "Resolved"] as const)("is not offered when %s", async (s) => {
    serve({ ...RESOLVED, status: s }, "resolve", RESOLVED);
    renderDetail();

    await screen.findByRole("heading", { name: "R-1000" });
    expect(screen.queryByRole("button", { name: "Resolve" })).not.toBeInTheDocument();
  });

  it("shows no Outcome fields before the request is Resolved", async () => {
    serve(IN_PROGRESS, "resolve", RESOLVED);
    renderDetail();

    await screen.findByRole("heading", { name: "R-1000" });
    expect(field("Outcome")).toBeUndefined();
    expect(field("Explanation")).toBeUndefined();
  });
});
