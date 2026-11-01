import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient, AuthSession } from "./auth";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com", role: "coordinator" };

/** In-memory stand-in for Supabase Auth: one valid email/password pair. */
function fakeAuth(initial: AuthSession | null = null): AuthClient & { signedOut: boolean } {
  let session = initial;
  const listeners = new Set<(s: AuthSession | null) => void>();
  const set = (s: AuthSession | null) => {
    session = s;
    listeners.forEach((l) => l(s));
  };
  return {
    signedOut: false,
    getSession: async () => session,
    onChange: (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    signIn: async (email, password) => {
      if (email === "pat@example.com" && password === "right") {
        set({ accessToken: "tok-pat" });
        return { error: null };
      }
      return { error: "Invalid login credentials" };
    },
    async signOut() {
      this.signedOut = true;
      set(null);
    },
  };
}

function apiMe(status: number, body: unknown = {}) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderAt(path: string, auth: AuthClient) {
  window.history.pushState({}, "", path);
  return render(<App auth={auth} />);
}

describe("dashboard login", () => {
  beforeEach(() => apiMe(200, STAFF));
  afterEach(() => vi.unstubAllGlobals());

  it("sends a logged-out visitor to the login page", async () => {
    renderAt("/", fakeAuth());
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/login");
  });

  it("logs a coordinator in and lands on the empty queue", async () => {
    const fetchMock = apiMe(200, STAFF);
    renderAt("/login", fakeAuth());

    await userEvent.type(await screen.findByLabelText("Email"), "pat@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "right");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("heading", { name: "Queue" })).toBeInTheDocument();
    expect(screen.getByText("No requests.")).toBeInTheDocument();
    expect(screen.getByText("Pat Lee")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
    expect(fetchMock).toHaveBeenCalledWith("/api/me", {
      headers: { Authorization: "Bearer tok-pat" },
    });
  });

  it("shows the error and stays on login when the password is wrong", async () => {
    renderAt("/login", fakeAuth());

    await userEvent.type(await screen.findByLabelText("Email"), "pat@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid login credentials");
    expect(window.location.pathname).toBe("/login");
  });

  it("refuses a signed-in user who is not staff", async () => {
    apiMe(403, { detail: "Not a staff account" });
    renderAt("/", fakeAuth({ accessToken: "tok-x" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("not on the staff list");
    expect(screen.queryByRole("heading", { name: "Queue" })).not.toBeInTheDocument();
  });

  it("signs out and returns to login when the backend rejects the token", async () => {
    apiMe(401, { detail: "Not signed in" });
    const auth = fakeAuth({ accessToken: "stale" });
    renderAt("/", auth);

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(auth.signedOut).toBe(true);
  });

  it("logs out back to the login page", async () => {
    const auth = fakeAuth({ accessToken: "tok-pat" });
    renderAt("/", auth);

    await userEvent.click(await screen.findByRole("button", { name: "Log out" }));

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/login");
    expect(auth.signedOut).toBe(true);
  });
});
