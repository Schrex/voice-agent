import { expect, test } from "@playwright/test";

import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json.
const ADMIN: StubUser = {
  id: "7c1d4e2a-3b5f-4a6c-9d8e-0f1a2b3c4d02",
  email: "avery@example.com",
  password: "admin pass",
};

/** Tomorrow's New York calendar date as YYYY-MM-DD, and as the page shows it. */
function tomorrowInNewYork(): { iso: string; shown: string } {
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const iso = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(tomorrow);
  const shown = new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${iso}T00:00:00Z`));
  return { iso, shown };
}

test.beforeEach(async ({ page }) => {
  await stubSupabaseAuth(page, [ADMIN]);
});

test("admin sets tomorrow's on-duty Coordinator; it is kept after reload", async ({ page }) => {
  const { iso, shown } = tomorrowInNewYork();
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN.email);
  await page.getByLabel("Password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("link", { name: "Admin" }).click();
  await page.getByRole("link", { name: "Owners, staff, duty roster, settings" }).click();

  const form = page.getByRole("form", { name: "Set duty day" });
  await form.getByLabel("Date").fill(iso);
  await form.getByLabel("On duty").selectOption({ label: "Casey Coordinator" });
  await form.getByLabel("Backup").selectOption({ label: "Avery Admin" });
  await form.getByRole("button", { name: "Save duty day" }).click();

  const row = page.getByRole("row", { name: new RegExp(shown) });
  await expect(row).toContainText("Casey Coordinator");
  await expect(row).toContainText("Avery Admin");

  await page.reload();
  await expect(page.getByRole("row", { name: new RegExp(shown) })).toContainText(
    "Casey Coordinator",
  );
});
