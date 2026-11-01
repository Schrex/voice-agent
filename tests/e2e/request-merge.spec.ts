import { expect, test } from "@playwright/test";

import { jobId, recordRequestByCall } from "./agent-stub";
import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// Ticket #33: merge duplicates from the detail page (spec J2, J9). Seed as in request-resolve.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE_PHONE = "+15855550101";

test("a coordinator merges a duplicate into another request from the detail page", async ({
  page,
  request: api,
}) => {
  const item = {
    job_id: jobId("Route 104 Widening"),
    job_spoken: "the 104 job",
    category: "Trucking",
    needed_by_spoken: "tomorrow at seven",
  };
  const kept = await recordRequestByCall(api, DALE_PHONE, {
    ...item,
    need: `e2e tri-axle ${Date.now()}`,
  });
  const duplicate = await recordRequestByCall(api, DALE_PHONE, {
    ...item,
    need: `e2e tri-axle again ${Date.now()}`,
  });
  await stubSupabaseAuth(page, [COORDINATOR]);

  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("link", { name: duplicate, exact: true }).click();

  await page.getByRole("button", { name: "Merge into another request" }).click();
  const form = page.getByRole("form", { name: "Merge" });
  const merge = form.getByRole("button", { name: "Merge", exact: true });
  await form.getByLabel("Merge into").fill(duplicate);
  await form.getByRole("combobox", { name: "Outcome" }).selectOption("Withdrawn");
  await form.getByLabel("Explanation").fill(`Duplicate of ${kept}`);
  await merge.click();
  await expect(page.getByRole("alert")).toHaveText("Could not merge the request."); // into itself

  await form.getByLabel("Merge into").fill(kept);
  await merge.click();

  const fields = page.getByRole("group", { name: "Fields" });
  await expect(fields.getByText("Resolved", { exact: true }).first()).toBeVisible();
  await expect(fields.getByText("Withdrawn", { exact: true })).toBeVisible();
  const history = page.getByRole("table", { name: "History" });
  const events = history.getByRole("row").filter({ has: page.getByRole("cell") });
  await expect(events).toHaveCount(2);
  await expect(events.nth(1).getByRole("cell").nth(1)).toHaveText("Casey Coordinator");
  await expect(events.nth(1).getByRole("cell").nth(2)).toHaveText("Merged");

  await fields.getByRole("link", { name: kept, exact: true }).click();
  await expect(page.getByRole("heading", { name: kept })).toBeVisible();
  await expect(fields.getByText("Recorded", { exact: true }).first()).toBeVisible();
  const keptEvents = history.getByRole("row").filter({ has: page.getByRole("cell") });
  await expect(keptEvents).toHaveCount(2);
  await expect(keptEvents.nth(1).getByRole("cell").nth(2)).toHaveText("Merged in");
  await expect(keptEvents.nth(1).getByRole("cell").nth(3)).toContainText(duplicate);

  await page.getByRole("link", { name: "Queue" }).click();
  await expect(page.getByRole("link", { name: kept, exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: duplicate, exact: true })).toHaveCount(0);
});
