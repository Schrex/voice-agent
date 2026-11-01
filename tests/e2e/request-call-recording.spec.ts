import { expect, test } from "@playwright/test";

import { deliverPostCall, jobId, recordRequestOnCall } from "./agent-stub";
import { stubSupabaseAuth, type StubUser } from "./supabase-stub";

// In tests/e2e/seed.json: a coordinator, and Dale Kramer (rostered) on Route 104 Widening.
// The recording comes from tests/e2e/elevenlabs_stub.py through the backend's audio proxy.
const COORDINATOR: StubUser = {
  id: "0b6f2c1e-8a8e-4d47-9c3f-5e2d7a1b0c01",
  email: "casey@example.com",
  password: "correct horse",
};
const DALE_PHONE = "+15855550101";

test("a request's linked call shows its transcript and plays its recording", async ({
  page,
  request: api,
}) => {
  const need = `e2e loader ${Date.now()}`;
  const { ref, conversationId } = await recordRequestOnCall(api, DALE_PHONE, {
    job_id: jobId("Route 104 Widening"),
    category: "Equipment",
    need,
    quantity: 1,
    unit: "loader",
    needed_by_spoken: "tomorrow",
  });
  await deliverPostCall(
    api,
    conversationId,
    [
      { role: "agent", message: "This call is recorded. What do you need?", time_in_call_secs: 0 },
      { role: "user", message: `I need a ${need} at Route 104 tomorrow.`, time_in_call_secs: 4 },
    ],
    75,
  );
  await stubSupabaseAuth(page, [COORDINATOR]);

  await page.goto("/login");
  await page.getByLabel("Email").fill(COORDINATOR.email);
  await page.getByLabel("Password").fill(COORDINATOR.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("link", { name: ref, exact: true }).click();

  const call = page.getByRole("region", { name: /^Call / });
  await expect(call).toHaveCount(1);
  await expect(call.getByText("Duration 1:15")).toBeVisible();
  await expect(call.getByRole("list", { name: "Transcript" }).getByRole("listitem")).toHaveText([
    "Agent: This call is recorded. What do you need?",
    `Foreman: I need a ${need} at Route 104 tomorrow.`,
  ]);

  await call.getByRole("button", { name: "Play recording" }).click();
  const audio = call.getByLabel("Recording");
  await expect(audio).toBeVisible();
  await expect
    .poll(() => audio.evaluate((a: HTMLAudioElement) => (a.paused ? 0 : a.currentTime)), {
      timeout: 10_000,
    })
    .toBeGreaterThan(0);
  expect(await audio.evaluate((a: HTMLAudioElement) => a.duration)).toBeCloseTo(3, 0);
});
