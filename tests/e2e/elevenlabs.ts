import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { APIRequestContext } from "@playwright/test";

/** Webhook secrets the backend under test expects (see frontend/playwright.config.ts). */
export const E2E_HOOK_SECRET = "e2e-only-hook-secret";
export const E2E_WEBHOOK_SECRET = "e2e-only-post-call-webhook-secret";

// `npm run e2e` runs from frontend/.
const FIXTURES = join(process.cwd(), "..", "tests", "fixtures", "elevenlabs");

/**
 * Plays one call the way ElevenLabs reports it: call start for `caller`, then the signed
 * post-call webhook of fixture `fixture` (renamed to `conversationId`, so reruns stay new).
 */
export async function playCall(
  request: APIRequestContext,
  { caller, conversationId, fixture }: { caller: string; conversationId: string; fixture: string },
): Promise<void> {
  const start = await request.post("/hooks/call-start", {
    data: { caller_id: caller, conversation_id: conversationId },
    headers: { "X-Hook-Secret": E2E_HOOK_SECRET },
  });
  if (!start.ok()) throw new Error(`call-start failed: ${start.status()}`);

  const payload = JSON.parse(readFileSync(join(FIXTURES, fixture), "utf8"));
  payload.data.conversation_id = conversationId;
  const body = JSON.stringify(payload);
  const t = Math.floor(Date.now() / 1000);
  const v0 = createHmac("sha256", E2E_WEBHOOK_SECRET).update(`${t}.${body}`).digest("hex");
  const postCall = await request.post("/hooks/post-call", {
    data: body,
    headers: { "Content-Type": "application/json", "ElevenLabs-Signature": `t=${t},v0=${v0}` },
  });
  if (!postCall.ok()) throw new Error(`post-call failed: ${postCall.status()}`);
}
