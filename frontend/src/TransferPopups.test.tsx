// Incoming-transfer pop-ups (ticket #25, AC5.3): shown on every staff page, dismissible.
// Vitest runs in UTC (vite.config.ts); times must still show in America/New_York.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { Popup } from "./api";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com" };

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok-pat" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

const DALE: Popup = {
  id: 7,
  kind: "transfer",
  text: "Incoming transfer: Dale Kramer, Route 104 Widening, about: tri-axle dump trucks",
  at: "2026-11-01T20:04:00Z",
};

function serve(popups: Popup[]) {
  const calls: { url: string; method: string; auth: string | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const auth = new Headers(init?.headers).get("Authorization");
      calls.push({ url, method, auth });
      if (url === "/api/me") return new Response(JSON.stringify(STAFF));
      if (url === "/api/requests") return new Response(JSON.stringify({ requests: [] }));
      if (url === "/api/alerts/failed") return new Response(JSON.stringify({ alerts: [] }));
      if (url === "/api/drafts") return new Response(JSON.stringify({ drafts: [] }));
      if (url === "/api/popups") return new Response(JSON.stringify({ popups }));
      const dismiss = url.match(/^\/api\/popups\/(\d+)\/dismiss$/);
      if (dismiss && method === "POST") {
        popups = popups.filter((p) => p.id !== Number(dismiss[1]));
        return new Response(null, { status: 204 });
      }
      return new Response("{}", { status: 404 });
    }),
  );
  return calls;
}

describe("incoming-transfer pop-ups", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows who is being transferred, about what, and when", async () => {
    serve([DALE]);
    window.history.pushState({}, "", "/");
    render(<App auth={signedIn} />);

    const popup = await screen.findByRole("alertdialog", { name: "Incoming transfer" });
    expect(popup).toHaveTextContent(DALE.text);
    expect(popup).toHaveTextContent("Sun, Nov 1, 3:04 PM");
  });

  it("is shown on other dashboard pages too", async () => {
    serve([DALE]);
    window.history.pushState({}, "", "/drafts");
    render(<App auth={signedIn} />);

    expect(await screen.findByRole("alertdialog", { name: "Incoming transfer" })).toBeVisible();
  });

  it("is dismissed with the Dismiss button and stays gone", async () => {
    const calls = serve([DALE]);
    window.history.pushState({}, "", "/");
    render(<App auth={signedIn} />);
    const popup = await screen.findByRole("alertdialog", { name: "Incoming transfer" });

    await userEvent.click(within(popup).getByRole("button", { name: "Dismiss" }));

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog", { name: "Incoming transfer" })).toBeNull(),
    );
    expect(calls).toContainEqual({
      url: "/api/popups/7/dismiss",
      method: "POST",
      auth: "Bearer tok-pat",
    });
  });

  it("shows nothing when there is no pop-up", async () => {
    serve([]);
    window.history.pushState({}, "", "/");
    render(<App auth={signedIn} />);

    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});

