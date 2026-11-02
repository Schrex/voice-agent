import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com" };

const CHOICES = {
  foremen: [
    { id: 1, name: "Dale Kramer" },
    { id: 2, name: "Rita Owens" },
  ],
  jobs: [
    { id: 10, name: "Penfield Sewer Replacement" },
    { id: 11, name: "Route 104 Widening" },
  ],
  categories: ["Trucking", "Equipment", "Equipment Repair", "Material", "Labor", "Information", "Callback", "Other"],
  owners: [
    { id: 5, name: "Dispatch" },
    { id: 6, name: "Equipment Manager" },
  ],
};

function signedIn(): AuthClient {
  return {
    getSession: async () => ({ accessToken: "tok-pat" }),
    onChange: () => () => {},
    signIn: async () => ({ error: null }),
    signOut: async () => {},
  };
}

/** A fake backend: /api/me, /api/quick-entry, and POST /api/requests. */
function backend(logStatus = 201) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF), { status: 200 });
    if (url === "/api/quick-entry") return new Response(JSON.stringify(CHOICES), { status: 200 });
    if (url === "/api/requests" && init?.method === "POST") {
      const body = JSON.parse(init.body as string) as { owner_id: number | null };
      const status = body.owner_id === null ? "Recorded" : "Acknowledged";
      return new Response(JSON.stringify({ ref: "R-1004", status }), { status: logStatus });
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function posted(fetchMock: ReturnType<typeof backend>): unknown {
  const call = fetchMock.mock.calls.find(([url, init]) => url === "/api/requests" && init?.method === "POST");
  return call ? JSON.parse(call[1]!.body as string) : undefined;
}

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(<App auth={signedIn()} />);
}

describe("Quick entry page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("logs a request entered by keyboard alone and says it is Recorded", async () => {
    const fetchMock = backend();
    const user = userEvent.setup();
    renderAt("/quick-entry");

    const foreman = await screen.findByRole("combobox", { name: "Foreman" });
    await screen.findByRole("option", { name: "Dale Kramer" });
    expect(foreman).toHaveFocus();
    await user.selectOptions(foreman, "Dale Kramer");
    await user.selectOptions(screen.getByRole("combobox", { name: "Job" }), "Route 104 Widening");
    await user.selectOptions(screen.getByRole("combobox", { name: "Category" }), "Trucking");
    await user.type(screen.getByRole("textbox", { name: "Need" }), "tri-axle dump trucks");
    await user.type(screen.getByRole("textbox", { name: "Quantity" }), "3");
    await user.type(screen.getByRole("textbox", { name: "Unit" }), "trucks");
    await user.type(screen.getByRole("textbox", { name: "Needed-by" }), "tomorrow 7am{Enter}");

    expect(await screen.findByRole("status")).toHaveTextContent("R-1004 logged: Recorded.");
    expect(screen.getByRole("link", { name: "R-1004" })).toHaveAttribute("href", "/requests/R-1004");
    expect(posted(fetchMock)).toEqual({
      foreman_id: 1,
      job_id: 11,
      category: "Trucking",
      need: "tri-axle dump trucks",
      quantity: "3",
      unit: "trucks",
      needed_by: "tomorrow 7am",
      owner_id: null,
    });
    // Ready for the next call: cleared, Foreman focused.
    expect(screen.getByRole("textbox", { name: "Need" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Foreman" })).toHaveFocus();
  });

  it("logs straight to Acknowledged when an Owner is chosen; no Owner by default", async () => {
    const fetchMock = backend();
    const user = userEvent.setup();
    renderAt("/quick-entry");

    await screen.findByRole("option", { name: "Dale Kramer" });
    const owner = screen.getByRole("combobox", { name: "Owner (optional)" });
    expect(owner).toHaveDisplayValue("No Owner: stays Recorded");
    await user.selectOptions(screen.getByRole("combobox", { name: "Foreman" }), "Rita Owens");
    await user.selectOptions(screen.getByRole("combobox", { name: "Job" }), "Penfield Sewer Replacement");
    await user.selectOptions(screen.getByRole("combobox", { name: "Category" }), "Equipment");
    await user.type(screen.getByRole("textbox", { name: "Need" }), "mini excavator");
    await user.selectOptions(owner, "Equipment Manager");
    await user.click(screen.getByRole("button", { name: "Log request" }));

    expect(await screen.findByRole("status")).toHaveTextContent("R-1004 logged: Acknowledged.");
    expect(posted(fetchMock)).toMatchObject({
      foreman_id: 2,
      job_id: 10,
      category: "Equipment",
      need: "mini excavator",
      quantity: null,
      unit: null,
      needed_by: null,
      owner_id: 6,
    });
  });

  it("does not send without Foreman, Job, Category and Need", async () => {
    const fetchMock = backend();
    const user = userEvent.setup();
    renderAt("/quick-entry");

    await screen.findByRole("option", { name: "Dale Kramer" });
    await user.type(screen.getByRole("textbox", { name: "Need" }), "trucks{Enter}");

    expect(posted(fetchMock)).toBeUndefined();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("keeps what was typed and says so when the backend refuses it", async () => {
    backend(422);
    const user = userEvent.setup();
    renderAt("/quick-entry");

    await screen.findByRole("option", { name: "Dale Kramer" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Foreman" }), "Dale Kramer");
    await user.selectOptions(screen.getByRole("combobox", { name: "Job" }), "Route 104 Widening");
    await user.selectOptions(screen.getByRole("combobox", { name: "Category" }), "Trucking");
    await user.type(screen.getByRole("textbox", { name: "Need" }), "trucks{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("The request was not logged.");
    expect(screen.getByRole("textbox", { name: "Need" })).toHaveValue("trucks");
  });

  it("is linked from the queue", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/me") return new Response(JSON.stringify(STAFF), { status: 200 });
        if (url === "/api/requests") return new Response(JSON.stringify({ requests: [] }), { status: 200 });
        return new Response("{}", { status: 404 });
      }),
    );
    renderAt("/");

    expect(await screen.findByRole("link", { name: "Log a request" })).toHaveAttribute("href", "/quick-entry");
  });
});
