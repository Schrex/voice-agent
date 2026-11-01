import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";

import type { APIRequestContext } from "@playwright/test";

/** The backend under test checks the agent's calls against these (see frontend/playwright.config.ts). */
export const E2E_HOOK_SECRET = "e2e-only-hook-secret";
export const E2E_TOOL_SECRET = "e2e-only-tool-secret";
export const E2E_WEBHOOK_SECRET = "e2e-only-post-call-webhook-secret";

/** A Job's id from the e2e database (the agent learns ids from find_jobs, which comes later). */
export function jobId(name: string): number {
  const url = process.env.E2E_DATABASE_URL!.replace("postgresql+psycopg://", "postgresql://");
  const out = execFileSync("psql", [url, "-tAc", "SELECT id FROM jobs WHERE name = $$" + name + "$$"]);
  return Number(out.toString().trim());
}

/**
 * Plays the ElevenLabs agent: starts a call from a rostered number, then submits one
 * confirmed item through the tool endpoint. Returns the new request's ref.
 */
export async function recordRequestByCall(
  api: APIRequestContext,
  callerE164: string,
  item: Record<string, unknown>,
): Promise<string> {
  return (await recordRequestOnCall(api, callerE164, item)).ref;
}

/** Same as `recordRequestByCall`, also returning the call's ElevenLabs conversation id. */
export async function recordRequestOnCall(
  api: APIRequestContext,
  callerE164: string,
  item: Record<string, unknown>,
): Promise<{ ref: string; conversationId: string }> {
  const conversationId = `conv_e2e_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const started = await api.post("/hooks/call-start", {
    headers: { "X-Hook-Secret": E2E_HOOK_SECRET },
    data: {
      caller_id: callerE164,
      agent_id: "agent_e2e",
      called_number: "+15855550199",
      call_sid: `CA${Date.now()}`,
      conversation_id: conversationId,
    },
  });
  if (!started.ok()) throw new Error(`call-start: ${started.status()}`);
  const submitted = await api.post("/tools/submit_requests", {
    headers: { "X-Tool-Secret": E2E_TOOL_SECRET, "X-Conversation-Id": conversationId },
    data: { items: [item] },
  });
  const body = (await submitted.json()) as [{ ref: string }] | { error: string };
  if (!Array.isArray(body)) throw new Error(`submit_requests: ${body.error}`);
  return { ref: body[0].ref, conversationId };
}

/**
 * Plays ElevenLabs' post-call webhook: delivers the call's transcript, signed the way
 * ElevenLabs signs it (`ElevenLabs-Signature: t=<secs>,v0=<HMAC-SHA256 hex of "t.body">`).
 */
export async function deliverPostCall(
  api: APIRequestContext,
  conversationId: string,
  transcript: { role: "agent" | "user"; message: string; time_in_call_secs: number }[],
  durationSecs: number,
): Promise<void> {
  const now = Math.floor(Date.now() / 1000);
  const body = JSON.stringify({
    type: "post_call_transcription",
    event_timestamp: now,
    data: {
      agent_id: "agent_e2e",
      conversation_id: conversationId,
      status: "done",
      transcript,
      metadata: {
        start_time_unix_secs: now - durationSecs,
        call_duration_secs: durationSecs,
        termination_reason: "end_call tool was called.",
      },
      analysis: { transcript_summary: "e2e call", data_collection_results: {} },
    },
  });
  const signature = createHmac("sha256", E2E_WEBHOOK_SECRET).update(`${now}.${body}`).digest("hex");
  const delivered = await api.post("/hooks/post-call", {
    headers: { "ElevenLabs-Signature": `t=${now},v0=${signature}`, "Content-Type": "application/json" },
    data: body,
  });
  if (!delivered.ok()) throw new Error(`post-call: ${delivered.status()}`);
}
