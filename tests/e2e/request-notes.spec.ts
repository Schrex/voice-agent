import { expect, test } from "@playwright/test";

import { E2E_TOOL_SECRET, jobId, recordRequestOnCall } from "./agent-stub";
import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json: a coordinator and Dale Kramer (rostered) on Route 104 Widening.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE_PHONE = "+15855550101";

test("a note the Foreman adds on a call shows on the request detail with the urgent marker", async ({
  page,
  request: api,
}) => {
  const need = `e2e water truck ${Date.now()}`;
  const { ref, conversationId } = await recordRequestOnCall(api, DALE_PHONE, {
    job_id: jobId("Route 104 Widening"),
    job_spoken: "the 104 job",
    category: "Trucking",
    need,
    needed_by_spoken: "tomorrow at seven",
  });
  // Plays the agent's add_note tool call later in the same call (spec J3 step 4).
  const added = await api.post("/tools/add_note", {
    headers: { "X-Tool-Secret": E2E_TOOL_SECRET, "X-Conversation-Id": conversationId },
    data: { ref, text: "need an answer today", urgent: true },
  });
  expect(await added.json()).toEqual({ ok: true });
  await stubSupabaseAuth(page, [COORDINATOR]);

  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("link", { name: ref, exact: true }).click();

  const notes = page.getByRole("list", { name: "Notes" });
  const note = notes.getByRole("listitem");
  await expect(note).toHaveCount(1);
  await expect(note).toContainText("need an answer today");
  await expect(note).toContainText("Agent");
  await expect(note.getByText("Urgent", { exact: true })).toBeVisible();
  const history = page.getByRole("table", { name: "History" });
  await expect(history.getByRole("cell", { name: "Note added" })).toBeVisible();
});
