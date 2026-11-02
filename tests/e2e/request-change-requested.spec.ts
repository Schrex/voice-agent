import { expect, test } from "@playwright/test";

import { E2E_TOOL_SECRET, jobId, recordRequestOnCall } from "./agent-stub";
import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json: a coordinator, Dale Kramer (rostered) on Route 104 Widening, and the
// Owner Dispatch (default for Trucking).
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE_PHONE = "+15855550101";

test("a change the Foreman asks for on an In Progress request shows Change requested in the queue", async ({
  page,
  request: api,
}) => {
  const need = `e2e tri-axles ${Date.now()}`;
  const { ref, conversationId } = await recordRequestOnCall(api, DALE_PHONE, {
    job_id: jobId("Route 104 Widening"),
    job_spoken: "the 104 job",
    category: "Trucking",
    need,
    needed_by_spoken: "tomorrow at seven",
  });
  await stubSupabaseAuth(page, [COORDINATOR]);
  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  const row = page.getByRole("row").filter({ has: page.getByRole("link", { name: ref, exact: true }) });
  await expect(row).not.toContainText("Change requested");

  // The coordinator works it to In Progress.
  await row.getByRole("link", { name: ref, exact: true }).click();
  const fields = page.getByRole("group", { name: "Fields" });
  await page.getByRole("button", { name: "Acknowledge" }).click(); // Dispatch, Trucking's default
  await page.getByRole("button", { name: "Move to In Progress" }).click();
  await expect(fields.getByText("In Progress", { exact: true })).toBeVisible();

  // Plays the agent's amend_request tool call later in the same call (spec J4, AC4.2).
  const amended = await api.post("/tools/amend_request", {
    headers: { "X-Tool-Secret": E2E_TOOL_SECRET, "X-Conversation-Id": conversationId },
    data: { ref, changes: { needed_by_spoken: "thursday at seven" } },
  });
  expect(await amended.json()).toEqual({ applied: false, status: "In Progress" });

  await page.getByRole("link", { name: "Queue" }).click();
  await expect(row.getByText("Change requested", { exact: true })).toHaveClass("flag");
  await expect(row).toContainText("In Progress");

  await row.getByRole("link", { name: ref, exact: true }).click();
  const note = page.getByRole("list", { name: "Notes" }).getByRole("listitem");
  await expect(note).toContainText('Change requested: needed-by "thursday at seven"');
  const history = page.getByRole("table", { name: "History" });
  await expect(history.getByRole("cell", { name: "Change requested", exact: true })).toBeVisible();
});
