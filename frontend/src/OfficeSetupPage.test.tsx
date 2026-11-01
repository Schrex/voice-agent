import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const CATEGORIES = ["Trucking", "Equipment", "Equipment Repair", "Material", "Labor", "Information", "Callback", "Other"];

/** In-memory `/api/admin/{owners,category-defaults,staff,duty,settings}`; records every write. */
function fakeApi(role: "admin" | "coordinator") {
  const staff = [
    { id: "s-1", name: "Casey Coordinator", email: "casey@x.com", role: "coordinator", phone_e164: "+15855550123" },
    { id: "s-2", name: "Jo Backup", email: "jo@x.com", role: "coordinator", phone_e164: null },
  ];
  const owners = [{ id: 1, name: "Dispatch", phone_e164: null, email: null }];
  const defaults: Record<string, number | null> = Object.fromEntries(CATEGORIES.map((c) => [c, null]));
  defaults.Trucking = 1;
  let duty: { date: string; on_duty: { id: string; name: string }; backup: { id: string; name: string } | null }[] = [];
  const settings = { office_line_e164: null as string | null, ack_window_today_min: 15, ack_window_planned_min: 120 };
  const writes: { method: string; url: string; body: unknown }[] = [];
  let nextId = 100;
  const ref = (id: string | null) => {
    const s = staff.find((x) => x.id === id);
    return s ? { id: s.id, name: s.name } : null;
  };

  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    if (method !== "GET") writes.push({ method, url, body });
    if (url === "/api/me") return json({ id: "u", name: "Ali Admin", email: "a@x", role });
    if (role !== "admin") return json({ detail: "Admins only" }, 403);

    if (url === "/api/admin/settings" && method === "GET") return json(settings);
    if (url === "/api/admin/settings" && method === "PATCH") {
      if (body.ack_window_today_min !== undefined && body.ack_window_today_min < 1) {
        return json({ detail: [{ msg: "Input should be greater than or equal to 1" }] }, 422);
      }
      Object.assign(settings, body);
      return json(settings);
    }
    if (url === "/api/admin/staff" && method === "GET") return json(staff);
    if (url === "/api/admin/staff" && method === "POST") {
      const s = { role: "coordinator", phone_e164: null, ...body };
      staff.push(s);
      return json(s, 201);
    }
    let m = url.match(/^\/api\/admin\/staff\/(.+)$/);
    if (m && method === "PATCH") {
      const s = staff.find((x) => x.id === m![1])!;
      Object.assign(s, body);
      return json(s);
    }
    if (url === "/api/admin/owners" && method === "GET") return json(owners);
    if (url === "/api/admin/owners" && method === "POST") {
      const o = { id: nextId++, phone_e164: null, email: null, ...body };
      owners.push(o);
      return json(o, 201);
    }
    if (url === "/api/admin/category-defaults" && method === "GET") {
      return json(CATEGORIES.map((c) => ({ category: c, owner_id: defaults[c] })));
    }
    m = url.match(/^\/api\/admin\/category-defaults\/(.+)$/);
    if (m && method === "PUT") {
      const category = decodeURIComponent(m[1]);
      defaults[category] = body.owner_id;
      return json({ category, owner_id: body.owner_id });
    }
    if (url === "/api/admin/duty" && method === "GET") return json(duty);
    m = url.match(/^\/api\/admin\/duty\/(\d{4}-\d{2}-\d{2})$/);
    if (m && method === "PUT") {
      const day = { date: m[1], on_duty: ref(body.on_duty_staff_id)!, backup: ref(body.backup_staff_id) };
      duty = [...duty.filter((d) => d.date !== m![1]), day].sort((a, b) => a.date.localeCompare(b.date));
      return json(day);
    }
    if (m && method === "DELETE") {
      duty = duty.filter((d) => d.date !== m![1]);
      return new Response(null, { status: 204 });
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

describe("admin: owners, staff, duty roster, settings", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("refuses a coordinator", async () => {
    fakeApi("coordinator");
    renderAt("/admin/office");
    expect(await screen.findByRole("alert")).toHaveTextContent("Admins only");
    expect(screen.queryByRole("heading", { name: "Duty roster" })).not.toBeInTheDocument();
  });

  it("is reached from the admin page", async () => {
    fakeApi("admin");
    renderAt("/admin");
    await userEvent.click(await screen.findByRole("link", { name: "Owners, staff, duty roster, settings" }));
    expect(window.location.pathname).toBe("/admin/office");
    expect(await screen.findByRole("heading", { name: "Duty roster" })).toBeInTheDocument();
  });

  it("sets the on-duty and backup Coordinator for a date, then removes the day", async () => {
    const { writes } = fakeApi("admin");
    renderAt("/admin/office");
    const form = await screen.findByRole("form", { name: "Set duty day" });
    await within(within(form).getByLabelText("Backup")).findByRole("option", { name: "Jo Backup" });

    await userEvent.type(within(form).getByLabelText("Date"), "2026-11-02");
    await userEvent.selectOptions(within(form).getByLabelText("On duty"), "Casey Coordinator");
    await userEvent.selectOptions(within(form).getByLabelText("Backup"), "Jo Backup");
    await userEvent.click(within(form).getByRole("button", { name: "Save duty day" }));

    const row = await screen.findByRole("row", { name: /Mon, Nov 2/ });
    expect(row).toHaveTextContent("Casey Coordinator");
    expect(row).toHaveTextContent("Jo Backup");

    await userEvent.click(within(row).getByRole("button", { name: "Remove" }));
    expect(await screen.findByText("No duty days set.")).toBeInTheDocument();
    expect(writes).toEqual([
      { method: "PUT", url: "/api/admin/duty/2026-11-02", body: { on_duty_staff_id: "s-1", backup_staff_id: "s-2" } },
      { method: "DELETE", url: "/api/admin/duty/2026-11-02", body: undefined },
    ]);
  });

  it("changes the acknowledgment windows and the office line", async () => {
    const { writes } = fakeApi("admin");
    renderAt("/admin/office");
    const form = await screen.findByRole("form", { name: "Settings" });
    const today = within(form).getByLabelText("Today ack window (minutes)");
    await screen.findByDisplayValue("120");

    await userEvent.clear(today);
    await userEvent.type(today, "30");
    await userEvent.type(within(form).getByLabelText("Office line"), "+15855550100");
    await userEvent.click(within(form).getByRole("button", { name: "Save settings" }));

    expect(await screen.findByText("Settings saved.")).toBeInTheDocument();
    expect(writes).toEqual([
      {
        method: "PATCH",
        url: "/api/admin/settings",
        body: { office_line_e164: "+15855550100", ack_window_today_min: 30, ack_window_planned_min: 120 },
      },
    ]);
  });

  it("shows why settings were not saved", async () => {
    fakeApi("admin");
    renderAt("/admin/office");
    const form = await screen.findByRole("form", { name: "Settings" });
    await screen.findByDisplayValue("120");
    const today = within(form).getByLabelText("Today ack window (minutes)");

    await userEvent.clear(today);
    await userEvent.type(today, "0");
    await userEvent.click(within(form).getByRole("button", { name: "Save settings" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("greater than or equal to 1");
  });

  it("adds staff and makes one an admin", async () => {
    const { writes } = fakeApi("admin");
    renderAt("/admin/office");
    const form = await screen.findByRole("form", { name: "Add staff" });

    await userEvent.type(within(form).getByLabelText("Supabase user id"), "s-3");
    await userEvent.type(within(form).getByLabelText("Name"), "Lee Office");
    await userEvent.type(within(form).getByLabelText("Email"), "lee@x.com");
    await userEvent.type(within(form).getByLabelText("Phone"), "+15855550130");
    await userEvent.click(within(form).getByRole("button", { name: "Add staff" }));
    const row = await screen.findByRole("row", { name: /Lee Office/ });
    expect(row).toHaveTextContent("coordinator");

    await userEvent.click(within(row).getByRole("button", { name: "Make admin" }));
    expect(await within(screen.getByRole("row", { name: /Lee Office/ })).findByRole("button", { name: "Make coordinator" })).toBeInTheDocument();
    expect(writes).toEqual([
      {
        method: "POST",
        url: "/api/admin/staff",
        body: { id: "s-3", name: "Lee Office", email: "lee@x.com", role: "coordinator", phone_e164: "+15855550130" },
      },
      { method: "PATCH", url: "/api/admin/staff/s-3", body: { role: "admin" } },
    ]);
  });

  it("adds an Owner and makes it a category's default", async () => {
    const { writes } = fakeApi("admin");
    renderAt("/admin/office");
    const form = await screen.findByRole("form", { name: "Add owner" });

    await userEvent.type(within(form).getByLabelText("Owner name"), "Equipment Manager");
    await userEvent.click(within(form).getByRole("button", { name: "Add owner" }));
    const equipment = screen.getByLabelText("Default owner for Equipment");
    await within(equipment).findByRole("option", { name: "Equipment Manager" });
    await userEvent.selectOptions(equipment, "Equipment Manager");

    expect(writes).toEqual([
      { method: "POST", url: "/api/admin/owners", body: { name: "Equipment Manager", phone_e164: null, email: null } },
      { method: "PUT", url: "/api/admin/category-defaults/Equipment", body: { owner_id: 100 } },
    ]);
    expect(screen.getByLabelText("Default owner for Trucking")).toHaveDisplayValue("Dispatch");
  });
});
