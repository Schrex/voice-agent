// Linked calls on the request detail page: transcript and recording (ticket #29).
// Vitest runs in UTC (vite.config.ts), so call times prove America/New_York display.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { AuthClient } from "./auth";
import type { CallRecord, RequestDetail } from "./api";

const STAFF = { id: "u-1", name: "Pat Lee", email: "pat@example.com", role: "coordinator" };

const signedIn: AuthClient = {
  getSession: async () => ({ accessToken: "tok-pat" }),
  onChange: () => () => {},
  signIn: async () => ({ error: null }),
  signOut: async () => {},
};

const DETAIL: RequestDetail = {
  ref: "R-1000",
  foreman: "Dale Kramer",
  job: "Route 104 Widening",
  job_spoken: "the 104 job",
  category: "Trucking",
  need: "dump trucks",
  quantity: null,
  unit: null,
  needed_by: null,
  urgency: null,
  status: "Recorded",
  source: "ai_call",
  recorded_at: "2026-11-02T01:30:00Z",
  events: [],
  calls: [{ id: 7, started_at: "2026-11-02T01:29:00Z", relation: "created" }],
};

const CALL: CallRecord = {
  id: 7,
  started_at: "2026-11-02T01:29:00Z",
  ended_at: "2026-11-02T01:30:26Z",
  duration_s: 86,
  transcript: [
    { role: "agent", message: "This call is recorded. What do you need?", at_s: 0 },
    { role: "user", message: "Two dump trucks at Route 104.", at_s: 4 },
  ],
};

type Audio = { status: number; body?: string };

function serve(detail: RequestDetail, call: CallRecord, audio: Audio = { status: 200 }) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/me") return new Response(JSON.stringify(STAFF));
    if (url === `/api/requests/${detail.ref}`) return new Response(JSON.stringify(detail));
    if (url === `/api/calls/${call.id}`) return new Response(JSON.stringify(call));
    if (url === `/api/calls/${call.id}/audio`)
      return new Response(audio.body ?? "mp3-bytes", { status: audio.status });
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderDetail() {
  window.history.pushState({}, "", "/requests/R-1000");
  render(<App auth={signedIn} />);
}

describe("linked calls on the request detail", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:recording-7");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows each linked call with its time (New York), duration and transcript", async () => {
    const fetchMock = serve(DETAIL, CALL);
    renderDetail();

    const call = await screen.findByRole("region", { name: "Call Sun, Nov 1, 8:29 PM" });
    expect(await within(call).findByText("Duration 1:26")).toBeInTheDocument();
    const transcript = await within(call).findByRole("list", { name: "Transcript" });
    expect(within(transcript).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Agent: This call is recorded. What do you need?",
      "Foreman: Two dump trucks at Route 104.",
    ]);
    expect(fetchMock).toHaveBeenCalledWith("/api/calls/7", {
      headers: { Authorization: "Bearer tok-pat" },
    });
  });

  it("plays the recording fetched through the backend with the staff token", async () => {
    const fetchMock = serve(DETAIL, CALL);
    renderDetail();

    const call = await screen.findByRole("region", { name: "Call Sun, Nov 1, 8:29 PM" });
    expect(call.querySelector("audio")).toBeNull(); // nothing fetched until asked
    await userEvent.click(within(call).getByRole("button", { name: "Play recording" }));

    const audio = await within(call).findByLabelText("Recording");
    expect(audio.tagName).toBe("AUDIO");
    expect(audio).toHaveAttribute("src", "blob:recording-7");
    expect(fetchMock).toHaveBeenCalledWith("/api/calls/7/audio", {
      headers: { Authorization: "Bearer tok-pat" },
    });
  });

  it("says so when there is no recording", async () => {
    serve(DETAIL, CALL, { status: 404 });
    renderDetail();

    const call = await screen.findByRole("region", { name: "Call Sun, Nov 1, 8:29 PM" });
    await userEvent.click(within(call).getByRole("button", { name: "Play recording" }));

    expect(await within(call).findByText("No recording for this call.")).toBeInTheDocument();
    expect(call.querySelector("audio")).toBeNull();
  });

  it("says so when the recording cannot be loaded", async () => {
    serve(DETAIL, CALL, { status: 502 });
    renderDetail();

    const call = await screen.findByRole("region", { name: "Call Sun, Nov 1, 8:29 PM" });
    await userEvent.click(within(call).getByRole("button", { name: "Play recording" }));

    expect(await within(call).findByRole("alert")).toHaveTextContent(
      "Could not load the recording.",
    );
  });

  it("says when the transcript has not arrived yet", async () => {
    serve(DETAIL, { ...CALL, ended_at: null, duration_s: null, transcript: [] });
    renderDetail();

    const call = await screen.findByRole("region", { name: "Call Sun, Nov 1, 8:29 PM" });
    expect(await within(call).findByText("No transcript yet.")).toBeInTheDocument();
    expect(within(call).queryByText(/^Duration/)).not.toBeInTheDocument();
  });

  it("says so when the request has no linked call", async () => {
    serve({ ...DETAIL, calls: [] }, CALL);
    renderDetail();

    expect(await screen.findByText("No linked calls.")).toBeInTheDocument();
  });
});
