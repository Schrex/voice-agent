import { expect, test } from "@playwright/test";

import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json: a coordinator, Dale Kramer (rostered) on Route 104 Widening, and the
// Owners Dispatch and Equipment Manager.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
// Spec J7: "quick-entry form (target < 30 s)".
const TARGET_MS = 30_000;
// A deliberate typist, not a script: every key is held back this long (about 6 keys a second).
const KEY_DELAY_MS = 150;

test("a coordinator logs an answered call by keyboard alone in under 30 s; it is in the queue", async ({
  page,
}) => {
  await stubSupabaseAuth(page, [COORDINATOR]);
  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("link", { name: "Log a request" }).click();
  const foreman = page.getByRole("combobox", { name: "Foreman" });
  await expect(foreman).toBeFocused();
  const need = `e2e quick entry ${Date.now()}`;

  // Timed: from the empty form with the Foreman focused to the confirmation. Keyboard only.
  const started = Date.now();
  const type = (text: string) => page.keyboard.type(text, { delay: KEY_DELAY_MS });
  const next = () => page.keyboard.press("Tab", { delay: KEY_DELAY_MS });
  await type("Dale"); // Foreman (select: type-ahead)
  await next();
  await type("Route"); // Job
  await next();
  await type("Truck"); // Category
  await next();
  await type(need); // Need
  await next();
  await type("3"); // Quantity
  await next();
  await type("trucks"); // Unit
  await next();
  await type("tomorrow 7am"); // Needed-by
  await next();
  await type("Disp"); // Owner (optional): Dispatch
  await next(); // "Log request"
  await page.keyboard.press("Enter");
  const status = page.getByRole("status");
  await expect(status).toContainText("logged: Acknowledged.");
  const elapsed = Date.now() - started;
  test.info().annotations.push({ type: "quick-entry ms", description: String(elapsed) });
  console.log(`quick entry by keyboard: ${elapsed} ms (target < ${TARGET_MS} ms)`);
  expect(elapsed).toBeLessThan(TARGET_MS);

  const ref = (await status.getByRole("link").textContent())!;
  await expect(foreman).toBeFocused(); // ready for the next call
  await page.getByRole("link", { name: "Queue" }).click();
  const row = page.getByRole("row").filter({ has: page.getByRole("link", { name: ref, exact: true }) });
  await expect(row).toContainText("Route 104 Widening");
  await expect(row).toContainText(need);
  await expect(row).toContainText("3 trucks");
  await expect(row).toContainText("Acknowledged");

  await row.getByRole("link", { name: ref, exact: true }).click();
  const fields = page.getByRole("group", { name: "Fields" });
  await expect(fields.getByText("Coordinator-logged", { exact: true })).toBeVisible();
  await expect(fields.getByText("Dale Kramer", { exact: true })).toBeVisible();
  await expect(fields.getByText("Dispatch", { exact: true })).toBeVisible();
});
