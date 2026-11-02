import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { Owner, RequestDetail } from "./api";

// Spec J9 actions "Reassign owner" and "Add note" on the request detail.

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com" };
const OWNERS: Owner[] = [
  { id: 1, name: "Dispatch" },
  { id: 2, name: "Equipment Manager" },
];

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
  allowed_actions: ["start", "reassign", "resolve", "merge", "edit", "note"],
  source: "ai_call",
  recorded_at: "2026-11-02T01:30:00Z",
  owner: { id: 1, name: "Dispatch" },
  acknowledged_at: "2026-11-02T01:40:00Z",
  outcome: null,
  explanation: null,
  resolved_at: null,
  foreman_informed_at: null,
  uninformed: false,
  default_owner_id: 1,
  events: [],
  calls: [],
  notes: [],
};

function serve(initial: RequestDetail, after: RequestDetail) {
  let current = initial;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === "/api/owners") return new Response(JSON.stringify({ owners: OWNERS }));
    if (url === "/api/jobs") return new Response(JSON.stringify({ jobs: [] }));
    if (
      (url === "/api/requests/R-1000/owner" || url === "/api/requests/R-1000/notes") &&
      init?.method === "POST"
    ) {
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
  return render(<App auth={signedIn} />);
}

describe("Reassign owner", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("gives an Acknowledged request another Owner", async () => {
    const fetchMock = serve(ACKNOWLEDGED, {
      ...ACKNOWLEDGED,
      owner: { id: 2, name: "Equipment Manager" },
    });
    renderDetail();

    const form = await screen.findByRole("form", { name: "Reassign owner" });
    const select = within(form).getByLabelText("New Owner");
    await screen.findByRole("option", { name: "Equipment Manager" });
    await userEvent.selectOptions(select, "2");
    await userEvent.click(within(form).getByRole("button", { name: "Reassign" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000/owner", {
      method: "POST",
      headers: { Authorization: "Bearer tok-pat", "Content-Type": "application/json" },
      body: JSON.stringify({ owner_id: 2 }),
    });
    const fields = await screen.findByRole("group", { name: "Fields" });
    expect(await within(fields).findByText("Equipment Manager")).toBeInTheDocument();
  });

  it("is not offered when the backend does not allow reassign", async () => {
    serve({ ...ACKNOWLEDGED, allowed_actions: ["start", "resolve", "note"] }, ACKNOWLEDGED);
    renderDetail();

    await screen.findByRole("form", { name: "Add note" });
    expect(screen.queryByRole("form", { name: "Reassign owner" })).toBeNull();
  });
});

describe("Add note", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("appends a coordinator's note and shows it", async () => {
    const fetchMock = serve(ACKNOWLEDGED, {
      ...ACKNOWLEDGED,
      notes: [
        {
          at: "2026-11-02T01:50:00Z",
          author_type: "staff",
          author: "Pat Lee",
          text: "Called Dale back",
          urgent: false,
        },
      ],
    });
    renderDetail();

    const form = await screen.findByRole("form", { name: "Add note" });
    const add = within(form).getByRole("button", { name: "Add note" });
    expect(add).toBeDisabled();
    await userEvent.type(within(form).getByLabelText("Note"), "Called Dale back");
    await userEvent.click(add);

    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000/notes", {
      method: "POST",
      headers: { Authorization: "Bearer tok-pat", "Content-Type": "application/json" },
      body: JSON.stringify({ text: "Called Dale back" }),
    });
    const notes = await screen.findByRole("list", { name: "Notes" });
    expect(within(notes).getByText("Called Dale back")).toBeInTheDocument();
    expect(within(notes).getByText(/Pat Lee/)).toBeInTheDocument();
  });
});
