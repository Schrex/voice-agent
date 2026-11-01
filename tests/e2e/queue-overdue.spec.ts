import { execFileSync } from "node:child_process";

import { expect, test } from "@playwright/test";

import { jobId, recordRequestByCall } from "./agent-stub";
import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json: a coordinator, Dale Kramer (rostered) on Route 104 Widening, and the
// Owner Dispatch (default for Trucking).
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE_PHONE = "+15855550101";

/**
 * The backend under test runs on the real clock, so instead of waiting out the ack window the
 * spec moves the request's ack due time into the past, straight in the e2e database.
 */
function ackWindowOver(ref: string): void {
  const url = process.env.E2E_DATABASE_URL!.replace("postgresql+psycopg://", "postgresql://");
  const number = Number(ref.replace("R-", ""));
  execFileSync("psql", [
    url,
    "-tAc",
    `UPDATE requests SET ack_due_at = now() - interval '1 minute' WHERE ref = ${number}`,
  ]);
}

test("a request not Acknowledged within its ack window is flagged Overdue and counted in the queue", async ({
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
  const queue = page.getByRole("table").first();
  const row = queue.getByRole("row").filter({ has: page.getByRole("link", { name: ref, exact: true }) });
  await expect(row.getByRole("cell").nth(6)).toHaveText("Recorded"); // within its window
  await expect(page.getByText("Overdue (0)")).toBeVisible();

  ackWindowOver(ref);
  await page.reload();
  await expect(page.getByText("Overdue (1)")).toBeVisible();
  await expect(row.getByRole("cell").nth(6)).toHaveText("Recorded Overdue");

  await row.getByRole("link", { name: ref, exact: true }).click();
  await page.getByRole("button", { name: "Acknowledge" }).click(); // Dispatch, Trucking's default
  await expect(page.getByRole("button", { name: "Acknowledge" })).toHaveCount(0);
  await page.getByRole("link", { name: "Queue" }).click();
  await expect(row.getByRole("cell").nth(6)).toHaveText("Acknowledged");
  await expect(page.getByText("Overdue (0)")).toBeVisible();
});
