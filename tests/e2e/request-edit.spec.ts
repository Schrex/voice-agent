import { expect, test } from "@playwright/test";

import { recordRequestByCall } from "./agent-stub";
import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json: a coordinator, Dale Kramer (rostered) and the active Job Route 104
// Widening.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE_PHONE = "+15855550101";

test("a coordinator fixes the Job of an Unmatched request; the Unmatched flag disappears", async ({
  page,
  request: api,
}) => {
  const need = `e2e lowboy ${Date.now()}`;
  const ref = await recordRequestByCall(api, DALE_PHONE, {
    job_spoken: "the Smith pit", // matches no Job: recorded Unmatched
    category: "Equipment",
    need,
  });
  await stubSupabaseAuth(page, [COORDINATOR]);

  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  const row = page.getByRole("row").filter({ has: page.getByRole("link", { name: ref, exact: true }) });
  await expect(row.getByText("Unmatched", { exact: true })).toBeVisible();
  await row.getByRole("link", { name: ref, exact: true }).click();

  const fields = page.getByRole("group", { name: "Fields" });
  await expect(fields.getByText("Unmatched: “the Smith pit”")).toBeVisible();
  await page.getByRole("button", { name: "Edit fields" }).click();
  const form = page.getByRole("form", { name: "Edit fields" });
  await form.getByRole("combobox", { name: "Job" }).selectOption({ label: "Route 104 Widening" });
  await form.getByRole("button", { name: "Save" }).click();

  await expect(fields.getByText("Route 104 Widening", { exact: true })).toBeVisible();
  await expect(fields.getByText(/Unmatched/)).toHaveCount(0);
  const history = page.getByRole("table", { name: "History" });
  const events = history.getByRole("row").filter({ has: page.getByRole("cell") });
  await expect(events).toHaveCount(2);
  await expect(events.nth(1).getByRole("cell").nth(1)).toHaveText("Casey Coordinator");
  await expect(events.nth(1).getByRole("cell").nth(2)).toHaveText("Edited");
  await expect(events.nth(1).getByRole("cell").nth(3)).toHaveText(/^job_id: — → \d+$/);

  await page.getByRole("link", { name: "Queue" }).click();
  const fixed = page.getByRole("row").filter({ has: page.getByRole("link", { name: ref, exact: true }) });
  await expect(fixed.getByText("Route 104 Widening", { exact: true })).toBeVisible();
  await expect(fixed.getByText("Unmatched", { exact: true })).toHaveCount(0);
});
