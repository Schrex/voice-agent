// Vitest runs in UTC (vite.config.ts); the alert time must still show in America/New_York.
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { FailedAlert } from "./api";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com", role: "coordinator" };

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok-pat" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

function serve(alerts: FailedAlert[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/me") return new Response(JSON.stringify(STAFF));
      if (url === "/api/requests") return new Response(JSON.stringify({ requests: [] }));
      if (url === "/api/alerts/failed") return new Response(JSON.stringify({ alerts }));
      return new Response("{}", { status: 404 });
    }),
  );
}

describe("failed alerts on the queue", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("names each SMS that was not sent, its request, when and why", async () => {
    serve([
      {
        ref: "R-1000",
        kind: "today_new",
        channel: "sms",
        at: "2026-11-01T20:04:00Z",
        detail: "No on-duty Coordinator for Sun, Nov 1",
      },
    ]);
    window.history.pushState({}, "", "/");
    render(<App auth={signedIn} />);

    const box = await screen.findByRole("alert", { name: "Alerts not sent" });
    const item = within(box).getByRole("listitem");
    expect(item).toHaveTextContent(
      "Today SMS for R-1000 not sent (Sun, Nov 1, 3:04 PM): No on-duty Coordinator for Sun, Nov 1",
    );
    expect(within(item).getByRole("link", { name: "R-1000" })).toHaveAttribute(
      "href",
      "/requests/R-1000",
    );
  });

  it("shows nothing when every alert was sent", async () => {
    serve([]);
    window.history.pushState({}, "", "/");
    render(<App auth={signedIn} />);

    await screen.findByText("No requests.");
    expect(screen.queryByRole("alert", { name: "Alerts not sent" })).toBeNull();
  });
});
