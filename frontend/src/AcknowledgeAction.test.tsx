import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { Owner, RequestDetail } from "./api";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com", role: "coordinator" };
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
  urgency: null,
  status: "Recorded",
  source: "ai_call",
  recorded_at: "2026-11-02T01:30:00Z",
  owner: null,
  acknowledged_at: null,
  outcome: null,
  explanation: null,
  resolved_at: null,
  default_owner_id: 1,
  events: [],
  calls: [],
};

const ACKNOWLEDGED: RequestDetail = {
  ...RECORDED,
  status: "Acknowledged",
  owner: { id: 2, name: "Equipment Manager" },
  acknowledged_at: "2026-11-02T01:40:00Z",
  events: [
    {
      at: "2026-11-02T01:40:00Z",
      actor: { type: "staff", id: "u-1", name: "Pat Lee" },
      kind: "acknowledged",
      before: { status: "Recorded", owner_id: null, acknowledged_at: null },
      after: { status: "Acknowledged", owner_id: 2, acknowledged_at: "2026-11-02T01:40:00Z" },
    },
  ],
};

/** Serves `initial` until an acknowledge succeeds, then `afterAck` (or answers `ackStatus`). */
function serve(initial: RequestDetail, afterAck = ACKNOWLEDGED, ackStatus = 200) {
  let current = initial;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === "/api/owners") return new Response(JSON.stringify({ owners: OWNERS }));
    if (url === "/api/requests/R-1000/acknowledge" && init?.method === "POST") {
      if (ackStatus !== 200) {
        return new Response(JSON.stringify({ detail: "nope" }), { status: ackStatus });
      }
      current = afterAck;
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
  return within(fields).getByText(term, { selector: "dt" }).nextElementSibling?.textContent;
}

describe("acknowledge", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("offers the category's default Owner first", async () => {
    serve(RECORDED);
    renderDetail();

    const owner = await screen.findByRole("combobox", { name: "Owner" });
    await screen.findByRole("option", { name: "Dispatch" });
    expect(owner).toHaveValue("1");
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeEnabled();
  });

  it("acknowledges with the chosen Owner and shows the new status", async () => {
    const fetchMock = serve(RECORDED);
    renderDetail();

    await screen.findByRole("option", { name: "Equipment Manager" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Owner" }), "2");
    await userEvent.click(screen.getByRole("button", { name: "Acknowledge" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000/acknowledge", {
      method: "POST",
      headers: { Authorization: "Bearer tok-pat", "Content-Type": "application/json" },
      body: JSON.stringify({ owner_id: 2 }),
    });
    await screen.findByText("Acknowledged", { selector: "dd" });
    expect(field("Owner")).toBe("Equipment Manager");
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    const history = screen.getByRole("table", { name: "History" });
    expect(within(history).getByText("Acknowledged", { selector: "td" })).toBeInTheDocument();
  });

  it("cannot acknowledge without an Owner when the category has no default", async () => {
    const fetchMock = serve({ ...RECORDED, default_owner_id: null });
    renderDetail();

    await screen.findByRole("option", { name: "Dispatch" });
    expect(screen.getByRole("combobox", { name: "Owner" })).toHaveValue("");
    const button = screen.getByRole("button", { name: "Acknowledge" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/requests/R-1000/acknowledge",
      expect.anything(),
    );
  });

  it("says so when the backend refuses", async () => {
    serve(RECORDED, ACKNOWLEDGED, 422);
    renderDetail();

    await screen.findByRole("option", { name: "Dispatch" });
    await userEvent.click(screen.getByRole("button", { name: "Acknowledge" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not acknowledge");
    expect(field("Status")).toBe("Recorded");
  });

  it("is not offered once the request is past Recorded", async () => {
    serve(ACKNOWLEDGED);
    renderDetail();

    await screen.findByRole("heading", { name: "R-1000" });
    expect(field("Owner")).toBe("Equipment Manager");
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
  });
});
