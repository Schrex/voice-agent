import { expect, test } from "@playwright/test";

import { playCall } from "./elevenlabs";
import { accessToken, stubSupabaseAuth, type StubUser } from "./supabase-stub";

// Runs after login.spec.ts (files run in name order): that spec expects an empty queue.

// In tests/e2e/seed.json as a coordinator; Dale Kramer is a rostered Foreman there.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE = "+15855550101";

test.beforeEach(async ({ page }) => {
  await stubSupabaseAuth(page, [COORDINATOR]);
});

test("a coordinator records a Draft from a hung-up call", async ({ page, request }) => {
  const conversationId = `conv_e2e_hang_up_${Date.now()}`;
  await playCall(request, {
    caller: DALE,
    conversationId,
    fixture: "post_call_hang_up_before_confirm.json",
  });
  const auth = { Authorization: `Bearer ${accessToken(COORDINATOR)}` };
  const drafts = (await (await request.get("/api/drafts", { headers: auth })).json()).drafts;
  const ref: string = drafts[0].ref;

  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("link", { name: "Drafts" }).click();

  await expect(page.getByRole("heading", { name: "Drafts" })).toBeVisible();
  const row = page.getByRole("row", { name: new RegExp(`${ref}\\b`) });
  await expect(row).toContainText("Dale Kramer");
  await expect(row).toContainText("Route 104 Widening");
  await expect(row).toContainText("tri-axle dump trucks");
  await expect(row).toContainText("2 trucks");
  await expect(row).toContainText("tomorrow at 7 AM");

  await row.getByRole("button", { name: "Record" }).click();

  await expect(row).toHaveCount(0);
  const after = (await (await request.get("/api/drafts", { headers: auth })).json()).drafts;
  expect(after.map((d: { ref: string }) => d.ref)).not.toContain(ref);
  // Recording it again is refused: it is no longer a Draft.
  const again = await request.post(`/api/requests/${ref}/record`, { headers: auth });
  expect(again.status()).toBe(422);

  // It is now in the queue, and its history shows who recorded it.
  await page.getByRole("link", { name: "Queue" }).click();
  await page.getByRole("link", { name: ref, exact: true }).click();
  const fields = page.getByRole("group", { name: "Fields" });
  await expect(fields).toContainText("Recorded");
  const events = page
    .getByRole("table", { name: "History" })
    .getByRole("row")
    .filter({ has: page.getByRole("cell") });
  await expect(events).toHaveCount(2);
  await expect(events.nth(0).getByRole("cell").nth(1)).toHaveText("Agent");
  await expect(events.nth(0).getByRole("cell").nth(2)).toHaveText("Draft");
  await expect(events.nth(1).getByRole("cell").nth(1)).toHaveText("Casey Coordinator");
  await expect(events.nth(1).getByRole("cell").nth(2)).toHaveText("Recorded");
  await expect(events.nth(1).getByRole("cell").nth(3)).toContainText("status: Draft → Recorded");
});
