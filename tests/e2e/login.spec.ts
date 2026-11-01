import { expect, test } from "@playwright/test";

import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json as a coordinator.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
// A Supabase user with no staff row.
const OUTSIDER: StubUser = {
  id: "5f0c9a77-1d2e-4c3b-8a90-ffeeddccbbaa",
  email: "outsider@example.com",
  password: "whatever",
};

test.beforeEach(async ({ page }) => {
  await stubSupabaseAuth(page, [COORDINATOR, OUTSIDER]);
});

async function logIn(page: import("@playwright/test").Page, user: StubUser) {
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Log in" }).click();
}

test("login lands on the empty queue; logout returns to login", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);

  await logIn(page, COORDINATOR);

  await expect(page.getByRole("heading", { name: "Queue" })).toBeVisible();
  await expect(page.getByText("No requests.")).toBeVisible();
  await expect(page.getByText("Casey Coordinator")).toBeVisible();
  await expect(page).toHaveURL(/\/$/);

  await page.getByRole("button", { name: "Log out" }).click();

  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("a Supabase user who is not staff is refused", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, OUTSIDER);

  await expect(page.getByRole("alert")).toContainText("not on the staff list");
  await expect(page.getByRole("heading", { name: "Queue" })).toHaveCount(0);
});

test("a wrong password stays on login with the error", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, { ...COORDINATOR, password: "nope" });

  await expect(page.getByRole("alert")).toContainText("Invalid login credentials");
  await expect(page).toHaveURL(/\/login$/);
});
