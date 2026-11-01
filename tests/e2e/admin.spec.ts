import { expect, test, type Page } from "@playwright/test";

import { E2E_HOOK_SECRET, stubSupabaseAuth, type StubUser } from "./supabase-stub";

// Both in tests/e2e/seed.json.
const ADMIN: StubUser = {
  id: "7c1d4e2a-3b5f-4a6c-9d8e-0f1a2b3c4d02",
  email: "avery@example.com",
  password: "admin pass",
};
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};

// The e2e database persists between runs, so every value this spec writes is new each run.
const run = String(Date.now()).slice(-6);

test.beforeEach(async ({ page }) => {
  await stubSupabaseAuth(page, [ADMIN, COORDINATOR]);
});

async function logIn(page: Page, user: StubUser) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Queue" })).toBeVisible();
}

let calls = 0;

/** A new call from this number, as ElevenLabs would announce it to the backend. */
async function callStart(page: Page, callerE164: string) {
  calls += 1;
  const response = await page.request.post("/hooks/call-start", {
    headers: { "X-Hook-Secret": E2E_HOOK_SECRET },
    data: { caller_id: callerE164, conversation_id: `conv_e2e_admin_${run}_${calls}` },
  });
  expect(response.ok()).toBe(true);
  return (await response.json()).dynamic_variables as { rejected: boolean; foreman_first_name: string };
}

test("admin adds a job alias; it is kept after reload", async ({ page }) => {
  const alias = `the widening ${run}`;
  await logIn(page, ADMIN);
  await page.getByRole("link", { name: "Admin" }).click();
  const job = page.getByRole("row", { name: /Route 104 Widening/ });

  await job.getByLabel("New alias").fill(alias);
  await job.getByRole("button", { name: "Add alias" }).click();
  await expect(job.getByText(alias)).toBeVisible();

  await page.reload();
  await expect(page.getByRole("row", { name: /Route 104 Widening/ }).getByText(alias)).toBeVisible();
});

test("admin adds a foreman, then deactivates him: his number is rejected at call start", async ({
  page,
}) => {
  const phone = `+1716555${run.slice(-4)}`;
  const lastName = `Tester${run}`;
  await logIn(page, ADMIN);
  await page.goto("/admin");

  const form = page.getByRole("form", { name: "Add foreman" });
  await form.getByLabel("First name").fill("Sam");
  await form.getByLabel("Last name").fill(lastName);
  await form.getByLabel("Phone").fill(phone);
  await form.getByRole("button", { name: "Add foreman" }).click();
  const row = page.getByRole("row", { name: new RegExp(`Sam ${lastName}`) });
  await expect(row).toContainText(phone);
  expect(await callStart(page, phone)).toMatchObject({ rejected: false, foreman_first_name: "Sam" });

  await row.getByRole("button", { name: "Deactivate" }).click();
  await expect(row.getByText("Inactive")).toBeVisible();
  expect(await callStart(page, phone)).toMatchObject({ rejected: true, foreman_first_name: "" });
});

test("a coordinator gets no admin screens", async ({ page }) => {
  await logIn(page, COORDINATOR);
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);

  await page.goto("/admin");
  await expect(page.getByRole("alert")).toContainText("Admins only");
  await expect(page.getByRole("heading", { name: "Foremen" })).toHaveCount(0);
});
