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

const RECORDED: RequestDetail = {
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
  merged_into: null,
  default_owner_id: 1,
  events: [],
  calls: [],
};

const MERGED: RequestDetail = {
  ...RECORDED,
  status: "Resolved",
  allowed_actions: ["mark_informed", "note"],
  outcome: "Withdrawn",
  explanation: "Same trucks as R-1001",
  resolved_at: "2026-11-02T02:00:00Z",
  merged_into: "R-1001",
  events: [
    {
      at: "2026-11-02T02:00:00Z",
      actor: { type: "staff", id: "u-1", name: "Pat Lee" },
      kind: "merged",
      before: {
        status: "Recorded",
        outcome: null,
        explanation: null,
        resolved_at: null,
        merged_into: null,
      },
      after: {
        status: "Resolved",
        outcome: "Withdrawn",
        explanation: "Same trucks as R-1001",
        resolved_at: "2026-11-02T02:00:00Z",
        merged_into: "R-1001",
      },
    },
  ],
};

/** Serves `initial`; a merge POST answers `mergeStatus` and, on 200, switches to MERGED. */
function serve(initial: RequestDetail, mergeStatus = 200) {
  let current = initial;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === "/api/owners") return new Response(JSON.stringify({ owners: [] }));
    if (url === "/api/requests/R-1000/merge" && init?.method === "POST") {
      if (mergeStatus !== 200) {
        return new Response(JSON.stringify({ detail: "nope" }), { status: mergeStatus });
      }
      current = MERGED;
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

async function openMerge() {
  await userEvent.click(await screen.findByRole("button", { name: "Merge into another request" }));
  return screen.getByRole("form", { name: "Merge" });
}

function field(term: string): string | null | undefined {
  const fields = screen.getByRole("group", { name: "Fields" });
  return within(fields).queryByText(term, { selector: "dt" })?.nextElementSibling?.textContent;
}

describe("merge duplicates", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("merges into the given request with an Outcome and explanation", async () => {
    const fetchMock = serve(RECORDED);
    renderDetail();

    const form = await openMerge();
    await userEvent.type(within(form).getByRole("textbox", { name: "Merge into" }), " R-1001 ");
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Outcome" }), "Withdrawn");
    await userEvent.type(
      within(form).getByRole("textbox", { name: "Explanation" }),
      "Same trucks as R-1001",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Merge" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000/merge", {
      method: "POST",
      headers: { Authorization: "Bearer tok-pat", "Content-Type": "application/json" },
      body: JSON.stringify({
        into: "R-1001",
        outcome: "Withdrawn",
        explanation: "Same trucks as R-1001",
      }),
    });
    await screen.findByText("Resolved", { selector: "dd" });
    expect(field("Merged into")).toBe("R-1001");
    expect(screen.getByRole("link", { name: "R-1001" })).toHaveAttribute("href", "/requests/R-1001");
    const history = screen.getByRole("table", { name: "History" });
    expect(within(history).getByText("Merged", { selector: "td" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Merge into another request" })).not.toBeInTheDocument();
  });

  it.each([
    ["no ref", "", "Withdrawn", "Dup"],
    ["no Outcome", "R-1001", "", "Dup"],
    ["a blank explanation", "R-1001", "Withdrawn", "   "],
  ])("cannot merge with %s", async (_, into, outcome, explanation) => {
    const fetchMock = serve(RECORDED);
    renderDetail();

    const form = await openMerge();
    if (into) await userEvent.type(within(form).getByRole("textbox", { name: "Merge into" }), into);
    if (outcome) {
      await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Outcome" }), outcome);
    }
    await userEvent.type(within(form).getByRole("textbox", { name: "Explanation" }), explanation);
    const button = within(form).getByRole("button", { name: "Merge" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(fetchMock).not.toHaveBeenCalledWith("/api/requests/R-1000/merge", expect.anything());
  });

  it("says so when the backend refuses (into itself, a Resolved or unknown request)", async () => {
    serve(RECORDED, 422);
    renderDetail();

    const form = await openMerge();
    await userEvent.type(within(form).getByRole("textbox", { name: "Merge into" }), "R-1000");
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Outcome" }), "Withdrawn");
    await userEvent.type(within(form).getByRole("textbox", { name: "Explanation" }), "Dup");
    await userEvent.click(within(form).getByRole("button", { name: "Merge" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not merge");
    expect(field("Status")).toBe("Recorded");
  });

  it("is offered when the backend allows merge", async () => {
    serve({ ...RECORDED, status: "In Progress", allowed_actions: ["merge", "note"] });
    renderDetail();

    expect(
      await screen.findByRole("button", { name: "Merge into another request" }),
    ).toBeInTheDocument();
  });

  it("is not offered when the backend does not allow merge, whatever the status", async () => {
    // ADR 0004: the dashboard does not work out the lifecycle rules itself.
    serve({ ...RECORDED, status: "Recorded", allowed_actions: ["note"] });
    renderDetail();

    await screen.findByRole("heading", { name: "R-1000" });
    expect(screen.queryByRole("button", { name: "Merge into another request" })).not.toBeInTheDocument();
  });

  it("shows the request merged in on the target's history", async () => {
    serve({
      ...RECORDED,
      events: [
        {
          at: "2026-11-02T02:00:00Z",
          actor: { type: "staff", id: "u-1", name: "Pat Lee" },
          kind: "merged_in",
          before: { merged_from: null },
          after: { merged_from: "R-0999" },
        },
      ],
    });
    renderDetail();

    const history = await screen.findByRole("table", { name: "History" });
    expect(await within(history).findByText("Merged in", { selector: "td" })).toBeInTheDocument();
    expect(within(history).getByText("merged_from: — → R-0999")).toBeInTheDocument();
    expect(field("Merged into")).toBeUndefined();
  });
});
