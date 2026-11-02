import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";

type Foreman = {
  id: number;
  first_name: string;
  last_name: string;
  active: boolean;
  phones: { id: number; e164: string }[];
};
type Job = { id: number; name: string; active: boolean; aliases: { id: number; alias: string }[] };

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

/** In-memory `/api` for the admin screens; records every write it receives. */
function fakeApi() {
  const foremen: Foreman[] = [
    { id: 1, first_name: "Dale", last_name: "Kramer", active: true, phones: [{ id: 11, e164: "+15855550101" }] },
  ];
  const jobs: Job[] = [
    { id: 2, name: "Route 104 Widening", active: true, aliases: [{ id: 21, alias: "Route 104" }] },
  ];
  const writes: { method: string; url: string; body: unknown }[] = [];
  let nextId = 100;

  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    if (method !== "GET") writes.push({ method, url, body });
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok");

    if (url === "/api/me") return json({ id: "u", name: "Ali Admin", email: "a@x" });
    if (url === "/api/admin/foremen" && method === "GET") return json(foremen);
    if (url === "/api/admin/jobs" && method === "GET") return json(jobs);

    let m = url.match(/^\/api\/admin\/foremen\/(\d+)$/);
    if (m && method === "PATCH") {
      const f = foremen.find((x) => x.id === Number(m![1]))!;
      Object.assign(f, body);
      return json(f);
    }
    m = url.match(/^\/api\/admin\/foremen\/(\d+)\/phones$/);
    if (m && method === "POST") {
      if (foremen.some((f) => f.phones.some((p) => p.e164 === body.e164))) {
        return json({ detail: `${body.e164} is already on the roster.` }, 409);
      }
      const f = foremen.find((x) => x.id === Number(m![1]))!;
      f.phones.push({ id: nextId++, e164: body.e164 });
      return json(f, 201);
    }
    if (url === "/api/admin/foremen" && method === "POST") {
      const f = { id: nextId++, ...body, active: true, phones: body.phones.map((e164: string) => ({ id: nextId++, e164 })) };
      foremen.push(f);
      return json(f, 201);
    }
    m = url.match(/^\/api\/admin\/jobs\/(\d+)\/aliases$/);
    if (m && method === "POST") {
      const j = jobs.find((x) => x.id === Number(m![1]))!;
      j.aliases.push({ id: nextId++, alias: body.alias });
      return json(j, 201);
    }
    m = url.match(/^\/api\/admin\/jobs\/(\d+)\/aliases\/(\d+)$/);
    if (m && method === "DELETE") {
      const j = jobs.find((x) => x.id === Number(m![1]))!;
      j.aliases = j.aliases.filter((a) => a.id !== Number(m![2]));
      return json(j);
    }
    m = url.match(/^\/api\/admin\/jobs\/(\d+)$/);
    if (m && method === "PATCH") {
      const j = jobs.find((x) => x.id === Number(m![1]))!;
      Object.assign(j, body);
      return json(j);
    }
    if (url === "/api/admin/jobs" && method === "POST") {
      const j = { id: nextId++, name: body.name, active: true, aliases: [] };
      jobs.push(j);
      return json(j, 201);
    }
    return json({ detail: "Not found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { writes };
}

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(<App auth={signedIn} />);
}

const row = (name: string) => screen.getByRole("row", { name: new RegExp(name) });

describe("admin: roster and jobs", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("takes any staff member from the queue to the roster and job list (one Staff role)", async () => {
    fakeApi();
    renderAt("/");

    await userEvent.click(await screen.findByRole("link", { name: "Admin" }));

    expect(window.location.pathname).toBe("/admin");
    expect(await screen.findByRole("heading", { name: "Foremen" })).toBeInTheDocument();
    expect(await screen.findByText("+15855550101")).toBeInTheDocument();
    expect(row("Dale Kramer")).toHaveTextContent("Active");
    expect(row("Route 104 Widening")).toHaveTextContent("Route 104");
  });

  it("adds a foreman with a phone number", async () => {
    const { writes } = fakeApi();
    renderAt("/admin");
    const form = await screen.findByRole("form", { name: "Add foreman" });

    await userEvent.type(within(form).getByLabelText("First name"), "Lena");
    await userEvent.type(within(form).getByLabelText("Last name"), "Ortiz");
    await userEvent.type(within(form).getByLabelText("Phone"), "+15855550120");
    await userEvent.click(within(form).getByRole("button", { name: "Add foreman" }));

    expect(await screen.findByRole("row", { name: /Lena Ortiz/ })).toHaveTextContent("+15855550120");
    expect(writes).toEqual([
      {
        method: "POST",
        url: "/api/admin/foremen",
        body: { first_name: "Lena", last_name: "Ortiz", phones: ["+15855550120"] },
      },
    ]);
  });

  it("deactivates a foreman", async () => {
    const { writes } = fakeApi();
    renderAt("/admin");
    await screen.findByText("+15855550101");

    await userEvent.click(within(row("Dale Kramer")).getByRole("button", { name: "Deactivate" }));

    expect(await within(row("Dale Kramer")).findByText("Inactive")).toBeInTheDocument();
    expect(within(row("Dale Kramer")).getByRole("button", { name: "Reactivate" })).toBeInTheDocument();
    expect(writes).toEqual([{ method: "PATCH", url: "/api/admin/foremen/1", body: { active: false } }]);
  });

  it("shows the reason when a number is already on the roster", async () => {
    fakeApi();
    renderAt("/admin");
    await screen.findByText("+15855550101");

    await userEvent.type(within(row("Dale Kramer")).getByLabelText("New phone"), "+15855550101");
    await userEvent.click(within(row("Dale Kramer")).getByRole("button", { name: "Add phone" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("+15855550101 is already on the roster.");
  });

  it("adds and removes a job alias", async () => {
    const { writes } = fakeApi();
    renderAt("/admin");
    await screen.findByText("+15855550101");

    await userEvent.type(within(row("Route 104 Widening")).getByLabelText("New alias"), "104 job");
    await userEvent.click(within(row("Route 104 Widening")).getByRole("button", { name: "Add alias" }));
    expect(await within(row("Route 104 Widening")).findByText("104 job")).toBeInTheDocument();

    await userEvent.click(
      within(row("Route 104 Widening")).getByRole("button", { name: "Remove alias Route 104" }),
    );
    expect(await screen.findByRole("row", { name: /Route 104 Widening/ })).not.toHaveTextContent(
      /Route 104(?! Widening)/,
    );
    expect(writes).toEqual([
      { method: "POST", url: "/api/admin/jobs/2/aliases", body: { alias: "104 job" } },
      { method: "DELETE", url: "/api/admin/jobs/2/aliases/21", body: undefined },
    ]);
  });

  it("adds a job and deactivates it", async () => {
    const { writes } = fakeApi();
    renderAt("/admin");
    const form = await screen.findByRole("form", { name: "Add job" });

    await userEvent.type(within(form).getByLabelText("Job name"), "Brighton Culvert");
    await userEvent.click(within(form).getByRole("button", { name: "Add job" }));
    await screen.findByRole("row", { name: /Brighton Culvert/ });
    await userEvent.click(within(row("Brighton Culvert")).getByRole("button", { name: "Deactivate" }));

    expect(await within(row("Brighton Culvert")).findByText("Inactive")).toBeInTheDocument();
    expect(writes).toEqual([
      { method: "POST", url: "/api/admin/jobs", body: { name: "Brighton Culvert", aliases: [] } },
      { method: "PATCH", url: "/api/admin/jobs/100", body: { active: false } },
    ]);
  });
});
