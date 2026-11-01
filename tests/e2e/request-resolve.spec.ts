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

test("a coordinator works a request to Resolved; it leaves the queue and the detail shows the Outcome", async ({
  page,
  request: api,
}) => {
  const need = `e2e water truck ${Date.now()}`;
  const ref = await recordRequestByCall(api, DALE_PHONE, {
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
  await row.getByRole("link", { name: ref, exact: true }).click();

  const fields = page.getByRole("group", { name: "Fields" });
  await page.getByRole("button", { name: "Acknowledge" }).click(); // Dispatch, Trucking's default
  await page.getByRole("button", { name: "Move to In Progress" }).click();
  await expect(fields.getByText("In Progress", { exact: true })).toBeVisible();

  const resolve = page.getByRole("button", { name: "Resolve" });
  await expect(resolve).toBeDisabled(); // no Outcome, no explanation (AC9.2)
  await page.getByRole("combobox", { name: "Outcome" }).selectOption("Partially Fulfilled");
  await expect(resolve).toBeDisabled(); // still no explanation
  await page.getByLabel("Explanation").fill("One truck sent; the second is down for repair");
  await resolve.click();

  await expect(fields.getByText("Resolved", { exact: true }).first()).toBeVisible();
  await expect(fields.getByText("Partially Fulfilled", { exact: true })).toBeVisible();
  await expect(
    fields.getByText("One truck sent; the second is down for repair", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Resolve" })).toHaveCount(0);
  const history = page.getByRole("table", { name: "History" });
  const events = history.getByRole("row").filter({ has: page.getByRole("cell") });
  await expect(events).toHaveCount(4);
  await expect(events.nth(2).getByRole("cell").nth(2)).toHaveText("In Progress");
  await expect(events.nth(3).getByRole("cell").nth(1)).toHaveText("Casey Coordinator");
  await expect(events.nth(3).getByRole("cell").nth(2)).toHaveText("Resolved");

  await page.getByRole("link", { name: "Queue" }).click();
  await expect(page.getByRole("heading", { name: "Queue" })).toBeVisible();
  await expect(page.getByRole("link", { name: ref, exact: true })).toHaveCount(0);

  await page.goto(`/requests/${ref}`); // kept, not deleted (AC9.5)
  await expect(fields.getByText("Partially Fulfilled", { exact: true })).toBeVisible();
});
