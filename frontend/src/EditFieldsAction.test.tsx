import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { RequestDetail } from "./api";

const STAFF = {
  id: "u-1",
  name: "Pat Lee",
  email: "pat@example.com",
};
const JOBS = [
  { id: 2, name: "Penfield Sewer Replacement" },
  { id: 1, name: "Route 104 Widening" },
];

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok-pat" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

const UNMATCHED: RequestDetail = {
  ref: "R-1000",
  foreman: "Dale Kramer",
  job: null,
  job_id: null,
  job_spoken: "the Smith pit",
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
  default_owner_id: null,
  events: [],
  calls: [],
};

const FIXED: RequestDetail = {
  ...UNMATCHED,
  job: "Penfield Sewer Replacement",
  job_id: 2,
  events: [
    {
      at: "2026-11-02T01:40:00Z",
      actor: { type: "staff", id: "u-1", name: "Pat Lee" },
      kind: "edited",
      before: { job_id: null },
      after: { job_id: 2 },
    },
  ],
};

/** Serves `initial` until a PATCH succeeds, then `afterEdit` (or answers `editStatus`). */
function serve(initial: RequestDetail, afterEdit = FIXED, editStatus = 200) {
  let current = initial;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === "/api/owners")
      return new Response(JSON.stringify({ owners: [] }));
    if (url === "/api/jobs")
      return new Response(JSON.stringify({ jobs: JOBS }));
    if (url === "/api/requests/R-1000" && init?.method === "PATCH") {
      if (editStatus !== 200) {
        return new Response(JSON.stringify({ detail: "nope" }), {
          status: editStatus,
        });
      }
      current = afterEdit;
      return new Response(JSON.stringify(current));
    }
    if (url === "/api/requests/R-1000")
      return new Response(JSON.stringify(current));
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
  return within(fields).getByText(term, { selector: "dt" }).nextElementSibling
    ?.textContent;
}

async function openEdit() {
  await userEvent.click(
    await screen.findByRole("button", { name: "Edit fields" }),
  );
  return screen.getByRole("form", { name: "Edit fields" });
}

function patchBodies(fetchMock: ReturnType<typeof serve>): unknown[] {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method === "PATCH")
    .map(([, init]) => JSON.parse(init!.body as string));
}

describe("edit fields / fix the Job", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("fixes the Job of an Unmatched request; the flag disappears", async () => {
    const fetchMock = serve(UNMATCHED);
    renderDetail();
    await screen.findByRole("heading", { name: "R-1000" });
    expect(field("Job")).toContain("Unmatched");

    const form = await openEdit();
    await within(form).findByRole("option", {
      name: "Penfield Sewer Replacement",
    });
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "Job" }),
      "2",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/requests/R-1000", {
      method: "PATCH",
      headers: {
        Authorization: "Bearer tok-pat",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ job_id: 2 }),
    });
    await screen.findByText("Penfield Sewer Replacement", { selector: "dd" });
    expect(field("Job")).not.toContain("Unmatched");
    expect(
      screen.queryByRole("form", { name: "Edit fields" }),
    ).not.toBeInTheDocument();
    const history = screen.getByRole("table", { name: "History" });
    expect(
      within(history).getByText("Edited", { selector: "td" }),
    ).toBeInTheDocument();
  });

  it("sends only the fields that changed", async () => {
    const fetchMock = serve({
      ...UNMATCHED,
      job: "Route 104 Widening",
      job_id: 1,
    });
    renderDetail();

    const form = await openEdit();
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "Category" }),
      "Material",
    );
    const need = within(form).getByRole("textbox", { name: "Need" });
    await userEvent.clear(need);
    await userEvent.type(need, "#2 stone");
    await userEvent.type(
      within(form).getByRole("textbox", { name: "Quantity" }),
      "40",
    );
    await userEvent.type(
      within(form).getByRole("textbox", { name: "Unit" }),
      "tons",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(patchBodies(fetchMock)).toEqual([
      { category: "Material", need: "#2 stone", quantity: "40", unit: "tons" },
    ]);
  });

  it("clears an emptied quantity and unit", async () => {
    const fetchMock = serve({ ...UNMATCHED, quantity: "3", unit: "trucks" });
    renderDetail();

    const form = await openEdit();
    await userEvent.clear(
      within(form).getByRole("textbox", { name: "Quantity" }),
    );
    await userEvent.clear(within(form).getByRole("textbox", { name: "Unit" }));
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(patchBodies(fetchMock)).toEqual([{ quantity: null, unit: null }]);
  });

  it("cannot save with nothing changed or a blank need", async () => {
    const fetchMock = serve(UNMATCHED);
    renderDetail();

    const form = await openEdit();
    const save = within(form).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await userEvent.clear(within(form).getByRole("textbox", { name: "Need" }));
    expect(save).toBeDisabled();
    expect(patchBodies(fetchMock)).toEqual([]);
  });

  it("offers every category of the glossary", async () => {
    serve(UNMATCHED);
    renderDetail();

    const form = await openEdit();
    const options = within(
      within(form).getByRole("combobox", { name: "Category" }),
    ).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "Trucking",
      "Equipment",
      "Equipment Repair",
      "Material",
      "Labor",
      "Information",
      "Callback",
      "Other",
    ]);
  });

  it("says so when the backend refuses, and keeps the form", async () => {
    serve(UNMATCHED, FIXED, 422);
    renderDetail();

    const form = await openEdit();
    await within(form).findByRole("option", {
      name: "Penfield Sewer Replacement",
    });
    await userEvent.selectOptions(
      within(form).getByRole("combobox", { name: "Job" }),
      "2",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Could not save",
    );
    expect(field("Job")).toContain("Unmatched");
  });

  it("can be cancelled", async () => {
    serve(UNMATCHED);
    renderDetail();

    const form = await openEdit();
    await userEvent.click(within(form).getByRole("button", { name: "Cancel" }));
    expect(
      screen.queryByRole("form", { name: "Edit fields" }),
    ).not.toBeInTheDocument();
  });

  it("is not offered when the backend does not allow edit (a Resolved request)", async () => {
    serve({
      ...UNMATCHED,
      status: "Resolved",
      allowed_actions: ["mark_informed", "note"],
      outcome: "Denied",
      explanation: "No trucks",
      resolved_at: "2026-11-02T02:00:00Z",
    });
    renderDetail();

    await screen.findByRole("heading", { name: "R-1000" });
    expect(
      screen.queryByRole("button", { name: "Edit fields" }),
    ).not.toBeInTheDocument();
  });
});
