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
 * The backend under test runs on the real clock, so instead of waiting 2 h the spec moves the
 * request's resolved time back past the Uninformed threshold, straight in the e2e database.
 */
function resolvedLongAgo(ref: string): void {
  const url = process.env.E2E_DATABASE_URL!.replace("postgresql+psycopg://", "postgresql://");
  const number = Number(ref.replace("R-", ""));
  execFileSync("psql", [
    url,
    "-tAc",
    `UPDATE requests SET resolved_at = now() - interval '2 hours 1 minute' WHERE ref = ${number}`,
  ]);
}

test("a Resolved request not marked Foreman Informed within 2 h is listed Uninformed; marking clears it", async ({
  page,
  request: api,
}) => {
  const need = `e2e lowboy ${Date.now()}`;
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
  await expect(page.getByRole("heading", { name: "Uninformed (0)" })).toBeVisible();
  await page.getByRole("link", { name: ref, exact: true }).click();

  await page.getByRole("button", { name: "Acknowledge" }).click(); // Dispatch, Trucking's default
  await page.getByRole("combobox", { name: "Outcome" }).selectOption("Fulfilled");
  await page.getByLabel("Explanation").fill("Lowboy booked for 7 AM");
  await page.getByRole("button", { name: "Resolve" }).click();
  const informed = page.getByRole("region", { name: "Foreman Informed" });
  await expect(informed).toContainText("Not marked Foreman Informed");
  await expect(informed.getByText("Uninformed", { exact: true })).toHaveCount(0); // within 2 h

  resolvedLongAgo(ref);
  await page.getByRole("link", { name: "Queue" }).click();
  await expect(page.getByRole("heading", { name: "Uninformed (1)" })).toBeVisible();
  const list = page.getByRole("table", { name: "Uninformed" });
  const row = list.getByRole("row").filter({ has: page.getByRole("link", { name: ref, exact: true }) });
  await expect(row.getByRole("cell")).toHaveText([
    ref,
    "Dale Kramer",
    "Route 104 Widening",
    need,
    "Fulfilled",
    /.+/,
  ]);

  await row.getByRole("link", { name: ref, exact: true }).click();
  await expect(informed.getByText("Uninformed", { exact: true })).toBeVisible();
  await informed.getByRole("button", { name: "Mark Foreman Informed" }).click();
  await expect(informed).toContainText(/Foreman Informed \w{3}, \w{3} \d+/);
  await expect(informed.getByText("Uninformed", { exact: true })).toHaveCount(0);
  const history = page.getByRole("table", { name: "History" });
  const events = history.getByRole("row").filter({ has: page.getByRole("cell") });
  await expect(events.last().getByRole("cell").nth(1)).toHaveText("Casey Coordinator");
  await expect(events.last().getByRole("cell").nth(2)).toHaveText("Foreman Informed");

  await page.getByRole("link", { name: "Queue" }).click();
  await expect(page.getByRole("heading", { name: "Uninformed (0)" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Uninformed" })).toHaveCount(0);
});
