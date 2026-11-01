import { expect, test } from "@playwright/test";

import { jobId, recordRequestByCall } from "./agent-stub";
import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json: a coordinator, and Dale Kramer (rostered) on Route 104 Widening.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE_PHONE = "+15855550101";

test("opening a recorded request shows its fields and the Recorded event in its history", async ({
  page,
  request: api,
}) => {
  const need = `e2e excavator ${Date.now()}`;
  const ref = await recordRequestByCall(api, DALE_PHONE, {
    job_id: jobId("Route 104 Widening"),
    job_spoken: "the 104 job",
    category: "Equipment",
    need,
    quantity: 1,
    unit: "excavator",
    needed_by_spoken: "Monday morning",
  });
  await stubSupabaseAuth(page, [COORDINATOR]);

  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("link", { name: ref, exact: true }).click();

  await expect(page).toHaveURL(`/requests/${ref}`);
  await expect(page.getByRole("heading", { name: ref })).toBeVisible();
  const fields = page.getByRole("group", { name: "Fields" });
  await expect(fields.getByRole("definition")).toHaveText([
    "Dale Kramer",
    "Route 104 Widening",
    "Equipment",
    need,
    "1 excavator",
    // "Monday morning": the next Monday at 7:00 AM, resolved by the backend.
    /^Mon, \w{3} \d{1,2}, 7:00 AM$/,
    "Planned",
    "Recorded",
    "—",
    "AI call",
    /^\w{3}, \w{3} \d{1,2}, \d{1,2}:\d{2} (AM|PM)$/,
  ]);

  const history = page.getByRole("table", { name: "History" });
  const events = history.getByRole("row").filter({ has: page.getByRole("cell") });
  await expect(events).toHaveCount(1);
  await expect(events.first().getByRole("cell").nth(1)).toHaveText("Agent");
  await expect(events.first().getByRole("cell").nth(2)).toHaveText("Recorded");
  await expect(events.first().getByRole("cell").nth(3)).toContainText(`ref: ${ref}`);
  await expect(events.first().getByRole("cell").nth(3)).toContainText(`need: ${need}`);
});
