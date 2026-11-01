import { expect, test } from "@playwright/test";

import { jobId, recordRequestByCall } from "./agent-stub";
import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json: a coordinator, Dale Kramer (rostered) on Route 104 Widening, and the
// Owners Dispatch (default for Trucking) and Equipment Manager.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE_PHONE = "+15855550101";

test("a coordinator acknowledges a recorded request with an Owner; the queue shows Acknowledged", async ({
  page,
  request: api,
}) => {
  const need = `e2e lowboy ${Date.now()}`;
  const ref = await recordRequestByCall(api, DALE_PHONE, {
    job_id: jobId("Route 104 Widening"),
    category: "Trucking",
    need,
    needed_by_spoken: "this afternoon",
  });
  await stubSupabaseAuth(page, [COORDINATOR]);

  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  const row = page.getByRole("row").filter({ has: page.getByRole("link", { name: ref, exact: true }) });
  await expect(row).toContainText("Recorded");
  await row.getByRole("link", { name: ref, exact: true }).click();

  const owner = page.getByRole("combobox", { name: "Owner" });
  await expect(owner.locator("option:checked")).toHaveText("Dispatch"); // Trucking's default
  await owner.selectOption({ label: "Equipment Manager" });
  await page.getByRole("button", { name: "Acknowledge" }).click();

  const fields = page.getByRole("group", { name: "Fields" });
  await expect(fields.getByText("Acknowledged", { exact: true })).toBeVisible();
  await expect(fields.getByText("Equipment Manager", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Acknowledge" })).toHaveCount(0);
  const history = page.getByRole("table", { name: "History" });
  const events = history.getByRole("row").filter({ has: page.getByRole("cell") });
  await expect(events).toHaveCount(2);
  await expect(events.nth(1).getByRole("cell").nth(1)).toHaveText("Casey Coordinator");
  await expect(events.nth(1).getByRole("cell").nth(2)).toHaveText("Acknowledged");

  await page.getByRole("link", { name: "Queue" }).click();
  await expect(row).toContainText("Acknowledged");
});
