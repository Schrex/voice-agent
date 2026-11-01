import { expect, test, type APIRequestContext } from "@playwright/test";

import { E2E_HOOK_SECRET, E2E_TOOL_SECRET, jobId } from "./agent-stub";
import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// Ticket #25, AC5.3: when the agent is about to transfer a Foreman, the open dashboard shows an
// incoming-transfer pop-up within one poll (10 s), and a Coordinator can dismiss it.
// In tests/e2e/seed.json: a coordinator and Dale Kramer (rostered) on Route 104 Widening.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE_PHONE = "+15855550101";
const ONE_POLL_MS = 10_000;

/** Plays the ElevenLabs agent: starts Dale's call, then calls `transfer_to_office`. */
async function transferToOffice(api: APIRequestContext, body: Record<string, unknown>) {
  const conversationId = `conv_e2e_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const started = await api.post("/hooks/call-start", {
    headers: { "X-Hook-Secret": E2E_HOOK_SECRET },
    data: {
      caller_id: DALE_PHONE,
      agent_id: "agent_e2e",
      called_number: "+15855550199",
      call_sid: `CA${Date.now()}`,
      conversation_id: conversationId,
    },
  });
  expect(started.ok()).toBe(true);
  const told = await api.post("/tools/transfer_to_office", {
    headers: { "X-Tool-Secret": E2E_TOOL_SECRET, "X-Conversation-Id": conversationId },
    data: body,
  });
  expect(await told.json()).toEqual({ ok: true });
}

test("an incoming transfer pops up on the open dashboard within one poll and can be dismissed", async ({
  page,
  request: api,
}) => {
  await stubSupabaseAuth(page, [COORDINATOR]);
  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  const firstPoll = page.waitForResponse((r) => r.url().endsWith("/api/popups"));
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Queue", level: 1 })).toBeVisible();
  // The dashboard has made its first poll before the transfer starts.
  await firstPoll;

  const need = `e2e loader ${Date.now()}`;
  await transferToOffice(api, {
    reason: need,
    job_id: jobId("Route 104 Widening"),
    job_spoken: "the 104 job",
  });

  const popup = page.getByRole("alertdialog", { name: "Incoming transfer" }).filter({
    hasText: need,
  });
  await expect(popup).toBeVisible({ timeout: ONE_POLL_MS + 2_000 });
  await expect(popup).toContainText(
    `Incoming transfer: Dale Kramer, Route 104 Widening, about: ${need}`,
  );

  await popup.getByRole("button", { name: "Dismiss" }).click();
  await expect(popup).toHaveCount(0);

  // Gone for good: a reload (and the next poll) does not bring it back.
  const pollAfterReload = page.waitForResponse((r) => r.url().endsWith("/api/popups"));
  await page.reload();
  await expect(page.getByRole("heading", { name: "Queue", level: 1 })).toBeVisible();
  await pollAfterReload;
  await expect(popup).toHaveCount(0);
});
