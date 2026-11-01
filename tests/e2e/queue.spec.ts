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
// The queue refetches every 10 s (QueuePage REFRESH_MS; architecture §1). A request recorded just
// after a fetch shows on the next one, up to a full interval later plus fetch and render time, so
// waiting exactly 10 s races the poll. Allow one interval plus margin.
const QUEUE_REFRESH_MS = 10_000;
const NEXT_REFRESH_TIMEOUT_MS = QUEUE_REFRESH_MS + 5_000;

test("a request recorded by the agent appears in the open queue on the next 10 s refresh, without reload", async ({
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
    job_spoken: "the 104 job",
    category: "Trucking",
    need,
    quantity: 3,
    unit: "trucks",
    needed_by_spoken: "tomorrow at seven",
  });

  const row = page.getByRole("row").filter({ hasText: ref });
  await expect(row).toBeVisible({ timeout: NEXT_REFRESH_TIMEOUT_MS });
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
