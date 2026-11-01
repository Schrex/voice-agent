import { execFileSync } from "node:child_process";

import type { APIRequestContext } from "@playwright/test";

/** The backend under test checks the agent's calls against these (see frontend/playwright.config.ts). */
export const E2E_HOOK_SECRET = "e2e-only-hook-secret";
export const E2E_TOOL_SECRET = "e2e-only-tool-secret";

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
  return body[0].ref;
}
