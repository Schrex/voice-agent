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

test("a request recorded by the agent appears in the open queue within 10 s, without reload", async ({
  page,
  request: api,
}) => {
  await stubSupabaseAuth(page, [COORDINATOR]);
  let queueLoads = 0;
  page.on("request", (r) => {
    if (r.resourceType() === "document") queueLoads += 1;
  });

  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Queue" })).toBeVisible();
  // The first queue fetch has happened (table or empty state shown) before the call.
  await expect(page.getByRole("table").or(page.getByText("No requests."))).toBeVisible();
  const loadsBefore = queueLoads;

  const need = `e2e dump trucks ${Date.now()}`;
  const ref = await recordRequestByCall(api, DALE_PHONE, {
    job_id: jobId("Route 104 Widening"),
    category: "Trucking",
    need,
    quantity: 3,
    unit: "trucks",
    needed_by_spoken: "tomorrow at seven",
  });

  const row = page.getByRole("row").filter({ hasText: ref });
  await expect(row).toBeVisible({ timeout: 10_000 });
  await expect(row.getByRole("cell")).toHaveText([
    ref,
    "Route 104 Widening",
    need,
    "3 trucks",
    "tomorrow at seven",
    "—",
    "Recorded",
    /^0m\s*Recorded /,
  ]);
  expect(queueLoads).toBe(loadsBefore); // no page reload
});
